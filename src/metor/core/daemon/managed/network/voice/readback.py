"""Authenticated bounded Voice reading and explicit inbound consumption."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Optional

from metor.core.api import Delivery, MessageOperationReason, VoiceContent
from metor.data import MessageDirection, MessageStatus, SettingKey
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants

# Local Package Imports
from .models import VoiceTurn

if TYPE_CHECKING:
    from metor.data import MessageManager
    from metor.data.profile import Config


class VoiceReadbackMixin:
    """Owns local byte access and the explicit consume boundary, not playback."""

    _messages: MessageManager
    _blobs: BlobStore
    _config: Config
    _purge_fence: threading.Event
    _lock: threading.RLock
    _inbound: dict[tuple[str, str], VoiceTurn]

    if TYPE_CHECKING:

        @staticmethod
        def _metadata_blob_ids(payload: str) -> tuple[str, ...] | None:
            """Projects the complete validated local object inventory."""
            ...

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
                if delivery is Delivery.DROP
                and record.status != MessageStatus.DRAFT.value
                and finalized
                else BlobLifecycle.TEMPORARY
            )
            if (
                not self._blobs.exists(blob_id, lifecycle)
                and not self._blobs.exists(blob_id, BlobLifecycle.PERSISTENT)
            ) or offset > size_bytes:
                raise ValueError
            remaining = max_bytes
            position = 0
            selected = bytearray()
            for index, chunk_id in enumerate(chunk_ids):
                expected_size = chunk_sizes[index] if chunk_sizes is not None else None
                if expected_size is not None and offset >= position + expected_size:
                    position += expected_size
                    continue
                selected_lifecycle = (
                    lifecycle
                    if self._blobs.exists(chunk_id, lifecycle)
                    else BlobLifecycle.PERSISTENT
                )
                chunk = self._blobs.read(chunk_id, selected_lifecycle)
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
