"""Local-only Voice capture staging shared by DROP and LIVE messages."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import threading
from typing import Callable, TYPE_CHECKING

from metor.core.api import (
    ContentType,
    Delivery,
    IpcEvent,
    MessageDirectionCode,
    MessageOperationReason,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
    VoiceOperationRejectedEvent,
    VoiceResourceLimitEvent,
    VoiceResourcePressureEvent,
    VoiceStartedEvent,
    is_valid_message_id,
)
from metor.data import MessageDirection, MessageStatus
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants
from metor.core.daemon.managed.network.state import StateTracker

# Local Package Imports
from .models import VoiceTurn

if TYPE_CHECKING:
    from metor.data import ContactManager, MessageManager
    from metor.data.profile import Config


class VoiceCaptureMixin:
    """Owns protected local draft admission, append, and finalization."""

    _contacts: ContactManager
    _messages: MessageManager
    _blobs: BlobStore
    _state: StateTracker
    _broadcast: Callable[[IpcEvent], None]
    _config: Config
    _lock: threading.RLock
    _purge_fence: threading.Event
    _outbound: dict[str, VoiceTurn]
    _capture_allocator: Callable[[str, bytes], str] | None = None

    if TYPE_CHECKING:

        def _canonical_outbound_metadata(self, turn: VoiceTurn) -> bool | None:
            """Reconciles uncertain SQL writes against canonical metadata."""
            ...

        def _finalized_outbound_event(self, msg_id: str) -> VoiceFinalizedEvent | None:
            """Returns a safe canonical projection for a finalized identity."""
            ...

        def _limit(self) -> int:
            """Returns the profile's retained Voice byte budget."""
            ...

        @staticmethod
        def _metadata(turn: VoiceTurn) -> str:
            """Serializes the bounded local Voice metadata."""
            ...

        def _used_bytes(self) -> int:
            """Counts retained Voice data against the profile budget."""
            ...

    def set_capture_allocator(self, allocator: Callable[[str, bytes], str]) -> None:
        """Installs Core's durable pre-write ownership journal."""
        self._capture_allocator = allocator

    def _put_capture_blob(self, msg_id: str, payload: bytes) -> str:
        """Allocates a protected local object without peer transport access."""
        if self._capture_allocator is not None:
            return self._capture_allocator(msg_id, payload)
        return self._blobs.put(payload, BlobLifecycle.TEMPORARY)

    def begin(self, target: str, delivery: Delivery, msg_id: str, codec: str) -> None:
        """Creates a target-bound unsent draft; neither mode emits a peer frame.

        Args:
            target: Core-resolved contact alias or onion.
            delivery: Intended publication semantics, unchanged until explicit Send.
            msg_id: Stable caller-created recording identity.
            codec: Bounded codec identifier.
        Returns:
            None. Admission is reported through typed events.
        """
        if self._purge_fence.is_set():
            return
        resolved = self._contacts.resolve_target(target)
        if (
            resolved is None
            or not is_valid_message_id(msg_id)
            or not codec
            or len(codec) > Constants.VOICE_CODEC_MAX_CHARS
        ):
            return
        alias, onion = resolved
        with self._lock:
            if self._purge_fence.is_set():
                return
            if self._messages.has_outbound_identity(msg_id):
                self._reject(msg_id, onion, MessageOperationReason.STALE_CAPTURE)
                return
            used, limit = self._used_bytes(), self._limit()
            if msg_id in self._outbound or (limit >= 0 and used >= limit):
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id,
                        onion=onion,
                        delivery=delivery,
                        used_bytes=used,
                        limit_bytes=limit,
                    )
                )
                return
            blob_id: str | None = None
            try:
                blob_id = self._put_capture_blob(msg_id, b'')
                turn = VoiceTurn(
                    alias=alias,
                    onion=onion,
                    msg_id=msg_id,
                    delivery=delivery,
                    codec=codec,
                    blob_id=blob_id,
                    chunk_ids=[],
                    chunk_sizes=[],
                    data=bytearray(),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    context_generation=(
                        self._state.get_live_media_generation(onion)
                        if delivery is Delivery.LIVE
                        else None
                    ),
                )
                admitted = bool(
                    self._messages.queue_message(
                        contact_onion=onion,
                        direction=MessageDirection.OUT,
                        delivery=delivery,
                        content_type=ContentType.VOICE,
                        payload=self._metadata(turn),
                        status=MessageStatus.DRAFT,
                        msg_id=msg_id,
                        timestamp=turn.timestamp,
                    )
                )
            except Exception:
                canonical = (
                    self._canonical_outbound_metadata(turn)
                    if blob_id is not None
                    else False
                )
                admitted = canonical is True
                if canonical is False and blob_id is not None:
                    self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
            if not admitted:
                self._reject(msg_id, onion)
                return
            self._outbound[msg_id] = turn
        self._broadcast(
            VoiceStartedEvent(
                alias=alias, onion=onion, msg_id=msg_id, delivery=delivery
            )
        )

    def _reject(
        self,
        msg_id: str,
        onion: str | None = None,
        reason: MessageOperationReason = MessageOperationReason.PERSISTENCE_FAILED,
    ) -> None:
        """Reports a content-free local staging failure."""
        self._broadcast(
            VoiceOperationRejectedEvent(msg_id=msg_id, onion=onion, reason=reason)
        )

    def _resource_limit(self, turn: VoiceTurn, used: int, limit: int) -> None:
        """Stops at a retained prefix without publishing or converting the draft."""
        self._broadcast(
            VoiceResourceLimitEvent(
                msg_id=turn.msg_id,
                onion=turn.onion,
                delivery=turn.delivery,
                used_bytes=used,
                limit_bytes=limit,
                reason=MessageOperationReason.MEDIA_LIMIT,
            )
        )
        self._finalize_locked(turn, None)

    def append(self, msg_id: str, offset: int, encoded_data: str) -> None:
        """Durably appends an exact contiguous draft chunk solely to local storage."""
        if self._purge_fence.is_set():
            return
        try:
            chunk = base64.b64decode(encoded_data, validate=True)
        except (binascii.Error, ValueError):
            self._reject(msg_id, reason=MessageOperationReason.MALFORMED_CHUNK)
            return
        if not chunk or len(chunk) > Constants.VOICE_CHUNK_MAX_BYTES:
            self._reject(msg_id, reason=MessageOperationReason.MALFORMED_CHUNK)
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            turn = self._outbound.get(msg_id)
            if (
                turn is None
                or turn.finalized
                or turn.published
                or offset != turn.size_bytes
            ):
                self._reject(msg_id, reason=MessageOperationReason.STALE_CAPTURE)
                return
            used, limit = self._used_bytes(), self._limit()
            if len(turn.chunk_ids) >= Constants.VOICE_MAX_SEGMENTS or (
                limit >= 0 and used + len(chunk) > limit
            ):
                self._resource_limit(turn, used, limit)
                return
            try:
                chunk_id = self._put_capture_blob(msg_id, chunk)
            except Exception:
                self._reject(msg_id, turn.onion)
                return
            turn.chunk_ids.append(chunk_id)
            turn.chunk_sizes.append(len(chunk))
            turn.size_bytes += len(chunk)
            safe_to_delete = True
            try:
                updated = self._messages.update_retained_bytes(
                    turn.onion, msg_id, turn.size_bytes, self._metadata(turn)
                )
            except Exception:
                canonical = self._canonical_outbound_metadata(turn)
                updated = canonical is True
                safe_to_delete = canonical is False
                if canonical is None:
                    self._outbound.pop(msg_id, None)
            if not updated:
                turn.chunk_ids.pop()
                turn.chunk_sizes.pop()
                turn.size_bytes -= len(chunk)
                if safe_to_delete:
                    self._blobs.delete(chunk_id, BlobLifecycle.TEMPORARY)
                self._reject(msg_id, turn.onion)
                return
            self._broadcast(
                VoiceChunkAcceptedEvent(msg_id=msg_id, next_offset=turn.size_bytes)
            )
            used += len(chunk)
            if (
                limit > 0
                and not turn.pressure_emitted
                and (used * 100 >= limit * Constants.VOICE_PRESSURE_PERCENT)
            ):
                turn.pressure_emitted = True
                self._broadcast(
                    VoiceResourcePressureEvent(
                        msg_id=msg_id,
                        onion=turn.onion,
                        delivery=turn.delivery,
                        used_bytes=used,
                        limit_bytes=limit,
                    )
                )
            if limit >= 0 and used >= limit:
                self._resource_limit(turn, used, limit)

    def finalize(self, msg_id: str, duration_ms: int | None) -> None:
        """Freezes the local draft for review without emitting or granting Send."""
        if self._purge_fence.is_set():
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            turn = self._outbound.get(msg_id)
            if turn is not None and not turn.published and not turn.finalized:
                self._finalize_locked(turn, duration_ms)
            else:
                finalized = self._finalized_outbound_event(msg_id)
                if finalized is not None:
                    self._broadcast(finalized)

    def _finalize_locked(self, turn: VoiceTurn, duration_ms: int | None) -> None:
        """Persists local finalization, preserving uncertain commits for recovery."""
        previous = turn.duration_ms, turn.finalized
        turn.duration_ms, turn.finalized = duration_ms, True
        try:
            updated = self._messages.update_retained_bytes(
                turn.onion, turn.msg_id, turn.size_bytes, self._metadata(turn)
            )
        except Exception:
            canonical = self._canonical_outbound_metadata(turn)
            updated = canonical is True
            if canonical is None:
                self._outbound.pop(turn.msg_id, None)
        if not updated:
            turn.duration_ms, turn.finalized = previous
            self._reject(turn.msg_id, turn.onion)
            return
        self._broadcast(
            VoiceFinalizedEvent(
                msg_id=turn.msg_id,
                size_bytes=turn.size_bytes,
                onion=turn.onion,
                delivery=turn.delivery,
                direction=MessageDirectionCode.OUT,
                duration_ms=turn.duration_ms,
            )
        )
