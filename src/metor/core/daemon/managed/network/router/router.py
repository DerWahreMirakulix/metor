"""Thin composition root for application-layer message routing."""

import socket
import threading
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

from metor.core.api import (
    Delivery,
    EventType,
    IpcEvent,
    JsonValue,
    MessageOperationReason,
    VoiceContent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data.blob import BlobStore
from metor.data import (
    ContactManager,
    HistoryActor,
    HistoryManager,
    HistoryReasonCode,
    MessageManager,
    MessageDirection,
)

# Local Package Imports
from ...notify import NotificationPayload
from ..state import StateTracker
from ..stream import TcpStreamReader
from .drop import DropMessageRouter
from .fallback import FallbackRouter
from .live import LiveMessageRouter
from .admission import FrameAdmission
from ..voice import VoiceTransferManager

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
        blob_store: Optional[BlobStore] = None,
        purge_fence: Optional[threading.Event] = None,
        operation_lock: Optional[threading.RLock] = None,
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
            blob_store (Optional[BlobStore]): Active profile external object store.
            purge_fence (Optional[threading.Event]): Destructive lifecycle fence.
            operation_lock (Optional[threading.RLock]): State publication barrier.

        Returns:
            None
        """
        self._purge_fence = purge_fence or threading.Event()
        self._operation_lock = operation_lock or threading.RLock()
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
            transition_lock=self._operation_lock,
            purge_fence=self._purge_fence,
        )
        transition_lock = self._operation_lock
        self._voice: Optional[VoiceTransferManager] = (
            VoiceTransferManager(
                contacts=cm,
                messages=mm,
                blobs=blob_store,
                state=state,
                broadcast=broadcast_callback,
                config=config,
                has_clients_callback=has_clients_callback,
                has_live_consumers_callback=has_live_consumers_callback,
                notify_callback=notify_callback,
                transition_lock=transition_lock,
                purge_fence=self._purge_fence,
            )
            if blob_store is not None
            else None
        )
        self._fallback: FallbackRouter = FallbackRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            state=state,
            broadcast_callback=broadcast_callback,
            config=config,
            transition_lock=transition_lock,
            promote_voice_callback=(
                self._voice.promote_fallback if self._voice is not None else None
            ),
            purge_fence=self._purge_fence,
        )
        self._drop: DropMessageRouter = DropMessageRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            notify_callback=notify_callback,
            config=config,
            state=state,
            voice_frame_callback=self.process_drop_voice_frame,
            transition_lock=transition_lock,
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
        if not self._purge_fence.is_set():
            with self._operation_lock:
                self._live.send_message(target, msg, msg_id)

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> FrameAdmission:
        """Delegates inbound live-message acceptance to the live router.

        Args:
            conn (socket.socket): The active session socket.
            onion (str): The peer onion identity.
            payload_id (str): The transport fallback message identifier.
            b64_payload (str): The Base64-encoded message envelope.

        Returns:
            FrameAdmission: Typed acceptance or termination outcome.
        """
        if self._purge_fence.is_set():
            return FrameAdmission.PURGING
        with self._operation_lock:
            return self._live.process_incoming_msg(conn, onion, payload_id, b64_payload)

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """Delegates incoming acknowledgement handling to the live router.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The acknowledged message identifier.

        Returns:
            None
        """
        if not self._purge_fence.is_set():
            with self._operation_lock:
                self._live.process_incoming_ack(onion, msg_id)

    def process_voice_commit_ack(self, onion: str, msg_id: str) -> None:
        """Finalizes one outbound Voice item after durable peer completion.

        Args:
            onion (str): Authenticated peer identity.
            msg_id (str): Stable Voice message identity.

        Returns:
            None
        """
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.acknowledge_complete(onion, msg_id)

    def process_incoming_drop_ack(self, onion: str, msg_id: str) -> None:
        """Finalizes a session-routed DROP text acknowledgement.

        Args:
            onion (str): Authenticated peer identity.
            msg_id (str): Stable DROP message identity.

        Returns:
            None
        """
        if not self._purge_fence.is_set():
            with self._operation_lock:
                self._live.process_incoming_drop_ack(onion, msg_id)

    def begin_voice(
        self, target: str, delivery: Delivery, msg_id: str, codec: str
    ) -> None:
        """Begins one logical Voice turn when blob storage is available.

        Args:
            target (str): Peer alias or onion.
            delivery (Delivery): Requested semantics.
            msg_id (str): Stable identity.
            codec (str): Codec identifier.

        Returns:
            None
        """
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.begin(target, delivery, msg_id, codec)

    def append_voice(self, msg_id: str, offset: int, data: str) -> None:
        """Appends one bounded local Voice chunk.

        Args:
            msg_id (str): Stable identity.
            offset (int): Exact byte offset.
            data (str): Base64 chunk.

        Returns:
            None
        """
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.append(msg_id, offset, data)

    def finalize_voice(self, msg_id: str, duration_ms: Optional[int]) -> None:
        """Finalizes one logical local Voice turn.

        Args:
            msg_id (str): Stable identity.
            duration_ms (Optional[int]): Optional duration metadata.

        Returns:
            None
        """
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.finalize(msg_id, duration_ms)

    def release_consumed_voice(self, onion: str, msg_ids: list[str]) -> None:
        """Releases consumed inbound LIVE Voice retention."""
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.release_consumed(onion, msg_ids)

    def voice_target(self, msg_id: str) -> Optional[str]:
        """Returns the peer identity permanently bound to one outbound turn."""
        return self._voice.outbound_target(msg_id) if self._voice is not None else None

    def voice_delivery(self, msg_id: str) -> Optional[Delivery]:
        """Returns delivery semantics permanently bound to one outbound turn."""
        return (
            self._voice.outbound_delivery(msg_id) if self._voice is not None else None
        )

    def read_voice_chunk(
        self,
        onion: str,
        msg_id: str,
        direction: MessageDirection,
        offset: int,
        max_bytes: int,
    ) -> tuple[
        Optional[VoiceContent],
        Optional[Delivery],
        Optional[bytes],
        int,
        bool,
        Optional[MessageOperationReason],
    ]:
        """Reads one bounded Voice range through the router boundary."""
        if self._purge_fence.is_set():
            return (
                None,
                None,
                None,
                offset,
                False,
                MessageOperationReason.NOT_FOUND,
            )
        if self._voice is None:
            return (
                None,
                None,
                None,
                offset,
                False,
                MessageOperationReason.UNSUPPORTED_CONTENT,
            )
        return self._voice.read_chunk(onion, msg_id, direction, offset, max_bytes)

    def release_inbound_voice_item(self, onion: str, msg_id: str) -> bool:
        """Consumes one finalized inbound Voice item after client handoff."""
        if self._voice is None or self._purge_fence.is_set():
            return False
        with self._operation_lock:
            return self._voice.release_inbound(onion, msg_id)

    def commit_voice_draft(self, target: str, msg_id: str) -> bool:
        """Publishes one finalized DROP Voice draft."""
        return (
            self._voice.commit_draft(target, msg_id)
            if self._voice is not None and not self._purge_fence.is_set()
            else False
        )

    def cancel_voice_draft(self, target: str, msg_id: str) -> bool:
        """Cancels one unsent DROP Voice draft."""
        return (
            self._voice.cancel_draft(target, msg_id)
            if self._voice is not None and not self._purge_fence.is_set()
            else False
        )

    def dismiss_inbound_voice(self, onion: str) -> None:
        """Releases all inbound Voice retention for a dismissed LIVE context."""
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.dismiss_inbound(onion)

    def process_voice_frame(
        self, conn: socket.socket, onion: str, command: str, encoded: str
    ) -> FrameAdmission:
        """Processes one authenticated Voice application frame.

        Args:
            conn (socket.socket): Active peer socket.
            onion (str): Authenticated peer identity.
            command (str): Voice wire command.
            encoded (str): Base64 JSON envelope.

        Returns:
            FrameAdmission: Typed acceptance or termination outcome.
        """
        if self._purge_fence.is_set():
            return FrameAdmission.PURGING
        if self._voice is None:
            return FrameAdmission.MALFORMED
        payload = self._voice.decode_wire_payload(encoded)
        if payload is None:
            return FrameAdmission.MALFORMED
        if command == TorCommand.VOICE_BEGIN.value:
            return self._voice.receive_begin(conn, onion, payload)
        if command == TorCommand.VOICE_CHUNK.value:
            return self._voice.receive_chunk(conn, onion, payload)
        if command == TorCommand.VOICE_END.value:
            return self._voice.receive_end(conn, onion, payload)
        return FrameAdmission.MALFORMED

    def process_drop_voice_frame(
        self, conn: socket.socket, onion: str, command: str, encoded: str
    ) -> FrameAdmission:
        """Processes one typed Voice frame carrying DROP semantics."""
        if self._voice is None:
            return FrameAdmission.MALFORMED
        if not self._drop.allows_inbound_drops():
            self._drop.reject_disabled_drop(conn)
            return FrameAdmission.POLICY_REJECTED
        payload = self._voice.decode_wire_payload(encoded)
        if payload is None:
            return FrameAdmission.MALFORMED
        if command == TorCommand.DROP_VOICE_BEGIN.value:
            return self._voice.receive_begin(
                conn, onion, payload, delivery=Delivery.DROP
            )
        if command == TorCommand.DROP_VOICE_CHUNK.value:
            return self._voice.receive_chunk(conn, onion, payload)
        if command == TorCommand.DROP_VOICE_END.value:
            return self._voice.receive_end(conn, onion, payload)
        return FrameAdmission.MALFORMED

    def process_voice_ack(self, onion: str, msg_id: str, next_offset: int) -> None:
        """Delegates one monotonic Voice resume acknowledgement.

        Args:
            onion (str): Peer identity.
            msg_id (str): Stable Voice identity.
            next_offset (int): Confirmed contiguous byte offset.

        Returns:
            None
        """
        if self._voice is not None and not self._purge_fence.is_set():
            self._voice.acknowledge(onion, msg_id, next_offset)

    def process_incoming_read_receipt(self, onion: str, msg_id: str) -> None:
        """Delegates incoming read-receipt handling to the live router.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The consumed message identifier.

        Returns:
            None
        """
        if not self._purge_fence.is_set():
            with self._operation_lock:
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
        if not self._purge_fence.is_set():
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
        if not self._purge_fence.is_set():
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
        if self._purge_fence.is_set():
            return {}
        converted = self._fallback.convert_unacked_messages_to_drop(
            alias,
            onion,
            request_id=request_id,
            emit_event=emit_event,
            history_actor=history_actor,
            history_reason_code=history_reason_code,
        )
        return converted

    def replay_unacked_messages(self, onion: str) -> list[str]:
        """Delegates pending live replay to the fallback router.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[str]: The message IDs replayed successfully.
        """
        if self._purge_fence.is_set():
            return []
        replayed = self._fallback.replay_unacked_messages(onion)
        if self._voice is not None:
            replayed.extend(self._voice.replay(onion))
        return replayed

    def force_fallback(
        self, target: str, msg_ids: Optional[list[str]] = None
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """Delegates explicit live-to-drop fallback to the fallback router.

        Args:
            target (str): The target alias or onion address.
            msg_ids (Optional[list[str]]): Selected logical IDs, or all.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: The operation result.
        """
        result = self._fallback.force_fallback(target, msg_ids)
        return result

    def finalize_pending_live_messages(self) -> None:
        """Delegates shutdown fallback finalization to the fallback router.

        Args:
            None

        Returns:
            None
        """
        if not self._purge_fence.is_set():
            self._fallback.finalize_pending_live_messages()
