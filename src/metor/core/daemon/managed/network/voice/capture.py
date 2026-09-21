"""Outbound Voice capture admission, persistence, and finalization."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import socket
import threading
from typing import Callable, Optional, TYPE_CHECKING

from metor.core.api import (
    ContentType,
    Delivery,
    FallbackSuccessEvent,
    IpcEvent,
    LiveMessageUnavailableEvent,
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
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    MessageDirection,
    MessageStatus,
    PendingLiveAdmission,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants
from metor.core.daemon.managed.network.state import StateTracker

from .models import VoiceTurn

if TYPE_CHECKING:
    from metor.data import ContactManager, MessageManager
    from metor.data.profile import Config


class VoiceCaptureMixin:
    """Owns outbound Voice capture admission, append, and finalization."""

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
    _capture_allocator: Optional[Callable[[str, bytes], str]] = None

    if TYPE_CHECKING:

        def _canonical_outbound_metadata(self, turn: VoiceTurn) -> bool | None: ...

        def _finalized_outbound_event(
            self, msg_id: str
        ) -> Optional[VoiceFinalizedEvent]: ...

        def _limit(self) -> int: ...

        @staticmethod
        def _metadata(turn: VoiceTurn) -> str: ...

        def _promote_turn_blobs(self, turn: VoiceTurn) -> None: ...

        def _used_bytes(self) -> int: ...

        @staticmethod
        def _wire(command: TorCommand, payload: dict[str, object]) -> bytes: ...

    def set_capture_allocator(self, allocator: Callable[[str, bytes], str]) -> None:
        """Installs the Core pre-write ownership hook before command admission.

        Args:
            allocator: Profile-bound allocator preserving legacy unowned behavior.
        Returns:
            None
        """
        self._capture_allocator = allocator

    def _put_capture_blob(self, msg_id: str, payload: bytes) -> str:
        """Allocates capture bytes through the installed ownership boundary.

        Args:
            msg_id: Exact recording identity.
            payload: Bounded anchor or encoded chunk bytes.
        Returns:
            str: Stored logical object ID.
        """
        if self._capture_allocator is not None:
            return self._capture_allocator(msg_id, payload)
        return self._blobs.put(payload, BlobLifecycle.TEMPORARY)

    def begin(self, target: str, delivery: Delivery, msg_id: str, codec: str) -> None:
        """Begins one outbound logical Voice turn.

        Args:
            target (str): Target alias or onion.
            delivery (Delivery): LIVE or DROP semantics.
            msg_id (str): Stable logical message identity.
            codec (str): Small codec identifier.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        resolved = self._contacts.resolve_target(target)
        if (
            not resolved
            or not is_valid_message_id(msg_id)
            or not codec
            or len(codec) > Constants.VOICE_CODEC_MAX_CHARS
        ):
            return
        alias, onion = resolved
        with self._lock:
            if self._purge_fence.is_set():
                return
            limit = self._limit()
            used = self._used_bytes()
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
            if (
                delivery is Delivery.LIVE
                and self._state.get_connection(onion) is None
                and not self._is_recovery_plausible(onion)
                and not self._config.get_bool(SettingKey.FALLBACK_TO_DROP)
            ):
                self._broadcast(
                    LiveMessageUnavailableEvent(alias=alias, onion=onion, msg_id=msg_id)
                )
                return
            persistence_failed = False
            try:
                blob_id = self._put_capture_blob(msg_id, b'')
            except Exception:
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            turn = VoiceTurn(
                context_generation=self._state.get_live_media_generation(onion),
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
            )
            try:
                if delivery is Delivery.LIVE:
                    admission = self._messages.queue_pending_live_if_capacity(
                        onion,
                        ContentType.VOICE,
                        self._metadata(turn),
                        msg_id,
                        turn.timestamp,
                        0,
                        self._config.get_int(SettingKey.MAX_PENDING_LIVE_MSGS),
                        self._config.get_int(SettingKey.MAX_PENDING_LIVE_BYTES),
                    )
                else:
                    admission = (
                        PendingLiveAdmission.ACCEPTED
                        if self._messages.queue_message(
                            contact_onion=onion,
                            direction=MessageDirection.OUT,
                            delivery=delivery,
                            content_type=ContentType.VOICE,
                            payload=self._metadata(turn),
                            status=MessageStatus.DRAFT,
                            msg_id=msg_id,
                            timestamp=turn.timestamp,
                        )
                        else PendingLiveAdmission.DUPLICATE
                    )
            except Exception:
                canonical = self._canonical_outbound_metadata(turn)
                persistence_failed = canonical is not True
                admission = (
                    PendingLiveAdmission.ACCEPTED
                    if canonical is True
                    else PendingLiveAdmission.DUPLICATE
                )
            if persistence_failed:
                if canonical is False:
                    try:
                        self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
                    except Exception:
                        pass
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            if delivery is Delivery.LIVE:
                if admission is not PendingLiveAdmission.ACCEPTED:
                    try:
                        self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
                    except Exception:
                        pass
                    reason = (
                        MessageOperationReason.COUNT_LIMIT
                        if admission is PendingLiveAdmission.COUNT_LIMIT
                        else MessageOperationReason.BYTE_LIMIT
                    )
                    self._broadcast(
                        VoiceResourceLimitEvent(
                            msg_id=msg_id,
                            onion=onion,
                            delivery=delivery,
                            used_bytes=used,
                            limit_bytes=(
                                self._config.get_int(SettingKey.MAX_PENDING_LIVE_MSGS)
                                if reason is MessageOperationReason.COUNT_LIMIT
                                else self._config.get_int(
                                    SettingKey.MAX_PENDING_LIVE_BYTES
                                )
                            ),
                            reason=reason,
                        )
                    )
                    return
            elif admission is not PendingLiveAdmission.ACCEPTED:
                try:
                    self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
                except Exception:
                    pass
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            self._outbound[msg_id] = turn
            if delivery is Delivery.LIVE:
                self._state.add_unacked_message(
                    onion, msg_id, self._metadata(turn), turn.timestamp
                )
        self._send_begin(turn)
        self._broadcast(
            VoiceStartedEvent(
                alias=alias, onion=onion, msg_id=msg_id, delivery=delivery
            )
        )

    def _is_recovery_plausible(self, onion: str) -> bool:
        """Checks genuine shared LIVE recovery state.

        Args:
            onion (str): Peer onion identity.

        Returns:
            bool: True when recovery is active or scheduled.
        """
        return bool(
            self._state.has_live_reconnect_grace(onion)
            or self._state.is_retunneling(onion)
            or self._state.has_outbound_attempt(onion)
            or self._state.has_scheduled_auto_reconnect(onion)
            or self._state.is_connected_or_pending(onion)
        )

    def _send_begin(self, turn: VoiceTurn) -> None:
        """Sends or resumes one Voice begin envelope when LIVE is available.

        Args:
            turn (VoiceTurn): Outbound Voice turn.

        Returns:
            None
        """
        conn = self._state.get_connection(turn.onion)
        if conn is None or turn.delivery is not Delivery.LIVE:
            return
        try:
            self._send_outbound_frame(
                turn,
                conn,
                self._wire(
                    TorCommand.VOICE_BEGIN,
                    {
                        'id': turn.msg_id,
                        'codec': turn.codec,
                        'offset': turn.acknowledged_offset,
                        'timestamp': turn.timestamp,
                    },
                ),
            )
        except OSError:
            return

    def _send_outbound_frame(
        self, turn: VoiceTurn, conn: socket.socket, payload: bytes
    ) -> None:
        """Queues one LIVE frame with a fallback/purge generation claim."""
        generation = self._state.get_live_generation(turn.onion, turn.msg_id)
        if generation is None:
            raise ConnectionError('LIVE emission authority has been revoked.')

        def claim() -> bool:
            with self._lock:
                return (
                    not self._purge_fence.is_set()
                    and turn.delivery is Delivery.LIVE
                    and self._state.is_live_generation(
                        turn.onion, turn.msg_id, generation
                    )
                )

        self._state.send_frame(conn, payload, claim)

    def append(self, msg_id: str, offset: int, encoded_data: str) -> None:
        """Appends and durably retains one exact-offset Voice chunk.

        Args:
            msg_id (str): Stable Voice identity.
            offset (int): Expected current byte length.
            encoded_data (str): Strict Base64 chunk.

        Returns:
            None
        """
        if self._purge_fence.is_set():
            return
        try:
            chunk = base64.b64decode(encoded_data, validate=True)
        except (binascii.Error, ValueError):
            self._broadcast(
                VoiceOperationRejectedEvent(
                    msg_id=msg_id,
                    reason=MessageOperationReason.MALFORMED_CHUNK,
                )
            )
            return
        if not chunk or len(chunk) > Constants.VOICE_CHUNK_MAX_BYTES:
            self._broadcast(
                VoiceOperationRejectedEvent(
                    msg_id=msg_id,
                    reason=MessageOperationReason.MALFORMED_CHUNK,
                )
            )
            return
        should_finalize = False
        accepted_turn: Optional[VoiceTurn] = None
        with self._lock:
            if self._purge_fence.is_set():
                return
            turn = self._outbound.get(msg_id)
            if turn is None or turn.finalized or offset != turn.size_bytes:
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        reason=MessageOperationReason.STALE_CAPTURE,
                    )
                )
                return
            limit = self._limit()
            used = self._used_bytes()
            if (
                len(turn.chunk_ids) >= Constants.VOICE_MAX_SEGMENTS
                or limit >= 0
                and used + len(chunk) > limit
            ):
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id,
                        onion=turn.onion,
                        delivery=turn.delivery,
                        used_bytes=used,
                        limit_bytes=limit,
                        reason=MessageOperationReason.MEDIA_LIMIT,
                    )
                )
                frame = self._finalize_locked(turn, None)
                if frame is not None:
                    try:
                        self._send_outbound_frame(turn, *frame)
                    except OSError:
                        pass
                return
            try:
                chunk_id = self._put_capture_blob(msg_id, chunk)
            except Exception:
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=msg_id,
                        onion=turn.onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return
            turn.chunk_ids.append(chunk_id)
            turn.chunk_sizes.append(len(chunk))
            turn.data.extend(chunk)
            turn.size_bytes += len(chunk)
            safe_to_delete = True
            try:
                if turn.delivery is Delivery.LIVE:
                    admission = self._messages.grow_pending_live_voice_if_capacity(
                        turn.onion,
                        msg_id,
                        offset,
                        turn.size_bytes,
                        self._metadata(turn),
                        self._config.get_int(SettingKey.MAX_PENDING_LIVE_BYTES),
                    )
                    updated = admission is PendingLiveAdmission.ACCEPTED
                else:
                    updated = self._messages.update_retained_bytes(
                        turn.onion, msg_id, turn.size_bytes, self._metadata(turn)
                    )
                    admission = PendingLiveAdmission.ACCEPTED
            except Exception:
                canonical = self._canonical_outbound_metadata(turn)
                updated = canonical is True
                safe_to_delete = canonical is False
                if canonical is None:
                    # Force canonical rehydration before another mutation can
                    # overwrite a commit whose outcome is still unavailable.
                    self._outbound.pop(msg_id, None)
                admission = (
                    PendingLiveAdmission.ACCEPTED
                    if updated
                    else PendingLiveAdmission.DUPLICATE
                )
            if not updated:
                turn.chunk_ids.pop()
                turn.chunk_sizes.pop()
                del turn.data[-len(chunk) :]
                turn.size_bytes -= len(chunk)
                if safe_to_delete:
                    try:
                        self._blobs.delete(chunk_id, BlobLifecycle.TEMPORARY)
                    except Exception:
                        pass
                if admission is PendingLiveAdmission.BYTE_LIMIT:
                    self._broadcast(
                        VoiceResourceLimitEvent(
                            msg_id=msg_id,
                            onion=turn.onion,
                            delivery=turn.delivery,
                            used_bytes=used,
                            limit_bytes=self._config.get_int(
                                SettingKey.MAX_PENDING_LIVE_BYTES
                            ),
                            reason=MessageOperationReason.BYTE_LIMIT,
                        )
                    )
                    frame = self._finalize_locked(turn, None)
                    if frame is not None:
                        try:
                            self._send_outbound_frame(turn, *frame)
                        except OSError:
                            pass
                else:
                    self._broadcast(
                        VoiceOperationRejectedEvent(
                            msg_id=msg_id,
                            onion=turn.onion,
                            reason=MessageOperationReason.PERSISTENCE_FAILED,
                        )
                    )
                return
            accepted_turn = turn
            self._broadcast(
                VoiceChunkAcceptedEvent(msg_id=msg_id, next_offset=turn.size_bytes)
            )
            used += len(chunk)
            if (
                limit > 0
                and not turn.pressure_emitted
                and used * 100 >= limit * Constants.VOICE_PRESSURE_PERCENT
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
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id,
                        onion=turn.onion,
                        delivery=turn.delivery,
                        used_bytes=used,
                        limit_bytes=limit,
                    )
                )
                should_finalize = True
        if accepted_turn is not None:
            self._send_chunk(accepted_turn, offset, encoded_data)
        if should_finalize:
            self.finalize(msg_id, None)

    def _send_chunk(self, turn: VoiceTurn, offset: int, encoded_data: str) -> None:
        """Sends one chunk over the current session without changing retention.

        Args:
            turn (VoiceTurn): Outbound Voice turn.
            offset (int): Chunk byte offset.
            encoded_data (str): Base64 chunk bytes.

        Returns:
            None
        """
        conn = self._state.get_connection(turn.onion)
        if conn is None or turn.delivery is not Delivery.LIVE:
            return
        try:
            self._send_outbound_frame(
                turn,
                conn,
                self._wire(
                    TorCommand.VOICE_CHUNK,
                    {'id': turn.msg_id, 'offset': offset, 'data': encoded_data},
                ),
            )
        except OSError:
            return

    def finalize(self, msg_id: str, duration_ms: Optional[int]) -> None:
        """Finalizes one outbound Voice turn.

        Args:
            msg_id (str): Stable Voice identity.
            duration_ms (Optional[int]): Optional capture duration metadata.

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
            if turn is not None and (
                not turn.finalized or turn.duration_ms == duration_ms
            ):
                frame = self._finalize_locked(turn, duration_ms)
            elif turn is None:
                finalized = self._finalized_outbound_event(msg_id)
                if finalized is not None:
                    self._broadcast(finalized)
        if frame is not None:
            try:
                assert turn is not None
                self._send_outbound_frame(turn, *frame)
            except OSError:
                pass

    def _finalize_locked(
        self, turn: VoiceTurn, duration_ms: Optional[int]
    ) -> Optional[tuple[socket.socket, bytes]]:
        """Commits Voice finalization while holding the manager lock.

        Args:
            turn (VoiceTurn): Outbound logical turn.
            duration_ms (Optional[int]): Optional duration metadata.

        Returns:
            Optional[tuple[socket.socket, bytes]]: Deferred terminal frame.
        """
        previous_duration = turn.duration_ms
        previous_finalized = turn.finalized
        turn.duration_ms = duration_ms
        turn.finalized = True
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
            turn.duration_ms = previous_duration
            turn.finalized = previous_finalized
            self._broadcast(
                VoiceOperationRejectedEvent(
                    msg_id=turn.msg_id,
                    onion=turn.onion,
                    reason=MessageOperationReason.PERSISTENCE_FAILED,
                )
            )
            return None
        conn = self._state.get_connection(turn.onion)
        frame = (
            (
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
            if conn is not None and turn.delivery is Delivery.LIVE
            else None
        )
        if (
            turn.delivery is Delivery.LIVE
            and conn is None
            and not self._is_recovery_plausible(turn.onion)
            and self._config.get_bool(SettingKey.FALLBACK_TO_DROP)
        ):
            records = self._messages.promote_pending_live_to_drop(
                turn.onion, [turn.msg_id]
            )
            if records:
                self._state.invalidate_live_generations(turn.onion, [turn.msg_id])
                turn.delivery = Delivery.DROP
                turn.fallback_committed = True
                try:
                    self._promote_turn_blobs(turn)
                except Exception:
                    self._broadcast(
                        VoiceOperationRejectedEvent(
                            msg_id=turn.msg_id,
                            onion=turn.onion,
                            reason=MessageOperationReason.PERSISTENCE_FAILED,
                        )
                    )
                    return None
                self._state.remove_unacked_message(turn.onion, turn.msg_id)
                self._outbound.pop(turn.msg_id, None)
                self._broadcast(
                    FallbackSuccessEvent(
                        alias=turn.alias,
                        onion=turn.onion,
                        count=1,
                        msg_ids=[turn.msg_id],
                    )
                )
        elif turn.delivery is Delivery.DROP:
            try:
                self._promote_turn_blobs(turn)
            except Exception:
                self._broadcast(
                    VoiceOperationRejectedEvent(
                        msg_id=turn.msg_id,
                        onion=turn.onion,
                        reason=MessageOperationReason.PERSISTENCE_FAILED,
                    )
                )
                return None
            self._outbound.pop(turn.msg_id, None)
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
        return frame
