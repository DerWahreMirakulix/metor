"""Inbound Voice frame admission on shared transfer-manager state."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
import socket
import threading
from typing import TYPE_CHECKING, Callable, Optional

from metor.core.api import (
    ContentType,
    Delivery,
    InboxNotificationEvent,
    IpcEvent,
    MessageReceivedEvent,
    MessageDirectionCode,
    RuntimeStateChangedEvent,
    VoiceChunkReceivedEvent,
    VoiceContent,
    VoiceFinalizedEvent,
    VoiceIncomingStartedEvent,
    is_valid_message_id,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    ContactManager,
    MessageDirection,
    MessageManager,
    MessageStatus,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants

from ...notify import NotificationPayload
from ..router.admission import FrameAdmission
from ..state import StateTracker
from .models import VoiceTurn

if TYPE_CHECKING:
    from metor.data.profile import Config


class VoiceInboundMixin:
    """Admits inbound begin/chunk/end frames under the manager-owned lock."""

    _contacts: ContactManager
    _messages: MessageManager
    _blobs: BlobStore
    _state: StateTracker
    _broadcast: Callable[[IpcEvent], None]
    _config: Config
    _has_clients: Callable[[], bool]
    _has_live_consumers: Callable[[], bool]
    _notify: Callable[[NotificationPayload], None]
    _lock: threading.RLock
    _purge_fence: threading.Event
    _inbound: dict[tuple[str, str], VoiceTurn]

    if TYPE_CHECKING:

        def _canonical_inbound_metadata(self, turn: VoiceTurn) -> bool | None: ...

        def _delete_turn_blobs(
            self, turn: VoiceTurn, lifecycle: BlobLifecycle
        ) -> None: ...

        def _limit(self) -> int: ...

        @staticmethod
        def _metadata(turn: VoiceTurn) -> str: ...

        def _promote_turn_blobs(self, turn: VoiceTurn) -> None: ...

        def _read_turn_range(
            self, turn: VoiceTurn, offset: int, size: int
        ) -> bytes: ...

        def _turn_from_metadata(
            self,
            onion: str,
            msg_id: str,
            payload: str,
            timestamp: str,
            delivery: Delivery,
            lifecycle: BlobLifecycle,
        ) -> Optional[VoiceTurn]: ...

        def _used_bytes(self) -> int: ...

    def receive_begin(
        self,
        conn: socket.socket,
        onion: str,
        payload: dict[str, object],
        delivery: Delivery = Delivery.LIVE,
    ) -> FrameAdmission:
        """Validates and initializes one inbound Voice stream.

        Args:
            conn (socket.socket): Authenticated peer socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded bounded envelope.
            delivery (Delivery): Logical LIVE or DROP semantics.

        Returns:
            FrameAdmission: Typed acceptance or termination outcome.
        """
        if self._purge_fence.is_set():
            return FrameAdmission.PURGING
        msg_id = payload.get('id')
        codec = payload.get('codec')
        offset = payload.get('offset', 0)
        timestamp = payload.get('timestamp')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or not isinstance(codec, str)
            or type(offset) is not int
            or offset < 0
            or (timestamp is not None and not isinstance(timestamp, str))
        ):
            return FrameAdmission.MALFORMED
        if not codec or len(codec) > Constants.VOICE_CODEC_MAX_CHARS:
            return FrameAdmission.MALFORMED
        with self._lock:
            if self._purge_fence.is_set():
                return FrameAdmission.PURGING
            if (onion, msg_id) in self._inbound:
                turn = self._inbound[(onion, msg_id)]
                if (
                    turn.codec != codec
                    or offset > turn.size_bytes
                    or (timestamp is not None and timestamp != turn.timestamp)
                    or (
                        delivery is Delivery.LIVE and turn.delivery is not Delivery.LIVE
                    )
                ):
                    return FrameAdmission.MALFORMED
                if delivery is Delivery.DROP and turn.delivery is Delivery.LIVE:
                    unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
                    if (
                        unseen_limit != -1
                        and self._messages.get_unread_drop_count(onion) >= unseen_limit
                    ):
                        return FrameAdmission.RESOURCE_LIMIT
                    if not self._messages.promote_inbound_voice_to_drop(
                        onion, msg_id, self._metadata(turn), turn.size_bytes
                    ):
                        return FrameAdmission.MALFORMED
                    turn.delivery = Delivery.DROP
                    if turn.finalized:
                        try:
                            self._promote_turn_blobs(turn)
                        except Exception:
                            return FrameAdmission.RESOURCE_LIMIT
                        self._inbound.pop((onion, msg_id), None)
                        self._broadcast(
                            RuntimeStateChangedEvent(scope='messages', onion=onion)
                        )
                elif delivery is Delivery.DROP and turn.finalized:
                    try:
                        self._promote_turn_blobs(turn)
                    except Exception:
                        return FrameAdmission.RESOURCE_LIMIT
                    self._inbound.pop((onion, msg_id), None)
                self._send_receive_offset(conn, turn)
                return FrameAdmission.ACCEPTED
            retained = self._messages.get_inbound_voice(onion, msg_id)
            if retained is not None:
                try:
                    if (
                        len(retained.payload.encode('utf-8'))
                        > Constants.VOICE_METADATA_MAX_BYTES
                    ):
                        return FrameAdmission.MALFORMED
                    metadata = json.loads(retained.payload)
                    if not isinstance(metadata, dict):
                        return FrameAdmission.MALFORMED
                    stored_delivery = Delivery(retained.delivery)
                    finalized = bool(metadata.get('finalized', False))
                    lifecycle = (
                        BlobLifecycle.PERSISTENT
                        if stored_delivery is Delivery.DROP and finalized
                        else BlobLifecycle.TEMPORARY
                    )
                    hydrated_turn = self._turn_from_metadata(
                        onion,
                        msg_id,
                        retained.payload,
                        retained.timestamp,
                        stored_delivery,
                        lifecycle,
                    )
                    if hydrated_turn is None:
                        return FrameAdmission.MALFORMED
                    turn = hydrated_turn
                except (KeyError, TypeError, ValueError, OSError):
                    return FrameAdmission.MALFORMED
                if (
                    turn.codec != codec
                    or offset > turn.size_bytes
                    or (timestamp is not None and timestamp != turn.timestamp)
                    or (
                        delivery is Delivery.LIVE and turn.delivery is not Delivery.LIVE
                    )
                ):
                    return FrameAdmission.MALFORMED
                if delivery is Delivery.DROP and turn.delivery is Delivery.LIVE:
                    unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
                    if (
                        unseen_limit != -1
                        and self._messages.get_unread_drop_count(onion) >= unseen_limit
                    ):
                        return FrameAdmission.RESOURCE_LIMIT
                    if not self._messages.promote_inbound_voice_to_drop(
                        onion, msg_id, self._metadata(turn), turn.size_bytes
                    ):
                        return FrameAdmission.MALFORMED
                    turn.delivery = Delivery.DROP
                    if turn.finalized:
                        self._promote_turn_blobs(turn)
                        self._broadcast(
                            RuntimeStateChangedEvent(scope='messages', onion=onion)
                        )
                if finalized:
                    self._send_receive_offset(conn, turn)
                    return FrameAdmission.ACCEPTED
                self._inbound[(onion, msg_id)] = turn
                self._send_receive_offset(conn, turn)
                return FrameAdmission.ACCEPTED
            if self._messages.has_inbound_message(onion, msg_id):
                if not self._messages.has_inbound_voice_receipt(onion, msg_id):
                    return FrameAdmission.MALFORMED
                if delivery is Delivery.LIVE:
                    self._state.send_frame(
                        conn,
                        f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode(
                            'ascii'
                        ),
                    )
                    return FrameAdmission.ACCEPTED
                alias = self._contacts.ensure_alias_for_onion(onion) or onion
                try:
                    blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
                except Exception:
                    return FrameAdmission.RESOURCE_LIMIT
                turn = VoiceTurn(
                    alias=alias,
                    onion=onion,
                    msg_id=msg_id,
                    delivery=Delivery.DROP,
                    codec=codec,
                    blob_id=blob_id,
                    chunk_ids=[],
                    chunk_sizes=[],
                    data=bytearray(),
                    timestamp=str(timestamp or datetime.now(timezone.utc).isoformat()),
                )
                if not self._messages.promote_inbound_voice_to_drop(
                    onion, msg_id, self._metadata(turn), 0
                ):
                    self._delete_turn_blobs(turn, BlobLifecycle.TEMPORARY)
                    return FrameAdmission.MALFORMED
                self._inbound[(onion, msg_id)] = turn
                self._send_receive_offset(conn, turn)
                return FrameAdmission.ACCEPTED
            limit = self._limit()
            if limit >= 0 and self._used_bytes() >= limit:
                return FrameAdmission.RESOURCE_LIMIT
            if delivery is Delivery.LIVE:
                unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
                if unseen_limit == 0 and not self._has_live_consumers():
                    return FrameAdmission.RESOURCE_LIMIT
                if (
                    unseen_limit > 0
                    and self._messages.get_unread_live_count(onion) >= unseen_limit
                ):
                    return FrameAdmission.RESOURCE_LIMIT
            else:
                unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
                if (
                    unseen_limit != -1
                    and self._messages.get_unread_drop_count(onion) >= unseen_limit
                ):
                    return FrameAdmission.RESOURCE_LIMIT
            alias = self._contacts.ensure_alias_for_onion(onion) or onion
            try:
                blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
            except Exception:
                return FrameAdmission.RESOURCE_LIMIT
            turn = VoiceTurn(
                alias=alias,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                context_generation=self._state.get_live_context_generation(onion),
                codec=codec,
                blob_id=blob_id,
                chunk_ids=[],
                chunk_sizes=[],
                data=bytearray(),
                timestamp=str(timestamp or datetime.now(timezone.utc).isoformat()),
            )
            try:
                queued = self._messages.queue_message(
                    contact_onion=onion,
                    direction=MessageDirection.IN,
                    delivery=delivery,
                    content_type=ContentType.VOICE,
                    payload=self._metadata(turn),
                    status=MessageStatus.UNREAD,
                    msg_id=msg_id,
                    timestamp=turn.timestamp,
                )
            except Exception:
                queued = None
            if not queued:
                canonical = self._canonical_inbound_metadata(turn)
                if canonical is not True:
                    if canonical is False:
                        self._delete_turn_blobs(turn, BlobLifecycle.TEMPORARY)
                    return FrameAdmission.RESOURCE_LIMIT
            self._inbound[(onion, msg_id)] = turn
            if (
                delivery is Delivery.LIVE
                and self._has_clients()
                and self._has_live_consumers()
            ):
                self._broadcast(
                    VoiceIncomingStartedEvent(
                        alias=alias,
                        onion=onion,
                        msg_id=msg_id,
                        delivery=delivery,
                        codec=codec,
                        next_offset=0,
                    )
                )
            self._send_receive_offset(conn, turn)
            return FrameAdmission.ACCEPTED

    def _send_receive_offset(self, conn: socket.socket, turn: VoiceTurn) -> None:
        """Acknowledges a resumable byte boundary or completed DROP item."""
        if turn.finalized:
            self._state.send_frame(
                conn,
                f'{TorCommand.VOICE_COMMIT_ACK.value} {turn.msg_id}\n'.encode('ascii'),
            )
            return
        self._state.send_frame(
            conn,
            f'{TorCommand.VOICE_ACK.value} {turn.msg_id} {turn.size_bytes}\n'.encode(
                'ascii'
            ),
        )

    def receive_chunk(
        self, conn: socket.socket, onion: str, payload: dict[str, object]
    ) -> FrameAdmission:
        """Validates, retains, streams, and acknowledges one inbound chunk.

        Args:
            conn (socket.socket): Authenticated LIVE socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded chunk envelope.

        Returns:
            FrameAdmission: Typed acceptance or termination outcome.
        """
        if self._purge_fence.is_set():
            return FrameAdmission.PURGING
        msg_id = payload.get('id')
        offset = payload.get('offset')
        encoded = payload.get('data')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or type(offset) is not int
            or offset < 0
            or not isinstance(encoded, str)
        ):
            return FrameAdmission.MALFORMED
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return FrameAdmission.MALFORMED
        if not chunk or len(chunk) > Constants.VOICE_CHUNK_MAX_BYTES:
            return FrameAdmission.MALFORMED
        received_event: Optional[VoiceChunkReceivedEvent] = None
        with self._lock:
            if self._purge_fence.is_set():
                return FrameAdmission.PURGING
            turn = self._inbound.get((onion, msg_id))
            if turn is None or turn.finalized or offset > turn.size_bytes:
                return FrameAdmission.MALFORMED
            if offset < turn.size_bytes:
                duplicate_end = offset + len(chunk)
                if (
                    duplicate_end > turn.size_bytes
                    or self._read_turn_range(turn, offset, len(chunk)) != chunk
                ):
                    return FrameAdmission.MALFORMED
            else:
                limit = self._limit()
                if (
                    len(turn.chunk_ids) >= Constants.VOICE_MAX_SEGMENTS
                    or limit >= 0
                    and self._used_bytes() + len(chunk) > limit
                ):
                    return FrameAdmission.RESOURCE_LIMIT
                try:
                    chunk_id = self._blobs.put(chunk, BlobLifecycle.TEMPORARY)
                except Exception:
                    return FrameAdmission.RESOURCE_LIMIT
                turn.chunk_ids.append(chunk_id)
                turn.chunk_sizes.append(len(chunk))
                turn.data.extend(chunk)
                turn.size_bytes += len(chunk)
                try:
                    updated = self._messages.update_inbound_voice_metadata(
                        onion, msg_id, turn.size_bytes, self._metadata(turn)
                    )
                except Exception:
                    updated = False
                if not updated:
                    canonical = self._canonical_inbound_metadata(turn)
                    if canonical is None:
                        # Preserve possibly committed segments. A new BEGIN must
                        # reload the canonical receipt, not reuse speculative RAM.
                        self._inbound.pop((onion, msg_id), None)
                        return FrameAdmission.RESOURCE_LIMIT
                    updated = canonical
                if not updated:
                    turn.chunk_ids.pop()
                    turn.chunk_sizes.pop()
                    del turn.data[-len(chunk) :]
                    turn.size_bytes -= len(chunk)
                    try:
                        self._blobs.delete(chunk_id, BlobLifecycle.TEMPORARY)
                    except Exception:
                        pass
                    return FrameAdmission.RESOURCE_LIMIT
                if (
                    turn.delivery is Delivery.LIVE
                    and self._has_clients()
                    and self._has_live_consumers()
                ):
                    received_event = VoiceChunkReceivedEvent(
                        alias=turn.alias,
                        onion=onion,
                        msg_id=msg_id,
                        offset=offset,
                        data=encoded,
                        delivery=turn.delivery,
                        codec=turn.codec,
                    )
            next_offset = turn.size_bytes
        if received_event is not None:
            self._broadcast(received_event)
        try:
            self._state.send_frame(
                conn,
                f'{TorCommand.VOICE_ACK.value} {msg_id} {next_offset}\n'.encode(
                    'ascii'
                ),
            )
        except OSError:
            pass
        return FrameAdmission.ACCEPTED

    def receive_end(
        self, conn: socket.socket, onion: str, payload: dict[str, object]
    ) -> FrameAdmission:
        """Finalizes one inbound Voice item after exact size validation.

        Args:
            conn (socket.socket): Authenticated LIVE socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded final envelope.

        Returns:
            FrameAdmission: Typed acceptance or termination outcome.
        """
        if self._purge_fence.is_set():
            return FrameAdmission.PURGING
        msg_id = payload.get('id')
        size = payload.get('size')
        duration_ms = payload.get('duration_ms')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or type(size) is not int
            or size < 0
            or size > Constants.VOICE_TURN_HARD_MAX_BYTES
            or (duration_ms is not None and type(duration_ms) is not int)
            or (isinstance(duration_ms, int) and duration_ms < 0)
        ):
            return FrameAdmission.MALFORMED
        with self._lock:
            if self._purge_fence.is_set():
                return FrameAdmission.PURGING
            turn = self._inbound.get((onion, msg_id))
            if turn is None:
                retained = self._messages.get_inbound_voice(onion, msg_id)
                if retained is not None:
                    try:
                        metadata = json.loads(retained.payload)
                    except (TypeError, ValueError):
                        metadata = None
                    if isinstance(metadata, dict) and metadata.get('finalized') is True:
                        if (
                            metadata.get('size_bytes') != size
                            or metadata.get('duration_ms') != duration_ms
                        ):
                            return FrameAdmission.MALFORMED
                        self._state.send_frame(
                            conn,
                            f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode(
                                'ascii'
                            ),
                        )
                        return FrameAdmission.ACCEPTED
                return FrameAdmission.MALFORMED
            if turn.finalized:
                if size != turn.size_bytes or duration_ms != turn.duration_ms:
                    return FrameAdmission.MALFORMED
                if turn.delivery is Delivery.DROP:
                    try:
                        self._promote_turn_blobs(turn)
                    except Exception:
                        return FrameAdmission.RESOURCE_LIMIT
                    self._inbound.pop((onion, msg_id), None)
                    self._notify_inbox(turn)
                    self._broadcast(
                        VoiceFinalizedEvent(
                            msg_id=msg_id,
                            size_bytes=turn.size_bytes,
                            onion=onion,
                            delivery=turn.delivery,
                            direction=MessageDirectionCode.IN,
                            duration_ms=turn.duration_ms,
                        )
                    )
                    self._broadcast(
                        RuntimeStateChangedEvent(scope='inbox', onion=onion)
                    )
                self._state.send_frame(
                    conn,
                    f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode('ascii'),
                )
                return FrameAdmission.ACCEPTED
            if size != turn.size_bytes:
                return FrameAdmission.MALFORMED
            previous_duration = turn.duration_ms
            previous_finalized = turn.finalized
            turn.duration_ms = duration_ms
            turn.finalized = True
            try:
                updated = self._messages.update_inbound_voice_metadata(
                    onion, msg_id, turn.size_bytes, self._metadata(turn)
                )
            except Exception:
                updated = False
            if not updated:
                canonical = self._canonical_inbound_metadata(turn)
                if canonical is None:
                    self._inbound.pop((onion, msg_id), None)
                    return FrameAdmission.RESOURCE_LIMIT
                updated = canonical
            if not updated:
                turn.duration_ms = previous_duration
                turn.finalized = previous_finalized
                return FrameAdmission.RESOURCE_LIMIT
            content = VoiceContent(
                blob_id=turn.blob_id,
                codec=turn.codec,
                size_bytes=turn.size_bytes,
                duration_ms=turn.duration_ms,
            )
            if turn.delivery is Delivery.DROP:
                try:
                    self._promote_turn_blobs(turn)
                except Exception:
                    return FrameAdmission.RESOURCE_LIMIT
                self._inbound.pop((onion, msg_id), None)
                self._notify_inbox(turn)
                self._state.send_frame(
                    conn,
                    f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode('ascii'),
                )
            else:
                if self._has_clients() and self._has_live_consumers():
                    self._broadcast(
                        MessageReceivedEvent(
                            alias=turn.alias,
                            onion=onion,
                            delivery=Delivery.LIVE,
                            content=content,
                            timestamp=turn.timestamp,
                            msg_id=msg_id,
                        )
                    )
                else:
                    self._notify_inbox(turn)
                self._send_receive_offset(conn, turn)
            self._broadcast(
                VoiceFinalizedEvent(
                    msg_id=msg_id,
                    size_bytes=turn.size_bytes,
                    onion=onion,
                    delivery=turn.delivery,
                    direction=MessageDirectionCode.IN,
                    duration_ms=turn.duration_ms,
                )
            )
            self._broadcast(RuntimeStateChangedEvent(scope='inbox', onion=onion))
            return FrameAdmission.ACCEPTED

    def _notify_inbox(self, turn: VoiceTurn) -> None:
        """Emits content-free attached or detached unseen notification metadata."""
        if self._has_clients():
            self._broadcast(
                InboxNotificationEvent(
                    alias=turn.alias,
                    onion=turn.onion,
                    count=1,
                    delivery=turn.delivery,
                    source_id=turn.msg_id,
                )
            )
            return
        self._notify(
            NotificationPayload(
                kind='inbox_notification',
                peer_alias=turn.alias,
                peer_onion=turn.onion,
                count=1,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )
