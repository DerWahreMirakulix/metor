"""Outbound Voice capture, persistence, replay, and acknowledgement."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
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
    VoiceContent,
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


class VoiceOutboundMixin:
    """Owns outbound Voice draft, LIVE replay, fallback, and ACK behavior."""

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

    @staticmethod
    def _metadata(turn: VoiceTurn) -> str:
        """Returns metadata through the concrete transfer manager."""
        raise NotImplementedError

    @staticmethod
    def _metadata_blob_ids(payload: str) -> Optional[tuple[str, ...]]:
        """Returns segmented IDs through the concrete transfer manager."""
        raise NotImplementedError

    @staticmethod
    def _metadata_finalized(payload: str) -> bool:
        """Checks finalized metadata through the concrete transfer manager."""
        raise NotImplementedError

    def _limit(self) -> int:
        """Returns the configured Voice limit from the concrete manager."""
        raise NotImplementedError

    def _used_bytes(self) -> int:
        """Returns retained bytes from the concrete manager."""
        raise NotImplementedError

    def _read_turn_range(
        self,
        turn: VoiceTurn,
        offset: int,
        max_bytes: int,
        lifecycle: BlobLifecycle = BlobLifecycle.TEMPORARY,
    ) -> bytes:
        """Reads a bounded segment range through the concrete manager."""
        raise NotImplementedError

    def _delete_turn_blobs(self, turn: VoiceTurn, lifecycle: BlobLifecycle) -> None:
        """Deletes turn segments through the concrete manager."""
        raise NotImplementedError

    def _promote_turn_blobs(self, turn: VoiceTurn) -> None:
        """Promotes turn segments through the concrete manager."""
        raise NotImplementedError

    @staticmethod
    def _wire(command: TorCommand, payload: dict[str, object]) -> bytes:
        """Serializes a wire frame through the concrete manager."""
        raise NotImplementedError

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
                blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
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
                persistence_failed = True
                admission = PendingLiveAdmission.DUPLICATE
            if persistence_failed:
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
                chunk_id = self._blobs.put(chunk, BlobLifecycle.TEMPORARY)
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
                updated = False
                admission = PendingLiveAdmission.DUPLICATE
            if not updated:
                turn.chunk_ids.pop()
                turn.chunk_sizes.pop()
                del turn.data[-len(chunk) :]
                turn.size_bytes -= len(chunk)
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
            updated = False
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

    def promote_fallback(self, msg_ids: list[str]) -> None:
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
            selected = (
                [
                    self._outbound[msg_id]
                    for msg_id in msg_ids
                    if msg_id in self._outbound
                    and self._state.get_live_generation(
                        self._outbound[msg_id].onion, msg_id
                    )
                    is None
                ]
                if msg_ids
                else [
                    turn
                    for turn in self._outbound.values()
                    if self._state.get_live_generation(turn.onion, turn.msg_id) is None
                ]
            )
            for turn in selected:
                turn.delivery = Delivery.DROP
                self._promote_turn_blobs(turn)
                self._outbound.pop(turn.msg_id, None)

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
        """Releases retained LIVE Voice after a terminal logical-message ACK."""
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
        """Releases Core-owned inbound LIVE Voice payloads after explicit consume."""
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
        """Returns the immutable onion target bound at Voice begin."""
        with self._lock:
            turn = self._outbound.get(msg_id)
            return turn.onion if turn is not None else None

    def outbound_delivery(self, msg_id: str) -> Optional[Delivery]:
        """Returns the immutable delivery semantics selected at Voice begin."""
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
        """Consumes and releases one finalized inbound Voice item explicitly."""
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
