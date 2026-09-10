"""Thin composition root for application-layer message routing."""

import socket
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

from metor.core.api import EventType, IpcEvent, JsonValue
from metor.data import (
    ContactManager,
    HistoryActor,
    HistoryManager,
    HistoryReasonCode,
    MessageManager,
)

# Local Package Imports
from ...notify import NotificationPayload
from ..state import StateTracker
from ..stream import TcpStreamReader
from .drop import DropMessageRouter
from .fallback import FallbackRouter
from .live import LiveMessageRouter

if TYPE_CHECKING:
    from metor.data.profile import Config


class MessageRouter:
    """Exposes one routing boundary backed by explicit route components."""

    def __init__(
        self,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        has_live_consumers_callback: Callable[[], bool],
        notify_callback: Callable[[NotificationPayload], None],
        config: 'Config',
    ) -> None:
        """Composes the live, drop, and fallback routing components.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            state (StateTracker): Connection and delivery state tracker.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            has_clients_callback (Callable[[], bool]): Connected-client check.
            has_live_consumers_callback (Callable[[], bool]): Live-consumer check.
            notify_callback (Callable[[NotificationPayload], None]): Detached notifier.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._live: LiveMessageRouter = LiveMessageRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            state=state,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            has_live_consumers_callback=has_live_consumers_callback,
            notify_callback=notify_callback,
            config=config,
        )
        self._drop: DropMessageRouter = DropMessageRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            notify_callback=notify_callback,
            config=config,
        )
        self._fallback: FallbackRouter = FallbackRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            state=state,
            broadcast_callback=broadcast_callback,
            config=config,
        )

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """Delegates outbound live delivery to the live router.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        self._live.send_message(target, msg, msg_id)

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> bool:
        """Delegates inbound live-message acceptance to the live router.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            bool: True when the session must close for backlog pressure.
        """
        return self._live.process_incoming_msg(conn, onion, payload_id, b64_payload)

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """Delegates incoming acknowledgement handling to the live router.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        self._live.process_incoming_ack(onion, msg_id)

    def process_incoming_read_receipt(self, onion: str, msg_id: str) -> None:
        """Delegates incoming read-receipt handling to the live router.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The consumed message identifier.

        Returns:
            None
        """
        self._live.process_incoming_read_receipt(onion, msg_id)

    def process_incoming_drop_over_session(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> None:
        """Delegates a session-carried drop frame to the drop router.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            None
        """
        self._drop.process_incoming_drop_over_session(
            conn, onion, payload_id, b64_payload
        )

    def process_async_drop(
        self, conn: socket.socket, stream: TcpStreamReader, onion: str
    ) -> None:
        """Delegates a dedicated drop-tunnel stream to the drop router.

        Args:
            conn (socket.socket): The dedicated drop-tunnel socket.
            stream (TcpStreamReader): The constrained tunnel stream.
            onion (str): The peer onion identity.

        Returns:
            None
        """
        self._drop.process_async_drop(conn, stream, onion)

    def convert_unacked_messages_to_drop(
        self,
        alias: str,
        onion: str,
        request_id: Optional[str] = None,
        emit_event: bool = True,
        history_actor: HistoryActor = HistoryActor.SYSTEM,
        history_reason_code: HistoryReasonCode = (
            HistoryReasonCode.UNACKED_LIVE_CONVERTED_TO_DROP
        ),
    ) -> Dict[str, Tuple[str, str]]:
        """Delegates terminal live-to-drop conversion to the fallback router.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            request_id (Optional[str]): Optional request correlation identifier.
            emit_event (bool): Whether to emit a fallback-success event.
            history_actor (HistoryActor): The history actor for queued-drop logging.
            history_reason_code (HistoryReasonCode): The queued-drop history reason.

        Returns:
            Dict[str, Tuple[str, str]]: The converted unacknowledged messages.
        """
        return self._fallback.convert_unacked_messages_to_drop(
            alias,
            onion,
            request_id=request_id,
            emit_event=emit_event,
            history_actor=history_actor,
            history_reason_code=history_reason_code,
        )

    def replay_unacked_messages(self, onion: str) -> list[str]:
        """Delegates pending live replay to the fallback router.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[str]: The message IDs replayed successfully.
        """
        return self._fallback.replay_unacked_messages(onion)

    def force_fallback(
        self, target: str
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """Delegates explicit live-to-drop fallback to the fallback router.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: The operation result.
        """
        return self._fallback.force_fallback(target)

    def finalize_pending_live_messages(self) -> None:
        """Delegates shutdown fallback finalization to the fallback router.

        Args:
            None

        Returns:
            None
        """
        self._fallback.finalize_pending_live_messages()
