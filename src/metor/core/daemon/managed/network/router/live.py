"""Live-message routing, durable acceptance, and acknowledgement handling."""

# mypy: disable-error-code=attr-defined

import socket
from datetime import datetime, timezone
from typing import Optional, Tuple, cast

from metor.core.api import (
    AckEvent,
    ContentType,
    Delivery,
    InboxNotificationEvent,
    MessageReceivedEvent,
    ReadReceiptEvent,
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
    SettingKey,
)

# Local Package Imports
from .codec import build_message_frame, decode_live_payload


class LiveMessageRouting:
    """Owns outbound live delivery and crash-safe inbound live acceptance."""

    def _should_defer_live_message(self, onion: str) -> bool:
        """Checks whether one outbound live message should stay recoverable.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if live recovery is still plausible.
        """
        has_live_reconnect_grace = getattr(
            self._state, 'has_live_reconnect_grace', None
        )
        is_retunneling = getattr(self._state, 'is_retunneling', None)
        has_outbound_attempt = getattr(self._state, 'has_outbound_attempt', None)
        has_scheduled_auto_reconnect = getattr(
            self._state, 'has_scheduled_auto_reconnect', None
        )
        is_connected_or_pending = getattr(self._state, 'is_connected_or_pending', None)
        return (
            bool(callable(has_live_reconnect_grace) and has_live_reconnect_grace(onion))
            or bool(callable(is_retunneling) and is_retunneling(onion))
            or bool(callable(has_outbound_attempt) and has_outbound_attempt(onion))
            or bool(
                callable(has_scheduled_auto_reconnect)
                and has_scheduled_auto_reconnect(onion)
            )
            or bool(
                callable(is_connected_or_pending) and is_connected_or_pending(onion)
            )
        )

    def _queue_pending_live_message(
        self, onion: str, msg: str, msg_id: str, timestamp: str
    ) -> None:
        """Persists one outbound live message until ACK or terminal fallback.

        Args:
            onion (str): The peer onion identity.
            msg (str): The message payload.
            msg_id (str): The stable logical message identifier.
            timestamp (str): The authored timestamp.

        Returns:
            None
        """
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            delivery=Delivery.LIVE,
            content_type=ContentType.TEXT,
            payload=msg,
            status=MessageStatus.PENDING,
            msg_id=msg_id,
            timestamp=timestamp,
        )
        self._state.add_unacked_message(onion, msg_id, msg, timestamp)

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
        self._remember_message_request_id(msg_id, request_id)
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        timestamp: str = datetime.now(timezone.utc).isoformat()

        if conn is None:
            if self._should_defer_live_message(onion) or not self._config.get_bool(
                SettingKey.FALLBACK_TO_DROP
            ):
                self._queue_pending_live_message(onion, msg, msg_id, timestamp)
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
                self._auto_fallback_event(
                    alias=alias,
                    onion=onion,
                    msg_id=msg_id,
                    request_id=request_id,
                )
            )
            return

        try:
            self._queue_pending_live_message(onion, msg, msg_id, timestamp)
            conn.sendall(
                build_message_frame(TorCommand.MSG, msg_id, msg, timestamp).encode(
                    'utf-8'
                )
            )
            touch_activity = getattr(self._state, 'touch_session_activity', None)
            if callable(touch_activity):
                touch_activity(onion)
        except Exception:
            pass

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> bool:
        """Persists one incoming live message before acknowledging the peer.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            bool: True when the session must close for backlog pressure.
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
            return True

        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        if self._mm.has_inbound_message(onion, msg_id):
            self._acknowledge(conn, msg_id)
            return False

        has_clients: bool = self._has_clients_callback()
        has_live_consumers: bool = self._has_live_consumers_callback()
        unread_live_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
        if unread_live_limit == 0:
            if not has_live_consumers:
                return True
        elif self._mm.get_unread_live_count(onion) >= unread_live_limit:
            return True

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
            return False

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
                self._notify_inbox(alias, onion)
        return False

    @staticmethod
    def _acknowledge(conn: socket.socket, msg_id: str) -> None:
        """Sends one best-effort transport acknowledgement.

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

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """Finalizes a delivered outbound live or session-routed drop message.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        drop_timestamp: Optional[str] = self._mm.mark_drop_delivered(onion, msg_id)
        if drop_timestamp is not None:
            self._hm.log_event(
                HistoryEvent.SENT, onion, actor=HistoryActor.LOCAL, transport='session'
            )
            self._broadcast(
                AckEvent(
                    msg_id=msg_id,
                    timestamp=drop_timestamp,
                    request_id=self._pop_message_request_id(msg_id),
                )
            )
            return

        acked_msg: Optional[Tuple[str, str]] = self._state.remove_unacked_message(
            onion, msg_id
        )
        self._mm.update_outbound_message_status(onion, msg_id, MessageStatus.DELIVERED)
        self._broadcast(
            AckEvent(
                msg_id=msg_id,
                timestamp=acked_msg[1] if acked_msg else None,
                request_id=self._pop_message_request_id(msg_id),
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
