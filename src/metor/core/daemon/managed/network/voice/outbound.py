"""Outbound Voice replay, fallback, acknowledgement, and release."""

from __future__ import annotations

import base64
import json
import socket
import threading
from typing import Callable, Optional, TYPE_CHECKING

from metor.core.api import (
    Delivery,
    IpcEvent,
    MessageOperationReason,
    VoiceContent,
    VoiceOperationRejectedEvent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    MessageDirection,
    MessageStatus,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants
from metor.core.daemon.managed.network.state import StateTracker

from .models import VoiceTurn

if TYPE_CHECKING:
    from metor.data import ContactManager, MessageManager
    from metor.data.profile import Config


class VoiceOutboundMixin:
    """Owns outbound replay, fallback, acknowledgement, and release behavior."""

    _contacts: 'ContactManager'
    _messages: 'MessageManager'
    _blobs: BlobStore
    _state: StateTracker
    _broadcast: Callable[[IpcEvent], None]
    _config: 'Config'
    _lock: threading.RLock
    _purge_fence: threading.Event
    _outbound: dict[str, VoiceTurn]
    _inbound: dict[tuple[str, str], VoiceTurn]

    if TYPE_CHECKING:

        def _delete_turn_blobs(self, turn: VoiceTurn, lifecycle: BlobLifecycle) -> None:
            """Deletes every object owned by one Voice turn.

            Args:
                turn: Voice turn whose objects are removed.
                lifecycle: Expected object lifecycle.
            Returns:
                None
            """
            ...

        @staticmethod
        def _metadata(turn: VoiceTurn) -> str:
            """Serializes canonical metadata for one Voice turn.

            Args:
                turn: Voice turn to describe.
            Returns:
                str: Canonical metadata JSON.
            """
            ...

        @staticmethod
        def _metadata_blob_ids(payload: str) -> Optional[tuple[str, ...]]:
            """Extracts a complete object inventory from canonical metadata.

            Args:
                payload: Stored canonical metadata.
            Returns:
                Optional[tuple[str, ...]]: Object IDs when the inventory is valid.
            """
            ...

        @staticmethod
        def _metadata_finalized(payload: str) -> bool:
            """Checks whether canonical metadata records finalization.

            Args:
                payload: Stored canonical metadata.
            Returns:
                bool: Whether the turn is finalized.
            """
            ...

        def _read_turn_range(
            self,
            turn: VoiceTurn,
            offset: int,
            max_bytes: int,
            lifecycle: BlobLifecycle = BlobLifecycle.TEMPORARY,
        ) -> bytes:
            """Reads one bounded contiguous range from segmented Voice objects.

            Args:
                turn: Voice turn owning the objects.
                offset: First byte to read.
                max_bytes: Maximum number of bytes to return.
                lifecycle: Expected object lifecycle.
            Returns:
                bytes: Available contiguous payload bytes.
            """
            ...

        def _send_begin(self, turn: VoiceTurn) -> None:
            """Emits an authorized live Voice begin frame.

            Args:
                turn: Outbound live Voice turn.
            Returns:
                None
            """
            ...

        def _send_outbound_frame(
            self, turn: VoiceTurn, conn: socket.socket, payload: bytes
        ) -> None:
            """Queues one frame under its final emission claim.

            Args:
                turn: Outbound live Voice turn.
                conn: Authenticated peer socket.
                payload: Encoded frame bytes.
            Returns:
                None
            """
            ...

        @staticmethod
        def _wire(command: TorCommand, payload: dict[str, object]) -> bytes:
            """Encodes one bounded Voice transport frame.

            Args:
                command: Voice transport command.
                payload: Validated frame payload.
            Returns:
                bytes: Encoded wire frame.
            """
            ...

    def replay(self, onion: str) -> list[str]:
        """Resumes retained Voice turns after their acknowledged byte offset.

        Args:
            onion (str): Recovered peer identity.

        Returns:
            list[str]: Logical Voice IDs resumed.
        """
        if self._purge_fence.is_set():
            return []
        turns: list[VoiceTurn] = []
        with self._lock:
            for turn in self._outbound.values():
                if turn.onion != onion or turn.delivery is not Delivery.LIVE:
                    continue
                if self._state.get_live_generation(onion, turn.msg_id) is not None:
                    turns.append(turn)
            for turn in turns:
                self._send_begin(turn)
        return [turn.msg_id for turn in turns]

    def promote_fallback(self, msg_ids: list[str], peer: str | None = None) -> None:
        """Releases LIVE Voice budget after message-level fallback commits.

        Args:
            msg_ids (list[str]): Successfully promoted logical identities.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            selected_ids = set(msg_ids)
            if not selected_ids:
                return
            for (
                _,
                onion,
                content_type,
                payload,
                msg_id,
                _,
            ) in self._messages.get_pending_outbox():
                if (
                    msg_id not in selected_ids
                    or content_type != 'voice'
                    or (peer is not None and onion != peer)
                ):
                    continue
                metadata = json.loads(payload)
                if (
                    not isinstance(metadata, dict)
                    or metadata.get('fallback_committed') is not True
                ):
                    continue
                if self._state.get_live_generation(onion, msg_id) is not None:
                    continue
                blob_ids = self._metadata_blob_ids(payload)
                if blob_ids is None:
                    raise ValueError('Committed fallback metadata is invalid.')
                turn = self._outbound.get(msg_id)
                if turn is not None and turn.onion == onion:
                    turn.delivery = Delivery.DROP
                    turn.fallback_committed = True
                for blob_id in blob_ids:
                    if not self._blobs.exists(blob_id, BlobLifecycle.PERSISTENT):
                        self._blobs.promote(blob_id)
                if turn is not None and turn.onion == onion:
                    self._outbound.pop(msg_id, None)

    def acknowledge(self, onion: str, msg_id: str, next_offset: int) -> None:
        """Advances an outbound Voice resume cursor monotonically.

        Args:
            onion (str): Peer onion identity.
            msg_id (str): Stable Voice identity.
            next_offset (int): Peer-confirmed contiguous byte offset.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        frame: Optional[tuple[socket.socket, bytes]] = None
        with self._lock:
            if self._purge_fence.is_set():
                return
            turn = self._outbound.get(msg_id)
            if turn is None or turn.onion != onion:
                return
            if next_offset < turn.acknowledged_offset or next_offset > turn.size_bytes:
                return
            previous_offset = turn.acknowledged_offset
            turn.acknowledged_offset = next_offset
            try:
                updated = self._messages.update_retained_bytes(
                    onion, msg_id, turn.size_bytes, self._metadata(turn)
                )
            except Exception:
                updated = False
            if not updated:
                turn.acknowledged_offset = previous_offset
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            if next_offset < turn.size_bytes:
                chunk = self._read_turn_range(
                    turn,
                    next_offset,
                    Constants.VOICE_CHUNK_MAX_BYTES,
                )
                conn = self._state.get_connection(onion)
                if conn is not None:
                    frame = (
                        conn,
                        self._wire(
                            TorCommand.VOICE_CHUNK,
                            {
                                'id': turn.msg_id,
                                'offset': next_offset,
                                'data': base64.b64encode(chunk).decode('ascii'),
                            },
                        ),
                    )
            elif turn.finalized:
                conn = self._state.get_connection(onion)
                if conn is not None:
                    frame = (
                        conn,
                        self._wire(
                            TorCommand.VOICE_END,
                            {
                                'id': turn.msg_id,
                                'size': turn.size_bytes,
                                'duration_ms': turn.duration_ms,
                            },
                        ),
                    )
        if frame is not None:
            try:
                assert turn is not None
                self._send_outbound_frame(turn, *frame)
            except OSError:
                pass

    def acknowledge_complete(self, onion: str, msg_id: str) -> None:
        """Releases retained LIVE Voice after a terminal logical-message ACK.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            turn = self._outbound.get(msg_id)
            if (
                turn is None
                or turn.onion != onion
                or turn.delivery is not Delivery.LIVE
                or not turn.finalized
            ):
                return
            try:
                completed = self._messages.update_outbound_message_status(
                    onion, msg_id, MessageStatus.DELIVERED
                )
            except Exception:
                completed = False
            if not completed:
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            self._state.remove_unacked_message(onion, msg_id)
            self._state.invalidate_live_generations(onion, [msg_id])
            try:
                self._delete_turn_blobs(turn, BlobLifecycle.TEMPORARY)
            except Exception:
                pass
            self._outbound.pop(msg_id, None)

    def release_consumed(self, onion: str, msg_ids: list[str]) -> None:
        """Releases Core-owned inbound LIVE Voice payloads after explicit consume.

        Args:
            onion (str): The onion input.
            msg_ids (list[str]): The msg ids input.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            for msg_id in msg_ids:
                turn = self._inbound.get((onion, msg_id))
                if (
                    turn is not None
                    and turn.delivery is Delivery.LIVE
                    and turn.finalized
                ):
                    self._inbound.pop((onion, msg_id), None)
                    self._delete_turn_blobs(turn, BlobLifecycle.TEMPORARY)

    def outbound_target(self, msg_id: str) -> Optional[str]:
        """Returns the immutable onion target bound at Voice begin.

        Args:
            msg_id (str): The msg id input.

        Returns:
            Optional[str]: The resulting value.
        """
        with self._lock:
            turn = self._outbound.get(msg_id)
            return turn.onion if turn is not None else None

    def outbound_delivery(self, msg_id: str) -> Optional[Delivery]:
        """Returns the immutable delivery semantics selected at Voice begin.

        Args:
            msg_id (str): The msg id input.

        Returns:
            Optional[Delivery]: The resulting value.
        """
        with self._lock:
            turn = self._outbound.get(msg_id)
            return turn.delivery if turn is not None else None

    def read_chunk(
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
        """Reads one bounded Voice range through the authenticated Core boundary.

        Args:
            onion (str): Exact peer onion identity.
            msg_id (str): Stable logical identity.
            direction (MessageDirection): Exact local direction.
            offset (int): Requested byte offset.
            max_bytes (int): Strict response byte ceiling.

        Returns:
            tuple: Content, delivery, bytes, next offset, completion, and error.
        """
        if self._purge_fence.is_set():
            return None, None, None, offset, False, MessageOperationReason.NOT_FOUND
        if offset < 0 or not 0 < max_bytes <= Constants.VOICE_CHUNK_MAX_BYTES:
            return None, None, None, offset, False, MessageOperationReason.INVALID_RANGE
        record = self._messages.get_voice_payload(onion, msg_id, direction)
        if record is None:
            return None, None, None, offset, False, MessageOperationReason.NOT_FOUND
        try:
            if len(record.payload.encode('utf-8')) > Constants.VOICE_METADATA_MAX_BYTES:
                raise ValueError
            metadata = json.loads(record.payload)
            if not isinstance(metadata, dict):
                raise ValueError
            blob_id = str(metadata['blob_id'])
            raw_chunk_ids = metadata['chunk_ids']
            if not isinstance(raw_chunk_ids, list) or any(
                not isinstance(chunk_id, str) for chunk_id in raw_chunk_ids
            ):
                raise ValueError
            chunk_ids = [str(chunk_id) for chunk_id in raw_chunk_ids]
            if len(chunk_ids) > Constants.VOICE_MAX_SEGMENTS:
                raise ValueError
            raw_chunk_sizes = metadata.get('chunk_sizes')
            chunk_sizes: Optional[list[int]] = None
            if isinstance(raw_chunk_sizes, list) and len(raw_chunk_sizes) == len(
                chunk_ids
            ):
                if any(type(size) is not int for size in raw_chunk_sizes):
                    raise ValueError
                candidate_sizes = list(raw_chunk_sizes)
                if all(
                    0 < size <= Constants.VOICE_CHUNK_MAX_BYTES
                    for size in candidate_sizes
                ):
                    chunk_sizes = candidate_sizes
            if chunk_sizes is None:
                raise ValueError
            codec = metadata['codec']
            size_bytes = metadata['size_bytes']
            if (
                not isinstance(codec, str)
                or not codec
                or len(codec) > Constants.VOICE_CODEC_MAX_CHARS
                or type(size_bytes) is not int
                or not 0 <= size_bytes <= Constants.VOICE_TURN_HARD_MAX_BYTES
                or sum(chunk_sizes) != size_bytes
            ):
                raise ValueError
            finalized = metadata.get('finalized') is True
            duration_raw = metadata.get('duration_ms')
            if duration_raw is not None and (
                type(duration_raw) is not int or duration_raw < 0
            ):
                raise ValueError
            duration_ms = duration_raw
            delivery = Delivery(record.delivery)
            lifecycle = (
                BlobLifecycle.PERSISTENT
                if delivery is Delivery.DROP and finalized
                else BlobLifecycle.TEMPORARY
            )
            if not self._blobs.exists(blob_id, lifecycle) or offset > size_bytes:
                raise ValueError
            remaining = max_bytes
            position = 0
            selected = bytearray()
            for index, chunk_id in enumerate(chunk_ids):
                expected_size = chunk_sizes[index] if chunk_sizes is not None else None
                if expected_size is not None and offset >= position + expected_size:
                    position += expected_size
                    continue
                chunk = self._blobs.read(chunk_id, lifecycle)
                if expected_size is not None and len(chunk) != expected_size:
                    raise ValueError
                chunk_end = position + len(chunk)
                if offset >= chunk_end:
                    position = chunk_end
                    continue
                start = max(0, offset - position)
                portion = chunk[start : start + remaining]
                selected.extend(portion)
                remaining -= len(portion)
                position = chunk_end
                if remaining == 0:
                    break
            next_offset = offset + len(selected)
            if next_offset > size_bytes:
                raise ValueError
            content = VoiceContent(
                blob_id=blob_id,
                codec=codec,
                size_bytes=size_bytes,
                duration_ms=duration_ms,
            )
            return (
                content,
                delivery,
                bytes(selected),
                next_offset,
                finalized and next_offset == size_bytes,
                None,
            )
        except (KeyError, OSError, TypeError, ValueError):
            return None, None, None, offset, False, MessageOperationReason.INVALID_RANGE

    def release_inbound(self, onion: str, msg_id: str) -> bool:
        """Consumes and releases one finalized inbound Voice item explicitly.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        if self._purge_fence.is_set():
            return False
        with self._lock:
            if self._purge_fence.is_set():
                return False
            record = self._messages.get_voice_payload(
                onion, msg_id, MessageDirection.IN
            )
            if record is None:
                return False
            released = self._messages.release_inbound_voice(onion, msg_id)
            if released is None:
                return False
            payload, delivery = released
            blob_ids = self._metadata_blob_ids(payload)
            if blob_ids is None:
                return False
            lifecycle = (
                BlobLifecycle.PERSISTENT
                if delivery is Delivery.DROP
                else BlobLifecycle.TEMPORARY
            )
            should_delete = delivery is Delivery.LIVE or self._config.get_bool(
                SettingKey.EPHEMERAL_MESSAGES
            )
            if should_delete:
                for blob_id in blob_ids:
                    try:
                        self._blobs.delete(blob_id, lifecycle)
                    except Exception:
                        pass
            self._inbound.pop((onion, msg_id), None)
        return True

    def commit_draft(self, target: str, msg_id: str) -> bool:
        """Queues one finalized DROP Voice draft only after explicit Send.

        Args:
            target (str): Expected peer alias or onion.
            msg_id (str): Stable draft identity.

        Returns:
            bool: True when the draft became pending delivery.
        """
        if self._purge_fence.is_set():
            return False
        with self._lock:
            if self._purge_fence.is_set():
                return False
            resolved = self._contacts.resolve_target(target)
            return resolved is not None and self._messages.commit_voice_draft(
                resolved[1], msg_id
            )

    def cancel_draft(self, target: str, msg_id: str) -> bool:
        """Cancels one unsent DROP Voice draft and releases all blob objects.

        Args:
            target (str): Expected peer alias or onion.
            msg_id (str): Stable draft identity.

        Returns:
            bool: True when an eligible draft was removed.
        """
        if self._purge_fence.is_set():
            return False
        with self._lock:
            if self._purge_fence.is_set():
                return False
            resolved = self._contacts.resolve_target(target)
            if resolved is None:
                return False
            onion = resolved[1]
            payload = self._messages.cancel_voice_draft(onion, msg_id)
            if payload is None:
                return False
            self._outbound.pop(msg_id, None)
        blob_ids = self._metadata_blob_ids(payload)
        if blob_ids is None:
            return False
        lifecycle = (
            BlobLifecycle.PERSISTENT
            if self._metadata_finalized(payload)
            else BlobLifecycle.TEMPORARY
        )
        for blob_id in blob_ids:
            self._blobs.delete(blob_id, lifecycle)
        return True
