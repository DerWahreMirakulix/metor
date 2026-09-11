"""Inbound drop-message persistence and tunnel-stream processing."""

import socket
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from metor.core.api import InboxNotificationEvent, IpcEvent, RuntimeStateChangedEvent
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    InboundDropOutcome,
    SettingKey,
)

# Local Package Imports
from ...notify import NotificationPayload
from ..state import StateTracker
from ..stream import TcpStreamReader
from .admission import FrameAdmission
from .codec import decode_drop_payload

if TYPE_CHECKING:
    from metor.data import ContactManager, HistoryManager, MessageManager
    from metor.data.profile import Config


class DropMessageRouter:
    """Owns durable inbound DROP acceptance for tunnel and session channels."""

    def __init__(
        self,
        cm: 'ContactManager',
        hm: 'HistoryManager',
        mm: 'MessageManager',
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        notify_callback: Callable[[NotificationPayload], None],
        config: 'Config',
        state: StateTracker,
        voice_frame_callback: Optional[
            Callable[[socket.socket, str, str, str], FrameAdmission]
        ] = None,
        transition_lock: Optional[threading.RLock] = None,
    ) -> None:
        """Initializes drop routing with its explicit collaborators.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            has_clients_callback (Callable[[], bool]): Connected-client check.
            notify_callback (Callable[[NotificationPayload], None]): Detached notifier.
            config (Config): Profile configuration.
            state (StateTracker): Shared socket frame serializer.
            voice_frame_callback (Optional[Callable]): Bounded DROP Voice frame handler.
            transition_lock (Optional[threading.RLock]): State publication barrier.

        Returns:
            None
        """
        self._cm: 'ContactManager' = cm
        self._hm: 'HistoryManager' = hm
        self._mm: 'MessageManager' = mm
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._notify_callback: Callable[[NotificationPayload], None] = notify_callback
        self._config: 'Config' = config
        self._state = state
        self._voice_frame_callback = voice_frame_callback
        self._transition_lock = transition_lock or threading.RLock()

    def _process_inbound_drop_frame(
        self,
        conn: socket.socket,
        onion: str,
        payload_id: str,
        b64_payload: str,
        transport: str,
    ) -> bool:
        """Persists and acknowledges one inbound drop frame.

        Args:
            conn (socket.socket): The authenticated channel socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.
            transport (str): The transport label for projected history.

        Returns:
            bool: True when the drop backlog is full.
        """
        decoded_payload: Optional[Tuple[str, str, Optional[str]]] = decode_drop_payload(
            payload_id, b64_payload
        )
        if decoded_payload is None:
            return False
        msg_id, content, timestamp = decoded_payload
        with self._transition_lock:
            return self._store_decoded_drop(
                conn, onion, msg_id, content, timestamp, transport
            )

    def _store_decoded_drop(
        self,
        conn: socket.socket,
        onion: str,
        msg_id: str,
        content: str,
        timestamp: Optional[str],
        transport: str,
    ) -> bool:
        """Commits and publishes one validated DROP under the state barrier."""
        unread_drop_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
        outcome = self._mm.store_inbound_drop_text(
            onion, msg_id, content, timestamp, unread_drop_limit
        )
        if outcome is InboundDropOutcome.LIMIT:
            self._hm.log_event(
                HistoryEvent.FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text='Drop backlog limit reached.',
            )
            return True
        if outcome is InboundDropOutcome.CONFLICT:
            return False
        self._acknowledge_drop(conn, msg_id)
        if outcome is InboundDropOutcome.DUPLICATE:
            return False

        self._hm.log_event(
            HistoryEvent.RECEIVED, onion, actor=HistoryActor.REMOTE, transport=transport
        )
        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        if alias:
            if self._has_clients_callback():
                self._broadcast(
                    InboxNotificationEvent(alias=alias, onion=onion, count=1)
                )
            else:
                self._notify_callback(
                    NotificationPayload(
                        kind='inbox_notification',
                        peer_alias=alias,
                        peer_onion=onion,
                        count=1,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )
        self._broadcast(RuntimeStateChangedEvent(scope='inbox', onion=onion))
        return False

    def _acknowledge_drop(self, conn: socket.socket, msg_id: str) -> None:
        """Sends one best-effort DROP acknowledgement.

        Args:
            conn (socket.socket): The active authenticated socket.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        try:
            self._state.send_frame(
                conn, f'{TorCommand.DROP_ACK.value} {msg_id}\n'.encode('utf-8')
            )
        except Exception:
            pass

    def process_incoming_drop_over_session(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> None:
        """Processes a drop frame that arrived over an active session.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            None
        """
        if self._config.get_bool(SettingKey.ALLOW_DROPS):
            self._process_inbound_drop_frame(
                conn, onion, payload_id, b64_payload, 'session'
            )

    def allows_inbound_drops(self) -> bool:
        """Returns the shared semantic DROP admission policy.

        Args:
            None

        Returns:
            bool: True when inbound DROP content is enabled.
        """
        return self._config.get_bool(SettingKey.ALLOW_DROPS)

    def reject_disabled_drop(self, conn: socket.socket) -> None:
        """Applies privacy-aware rejection for disabled inbound DROP content.

        Args:
            conn (socket.socket): Authenticated peer socket.

        Returns:
            None
        """
        if not self._config.get_bool(SettingKey.EXPOSE_DROP_REJECTION):
            return
        try:
            self._state.send_frame(
                conn, f'{TorCommand.REJECT.value} drops_disabled\n'.encode('utf-8')
            )
        except OSError:
            pass

    def process_async_drop(
        self, conn: socket.socket, stream: TcpStreamReader, onion: str
    ) -> None:
        """Consumes DROP frames from a dedicated tunnel and closes it on completion.

        Args:
            conn (socket.socket): The dedicated drop-tunnel socket.
            stream (TcpStreamReader): The constrained tunnel stream.
            onion (str): The peer onion identity.

        Returns:
            None
        """
        if not self._config.get_bool(SettingKey.ALLOW_DROPS):
            if self._config.get_bool(SettingKey.EXPOSE_DROP_REJECTION):
                try:
                    self._state.send_frame(
                        conn,
                        f'{TorCommand.REJECT.value} drops_disabled\n'.encode('utf-8'),
                    )
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass
            return

        try:
            while True:
                message: Optional[str] = stream.read_line()
                if not message:
                    break
                if message.startswith(f'{TorCommand.DROP.value} '):
                    parts: list[str] = message.split(' ', 2)
                    if len(parts) == 3 and self._process_inbound_drop_frame(
                        conn, onion, parts[1], parts[2], 'tunnel'
                    ):
                        break
                elif any(
                    message.startswith(f'{command.value} ')
                    for command in (
                        TorCommand.DROP_VOICE_BEGIN,
                        TorCommand.DROP_VOICE_CHUNK,
                        TorCommand.DROP_VOICE_END,
                    )
                ):
                    parts = message.split(' ', 1)
                    if (
                        len(parts) != 2
                        or self._voice_frame_callback is None
                        or self._voice_frame_callback(conn, onion, parts[0], parts[1])
                    ):
                        break
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
