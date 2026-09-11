"""Inbound drop-message persistence and tunnel-stream processing."""

import socket
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from metor.core.api import ContentType, Delivery, InboxNotificationEvent, IpcEvent
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    MessageDirection,
    MessageStatus,
    SettingKey,
)

# Local Package Imports
from ...notify import NotificationPayload
from ..stream import TcpStreamReader
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
        voice_frame_callback: Optional[
            Callable[[socket.socket, str, str, str], bool]
        ] = None,
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
            voice_frame_callback (Optional[Callable]): Bounded DROP Voice frame handler.

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
        self._voice_frame_callback = voice_frame_callback

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
        if self._mm.has_inbound_message(onion, msg_id):
            self._acknowledge_drop(conn, msg_id)
            return False

        unread_drop_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
        if (
            unread_drop_limit != -1
            and self._mm.get_unread_drop_count(onion) >= unread_drop_limit
        ):
            self._hm.log_event(
                HistoryEvent.FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text='Drop backlog limit reached.',
            )
            return True

        queue_result = self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.IN,
            delivery=Delivery.DROP,
            content_type=ContentType.TEXT,
            payload=content,
            status=MessageStatus.UNREAD,
            msg_id=msg_id,
            timestamp=timestamp,
        )
        self._acknowledge_drop(conn, msg_id)
        if queue_result.was_duplicate:
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
        return False

    @staticmethod
    def _acknowledge_drop(conn: socket.socket, msg_id: str) -> None:
        """Sends one best-effort DROP acknowledgement.

        Args:
            conn (socket.socket): The active authenticated socket.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        try:
            conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
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
                    conn.sendall(
                        f'{TorCommand.REJECT.value} drops_disabled\n'.encode('utf-8')
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
