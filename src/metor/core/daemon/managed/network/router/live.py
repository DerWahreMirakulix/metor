"""Live-message routing, durable acceptance, and acknowledgement handling."""

import socket
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, Tuple, cast

from metor.core.api import (
    AckEvent,
    AutoFallbackQueuedEvent,
    ContentType,
    Delivery,
    InboxNotificationEvent,
    IpcEvent,
    LiveMessageResourcePressureEvent,
    LiveMessageUnavailableEvent,
    MessageOperationReason,
    MessageReceivedEvent,
    ReadReceiptEvent,
    RuntimeStateChangedEvent,
    TextContent,
    get_current_request_id,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
    MessageDirection,
    MessageStatus,
    PendingLiveAdmission,
    SettingKey,
)

# Local Package Imports
from ..state import StateTracker
from .admission import FrameAdmission
from ...notify import NotificationPayload
from .codec import build_message_frame, decode_live_payload

if TYPE_CHECKING:
    from metor.data import ContactManager, HistoryManager, MessageManager
    from metor.data.profile import Config


class LiveMessageRouter:
    """Owns outbound live delivery and crash-safe inbound live acceptance."""

    def __init__(
        self,
        cm: 'ContactManager',
        hm: 'HistoryManager',
        mm: 'MessageManager',
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        has_live_consumers_callback: Callable[[], bool],
        notify_callback: Callable[[NotificationPayload], None],
        config: 'Config',
        transition_lock: Optional[threading.RLock] = None,
        purge_fence: Optional[threading.Event] = None,
    ) -> None:
        """Initializes live routing with its explicit collaborators.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            state (StateTracker): Connection and pending-message state.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            has_clients_callback (Callable[[], bool]): Connected-client check.
            has_live_consumers_callback (Callable[[], bool]): Live-consumer check.
            notify_callback (Callable[[NotificationPayload], None]): Detached notifier.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._cm: 'ContactManager' = cm
        self._hm: 'HistoryManager' = hm
        self._mm: 'MessageManager' = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._has_live_consumers_callback: Callable[[], bool] = (
            has_live_consumers_callback
        )
        self._notify_callback: Callable[[NotificationPayload], None] = notify_callback
        self._config: 'Config' = config
        self._transition_lock = transition_lock or threading.RLock()
        self._purge_fence = purge_fence or threading.Event()

    def _live_frame_claim(self, onion: str, msg_id: str) -> Callable[[], bool]:
        """Creates a last-moment emission claim ordered with fallback."""
        generation = self._state.get_live_generation(onion, msg_id)

        def claim() -> bool:
            with self._transition_lock:
                return (
                    not self._purge_fence.is_set()
                    and generation is not None
                    and self._state.is_live_generation(onion, msg_id, generation)
                )

        return claim

    def _should_defer_live_message(self, onion: str) -> bool:
        """Checks whether one outbound live message should stay recoverable.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if live recovery is still plausible.
        """
        return (
            self._state.has_live_reconnect_grace(onion)
            or self._state.is_retunneling(onion)
            or self._state.has_outbound_attempt(onion)
            or self._state.has_scheduled_auto_reconnect(onion)
            or self._state.is_connected_or_pending(onion)
        )

    def _queue_pending_live_message(
        self, onion: str, msg: str, msg_id: str, timestamp: str
    ) -> Optional[MessageOperationReason]:
        """Persists one outbound live message until ACK or terminal fallback.

        Args:
            onion (str): The peer onion identity.
            msg (str): The message payload.
            msg_id (str): The stable logical message identifier.
            timestamp (str): The authored timestamp.

        Returns:
            Optional[MessageOperationReason]: Limit reason, or None after queueing.
        """
        with self._transition_lock:
            if self._purge_fence.is_set():
                return MessageOperationReason.INVALID_SELECTION
            outcome = self._mm.queue_pending_live_if_capacity(
                onion,
                ContentType.TEXT,
                msg,
                msg_id,
                timestamp,
                0,
                self._config.get_int(SettingKey.MAX_PENDING_LIVE_MSGS),
                self._config.get_int(SettingKey.MAX_PENDING_LIVE_BYTES),
            )
            if outcome is PendingLiveAdmission.ACCEPTED:
                self._state.add_unacked_message(onion, msg_id, msg, timestamp)
        if outcome is PendingLiveAdmission.COUNT_LIMIT:
            return MessageOperationReason.COUNT_LIMIT
        if outcome is PendingLiveAdmission.BYTE_LIMIT:
            return MessageOperationReason.BYTE_LIMIT
        if outcome is PendingLiveAdmission.DUPLICATE:
            return MessageOperationReason.INVALID_SELECTION
        return None

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """Sends one live message or durably defers it for recovery.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            return
        alias, onion = resolved
        request_id: Optional[str] = get_current_request_id()
        self._state.remember_message_request_id(msg_id, request_id)
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        timestamp: str = datetime.now(timezone.utc).isoformat()

        if conn is None:
            if self._should_defer_live_message(onion):
                limit_reason = self._queue_pending_live_message(
                    onion, msg, msg_id, timestamp
                )
                if limit_reason is not None:
                    pending_count, pending_bytes = self._mm.get_pending_live_usage()
                    self._broadcast(
                        LiveMessageResourcePressureEvent(
                            alias=alias,
                            onion=onion,
                            msg_id=msg_id,
                            reason=limit_reason,
                            pending_count=pending_count,
                            pending_bytes=pending_bytes,
                            request_id=request_id,
                        )
                    )
                return
            if not self._config.get_bool(SettingKey.FALLBACK_TO_DROP):
                self._broadcast(
                    LiveMessageUnavailableEvent(
                        alias=alias,
                        onion=onion,
                        msg_id=msg_id,
                        request_id=request_id,
                    )
                )
                return
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                delivery=Delivery.DROP,
                content_type=ContentType.TEXT,
                payload=msg,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
            )
            self._hm.log_event(
                HistoryEvent.QUEUED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_code=HistoryReasonCode.AUTO_FALLBACK_TO_DROP,
            )
            self._broadcast(
                AutoFallbackQueuedEvent(
                    alias=alias,
                    onion=onion,
                    msg_id=msg_id,
                    request_id=request_id,
                )
            )
            return

        try:
            limit_reason = self._queue_pending_live_message(
                onion, msg, msg_id, timestamp
            )
            if limit_reason is not None:
                pending_count, pending_bytes = self._mm.get_pending_live_usage()
                self._broadcast(
                    LiveMessageResourcePressureEvent(
                        alias=alias,
                        onion=onion,
                        msg_id=msg_id,
                        reason=limit_reason,
                        pending_count=pending_count,
                        pending_bytes=pending_bytes,
                        request_id=request_id,
                    )
                )
                return
            self._state.send_frame(
                conn,
                build_message_frame(TorCommand.MSG, msg_id, msg, timestamp).encode(
                    'utf-8'
                ),
                self._live_frame_claim(onion, msg_id),
            )
            self._state.touch_session_activity(onion)
        except Exception:
            pass

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> FrameAdmission:
        """Persists one incoming live message before acknowledging the peer.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            FrameAdmission: Accepted, malformed, or resource-limited outcome.
        """
        try:
            msg_id, content, timestamp = decode_live_payload(payload_id, b64_payload)
        except ValueError as exc:
            self._hm.log_event(
                HistoryEvent.STREAM_CORRUPTED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=str(exc),
            )
            return FrameAdmission.MALFORMED

        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        if self._mm.has_inbound_message(onion, msg_id):
            if not self._mm.has_inbound_text_receipt(onion, msg_id):
                return FrameAdmission.MALFORMED
            self._acknowledge(conn, msg_id)
            return FrameAdmission.ACCEPTED

        has_clients: bool = self._has_clients_callback()
        has_live_consumers: bool = self._has_live_consumers_callback()
        unread_live_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
        if unread_live_limit == 0:
            if not has_live_consumers:
                return FrameAdmission.RESOURCE_LIMIT
        elif (
            unread_live_limit > 0
            and self._mm.get_unread_live_count(onion) >= unread_live_limit
        ):
            return FrameAdmission.RESOURCE_LIMIT

        queue_result = self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.IN,
            delivery=Delivery.LIVE,
            content_type=ContentType.TEXT,
            payload=content,
            status=MessageStatus.UNREAD,
            msg_id=msg_id,
            timestamp=timestamp or None,
        )
        self._acknowledge(conn, msg_id)
        if queue_result.was_duplicate:
            return FrameAdmission.ACCEPTED

        if alias:
            if has_clients and has_live_consumers:
                self._broadcast(
                    MessageReceivedEvent(
                        alias=alias,
                        onion=onion,
                        delivery=Delivery.LIVE,
                        content=TextContent(content),
                        timestamp=timestamp,
                        msg_id=msg_id,
                    )
                )
            elif has_clients:
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
        return FrameAdmission.ACCEPTED

    def _acknowledge(self, conn: socket.socket, msg_id: str) -> None:
        """Sends one best-effort transport acknowledgement.

        Args:
            conn (socket.socket): The active authenticated socket.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        try:
            self._state.send_frame(
                conn, f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
            )
        except Exception:
            pass

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """Finalizes a delivered outbound LIVE text message.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        timestamp = self._mm.mark_live_text_delivered(onion, msg_id)
        if timestamp is None:
            return
        self._state.invalidate_live_generations(onion, [msg_id])
        self._state.remove_unacked_message(onion, msg_id)
        self._broadcast(
            AckEvent(
                msg_id=msg_id,
                timestamp=timestamp,
                request_id=self._state.pop_message_request_id(msg_id),
            )
        )

    def process_incoming_drop_ack(self, onion: str, msg_id: str) -> None:
        """Finalizes only one pending session-routed DROP text message.

        Args:
            onion (str): Peer onion identity.
            msg_id (str): Stable logical identity.

        Returns:
            None
        """
        timestamp = self._mm.mark_drop_delivered(onion, msg_id)
        if timestamp is None:
            return
        self._hm.log_event(
            HistoryEvent.SENT, onion, actor=HistoryActor.LOCAL, transport='session'
        )
        self._broadcast(
            AckEvent(
                msg_id=msg_id,
                timestamp=timestamp,
                request_id=self._state.pop_message_request_id(msg_id),
            )
        )

    def process_incoming_read_receipt(self, onion: str, msg_id: str) -> None:
        """Broadcasts one transient read receipt from the peer.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The consumed message identifier.

        Returns:
            None
        """
        self._broadcast(
            ReadReceiptEvent(
                alias=cast(str, self._cm.ensure_alias_for_onion(onion)),
                msg_id=msg_id,
                onion=onion,
            )
        )
