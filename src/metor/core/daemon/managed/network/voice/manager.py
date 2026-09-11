"""Bounded, resumable Voice transfer over authenticated LIVE sessions."""

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import socket
import threading
from typing import TYPE_CHECKING, Callable, Optional

from metor.core.api import (
    ContentType,
    Delivery,
    FallbackSuccessEvent,
    InboxNotificationEvent,
    IpcEvent,
    LiveMessageUnavailableEvent,
    MessageReceivedEvent,
    VoiceChunkAcceptedEvent,
    VoiceChunkReceivedEvent,
    VoiceContent,
    VoiceFinalizedEvent,
    VoiceResourceLimitEvent,
    VoiceResourcePressureEvent,
    VoiceStartedEvent,
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

# Local Package Imports
from ..state import StateTracker
from ...notify import NotificationPayload

if TYPE_CHECKING:
    from metor.data.profile import Config


@dataclass
class VoiceTurn:
    """Tracks one peer-bound logical Voice turn and its resume position."""

    alias: str
    onion: str
    msg_id: str
    delivery: Delivery
    codec: str
    blob_id: str
    data: bytearray
    timestamp: str
    acknowledged_offset: int = 0
    duration_ms: Optional[int] = None
    finalized: bool = False
    pressure_emitted: bool = False


class VoiceTransferManager:
    """Owns bounded Voice capture, receive, resume, and fallback state."""

    def __init__(
        self,
        *,
        contacts: ContactManager,
        messages: MessageManager,
        blobs: BlobStore,
        state: StateTracker,
        broadcast: Callable[[IpcEvent], None],
        config: 'Config',
        has_clients_callback: Optional[Callable[[], bool]] = None,
        has_live_consumers_callback: Optional[Callable[[], bool]] = None,
        notify_callback: Optional[Callable[[NotificationPayload], None]] = None,
    ) -> None:
        """Initializes Voice transfer state with existing message primitives.

        Args:
            contacts (object): Contact manager implementing target resolution.
            messages (MessageManager): Canonical message receipt/spool service.
            blobs (BlobStore): Profile-mode external object store.
            state (StateTracker): Shared LIVE transport state.
            broadcast (Callable[[IpcEvent], None]): Typed IPC broadcaster.
            config (object): Profile config implementing typed getters.
            has_clients_callback (Optional[Callable[[], bool]]): IPC-client check.
            has_live_consumers_callback (Optional[Callable[[], bool]]): Active
                interactive LIVE-consumer check.
            notify_callback (Optional[Callable]): Detached notification sink.

        Returns:
            None
        """
        self._contacts = contacts
        self._messages = messages
        self._blobs = blobs
        self._state = state
        self._broadcast = broadcast
        self._config = config
        self._has_clients = has_clients_callback or (lambda: True)
        self._has_live_consumers = has_live_consumers_callback or (lambda: True)
        self._notify = notify_callback or (lambda _payload: None)
        self._lock = threading.RLock()
        self._outbound: dict[str, VoiceTurn] = {}
        self._inbound: dict[tuple[str, str], VoiceTurn] = {}
        self._hydrate_retained_turns()

    def _hydrate_retained_turns(self) -> None:
        """Restores resumable Voice turns from canonical receipt/blob storage."""
        for record in self._messages.get_pending_live_outbox():
            if record.content_type != ContentType.VOICE.value:
                continue
            turn = self._turn_from_metadata(
                record.peer_onion,
                record.msg_id,
                record.payload,
                record.timestamp,
                Delivery.LIVE,
                BlobLifecycle.TEMPORARY,
            )
            if turn is not None:
                self._outbound[record.msg_id] = turn
                self._state.add_unacked_message(
                    record.peer_onion,
                    record.msg_id,
                    record.payload,
                    record.timestamp,
                )
        for inbound_record in self._messages.get_unread_inbound_live_voices():
            turn = self._turn_from_metadata(
                inbound_record.peer_onion,
                inbound_record.msg_id,
                inbound_record.payload,
                inbound_record.timestamp,
                Delivery.LIVE,
                BlobLifecycle.TEMPORARY,
            )
            if turn is not None:
                self._inbound[(inbound_record.peer_onion, inbound_record.msg_id)] = turn

    def _turn_from_metadata(
        self,
        onion: str,
        msg_id: str,
        payload: str,
        timestamp: str,
        delivery: Delivery,
        lifecycle: BlobLifecycle,
    ) -> Optional[VoiceTurn]:
        """Builds one retained turn without trusting serialized byte counts."""
        try:
            metadata = json.loads(payload)
            if not isinstance(metadata, dict):
                return None
            blob_id = str(metadata['blob_id'])
            data = self._blobs.read(blob_id, lifecycle)
            duration = metadata.get('duration_ms')
            return VoiceTurn(
                alias=self._contacts.ensure_alias_for_onion(onion) or onion,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=str(metadata['codec']),
                blob_id=blob_id,
                data=bytearray(data),
                timestamp=timestamp,
                duration_ms=int(duration) if duration is not None else None,
                finalized=bool(metadata.get('finalized', False)),
                acknowledged_offset=int(metadata.get('acknowledged_offset', 0)),
            )
        except (KeyError, TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _metadata(turn: VoiceTurn) -> str:
        """Serializes content-only Voice metadata for the message spool.

        Args:
            turn (VoiceTurn): Logical Voice turn.

        Returns:
            str: Compact canonical JSON metadata.
        """
        return json.dumps(
            {
                'type': 'voice',
                'blob_id': turn.blob_id,
                'codec': turn.codec,
                'size_bytes': len(turn.data),
                'duration_ms': turn.duration_ms,
                'finalized': turn.finalized,
                'acknowledged_offset': turn.acknowledged_offset,
            },
            separators=(',', ':'),
        )

    @staticmethod
    def _wire(command: TorCommand, payload: dict[str, object]) -> bytes:
        """Builds one bounded Base64 JSON Voice protocol frame.

        Args:
            command (TorCommand): Voice protocol command.
            payload (dict[str, object]): Strict small envelope.

        Returns:
            bytes: Newline-delimited authenticated-session frame.
        """
        encoded = base64.b64encode(
            json.dumps(payload, separators=(',', ':')).encode('utf-8')
        ).decode('ascii')
        return f'{command.value} {encoded}\n'.encode('ascii')

    def _limit(self) -> int:
        """Returns the configured profile Voice retention budget.

        Args:
            None

        Returns:
            int: Byte limit, with -1 meaning unlimited.
        """
        return self._config.get_int(SettingKey.MAX_LIVE_VOICE_BUFFER_BYTES)

    def _used_bytes(self) -> int:
        """Returns current local and inbound in-memory Voice retention.

        Args:
            None

        Returns:
            int: Retained Voice bytes.
        """
        return sum(len(turn.data) for turn in self._outbound.values()) + sum(
            len(turn.data) for turn in self._inbound.values()
        )

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
            limit = self._limit()
            used = self._used_bytes()
            if msg_id in self._outbound or (limit >= 0 and used >= limit):
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id, used_bytes=used, limit_bytes=limit
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
            blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
            turn = VoiceTurn(
                alias=alias,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=codec,
                blob_id=blob_id,
                data=bytearray(),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._outbound[msg_id] = turn
            self._messages.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                delivery=delivery,
                content_type=ContentType.VOICE,
                payload=self._metadata(turn),
                status=MessageStatus.PENDING,
                msg_id=msg_id,
                timestamp=turn.timestamp,
            )
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
        return (
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
            conn.sendall(
                self._wire(
                    TorCommand.VOICE_BEGIN,
                    {
                        'id': turn.msg_id,
                        'codec': turn.codec,
                        'offset': turn.acknowledged_offset,
                        'timestamp': turn.timestamp,
                    },
                )
            )
        except OSError:
            return

    def append(self, msg_id: str, offset: int, encoded_data: str) -> None:
        """Appends and durably retains one exact-offset Voice chunk.

        Args:
            msg_id (str): Stable Voice identity.
            offset (int): Expected current byte length.
            encoded_data (str): Strict Base64 chunk.

        Returns:
            None
        """
        try:
            chunk = base64.b64decode(encoded_data, validate=True)
        except (binascii.Error, ValueError):
            return
        if not chunk or len(chunk) > Constants.VOICE_CHUNK_MAX_BYTES:
            return
        with self._lock:
            turn = self._outbound.get(msg_id)
            if turn is None or turn.finalized or offset != len(turn.data):
                return
            limit = self._limit()
            used = self._used_bytes()
            if limit >= 0 and used + len(chunk) > limit:
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id, used_bytes=used, limit_bytes=limit
                    )
                )
                self._finalize_locked(turn, None)
                return
            turn.data.extend(chunk)
            old_blob_id = turn.blob_id
            turn.blob_id = self._blobs.put(bytes(turn.data), BlobLifecycle.TEMPORARY)
            if not self._messages.update_retained_bytes(
                turn.onion, msg_id, len(turn.data), self._metadata(turn)
            ):
                self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)
                turn.blob_id = old_blob_id
                del turn.data[-len(chunk) :]
                return
            self._blobs.delete(old_blob_id, BlobLifecycle.TEMPORARY)
            self._send_chunk(turn, offset, encoded_data)
            self._broadcast(
                VoiceChunkAcceptedEvent(msg_id=msg_id, next_offset=len(turn.data))
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
                        msg_id=msg_id, used_bytes=used, limit_bytes=limit
                    )
                )
            if limit >= 0 and used >= limit:
                self._broadcast(
                    VoiceResourceLimitEvent(
                        msg_id=msg_id, used_bytes=used, limit_bytes=limit
                    )
                )
                self._finalize_locked(turn, None)

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
            conn.sendall(
                self._wire(
                    TorCommand.VOICE_CHUNK,
                    {'id': turn.msg_id, 'offset': offset, 'data': encoded_data},
                )
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
        with self._lock:
            turn = self._outbound.get(msg_id)
            if turn is not None and not turn.finalized:
                self._finalize_locked(turn, duration_ms)

    def _finalize_locked(self, turn: VoiceTurn, duration_ms: Optional[int]) -> None:
        """Commits Voice finalization while holding the manager lock.

        Args:
            turn (VoiceTurn): Outbound logical turn.
            duration_ms (Optional[int]): Optional duration metadata.

        Returns:
            None
        """
        turn.duration_ms = duration_ms
        turn.finalized = True
        self._messages.update_retained_bytes(
            turn.onion, turn.msg_id, len(turn.data), self._metadata(turn)
        )
        conn = self._state.get_connection(turn.onion)
        if conn is not None and turn.delivery is Delivery.LIVE:
            try:
                conn.sendall(
                    self._wire(
                        TorCommand.VOICE_END,
                        {'id': turn.msg_id, 'size': len(turn.data)},
                    )
                )
            except OSError:
                pass
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
                self._blobs.promote(turn.blob_id)
                turn.delivery = Delivery.DROP
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
            self._blobs.promote(turn.blob_id)
            self._outbound.pop(turn.msg_id, None)
        self._broadcast(
            VoiceFinalizedEvent(msg_id=turn.msg_id, size_bytes=len(turn.data))
        )

    def replay(self, onion: str) -> list[str]:
        """Resumes retained Voice turns after their acknowledged byte offset.

        Args:
            onion (str): Recovered peer identity.

        Returns:
            list[str]: Logical Voice IDs resumed.
        """
        resumed: list[str] = []
        with self._lock:
            for turn in self._outbound.values():
                if turn.onion != onion or turn.delivery is not Delivery.LIVE:
                    continue
                self._send_begin(turn)
                offset = turn.acknowledged_offset
                while offset < len(turn.data):
                    chunk = bytes(
                        turn.data[offset : offset + Constants.VOICE_CHUNK_MAX_BYTES]
                    )
                    self._send_chunk(
                        turn, offset, base64.b64encode(chunk).decode('ascii')
                    )
                    offset += len(chunk)
                if turn.finalized:
                    conn = self._state.get_connection(onion)
                    if conn is not None:
                        conn.sendall(
                            self._wire(
                                TorCommand.VOICE_END,
                                {'id': turn.msg_id, 'size': len(turn.data)},
                            )
                        )
                resumed.append(turn.msg_id)
        return resumed

    def promote_fallback(self, msg_ids: list[str]) -> None:
        """Releases LIVE Voice budget after message-level fallback commits.

        Args:
            msg_ids (list[str]): Successfully promoted logical identities.

        Returns:
            None
        """
        with self._lock:
            for msg_id in msg_ids:
                turn = self._outbound.get(msg_id)
                if turn is None:
                    continue
                self._blobs.promote(turn.blob_id)
                turn.delivery = Delivery.DROP
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
        with self._lock:
            turn = self._outbound.get(msg_id)
            if turn is None or turn.onion != onion:
                return
            if next_offset < turn.acknowledged_offset or next_offset > len(turn.data):
                return
            turn.acknowledged_offset = next_offset
            self._messages.update_retained_bytes(
                onion, msg_id, len(turn.data), self._metadata(turn)
            )
            if turn.finalized and next_offset == len(turn.data):
                self._messages.update_outbound_message_status(
                    onion, msg_id, MessageStatus.DELIVERED
                )
                self._state.remove_unacked_message(onion, msg_id)
                self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)
                self._outbound.pop(msg_id, None)

    def acknowledge_complete(self, onion: str, msg_id: str) -> None:
        """Releases retained LIVE Voice after a terminal logical-message ACK."""
        with self._lock:
            turn = self._outbound.get(msg_id)
            if (
                turn is None
                or turn.onion != onion
                or turn.delivery is not Delivery.LIVE
            ):
                return
            self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)
            self._outbound.pop(msg_id, None)

    def release_consumed(self, onion: str, msg_ids: list[str]) -> None:
        """Releases Core-owned inbound LIVE Voice payloads after explicit consume."""
        with self._lock:
            for msg_id in msg_ids:
                turn = self._inbound.pop((onion, msg_id), None)
                if turn is not None and turn.delivery is Delivery.LIVE:
                    self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)

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

    def dismiss_inbound(self, onion: str) -> None:
        """Shreds all retained inbound LIVE Voice payloads for one context."""
        with self._lock:
            keys = [key for key in self._inbound if key[0] == onion]
            for key in keys:
                turn = self._inbound.pop(key)
                if turn.delivery is Delivery.LIVE:
                    self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)

    def receive_begin(
        self,
        conn: socket.socket,
        onion: str,
        payload: dict[str, object],
        delivery: Delivery = Delivery.LIVE,
    ) -> bool:
        """Validates and initializes one inbound Voice stream.

        Args:
            conn (socket.socket): Authenticated peer socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded bounded envelope.
            delivery (Delivery): Logical LIVE or DROP semantics.

        Returns:
            bool: True when the session must terminate for resource pressure.
        """
        msg_id = payload.get('id')
        codec = payload.get('codec')
        timestamp = payload.get('timestamp')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or not isinstance(codec, str)
        ):
            return True
        if not codec or len(codec) > Constants.VOICE_CODEC_MAX_CHARS:
            return True
        with self._lock:
            if (onion, msg_id) in self._inbound:
                turn = self._inbound[(onion, msg_id)]
                self._send_receive_offset(conn, turn)
                return False
            retained = self._messages.get_inbound_voice(onion, msg_id)
            if retained is not None:
                try:
                    metadata = json.loads(retained.payload)
                    if not isinstance(metadata, dict):
                        return True
                    stored_delivery = Delivery(retained.delivery)
                    finalized = bool(metadata.get('finalized', False))
                    blob_id = str(metadata['blob_id'])
                    lifecycle = (
                        BlobLifecycle.PERSISTENT
                        if stored_delivery is Delivery.DROP and finalized
                        else BlobLifecycle.TEMPORARY
                    )
                    retained_data = self._blobs.read(blob_id, lifecycle)
                    turn = VoiceTurn(
                        alias=self._contacts.ensure_alias_for_onion(onion) or onion,
                        onion=onion,
                        msg_id=msg_id,
                        delivery=stored_delivery,
                        codec=str(metadata['codec']),
                        blob_id=blob_id,
                        data=bytearray(retained_data),
                        timestamp=retained.timestamp,
                        duration_ms=(
                            int(metadata['duration_ms'])
                            if metadata.get('duration_ms') is not None
                            else None
                        ),
                        finalized=finalized,
                    )
                except (KeyError, TypeError, ValueError, OSError):
                    return True
                if finalized:
                    self._send_receive_offset(conn, turn)
                    return False
                self._inbound[(onion, msg_id)] = turn
                self._send_receive_offset(conn, turn)
                return False
            if self._messages.has_inbound_message(onion, msg_id):
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('ascii'))
                return False
            limit = self._limit()
            if limit >= 0 and self._used_bytes() >= limit:
                return True
            if delivery is Delivery.LIVE:
                unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
                if unseen_limit == 0 and not self._has_live_consumers():
                    return True
                if (
                    unseen_limit > 0
                    and self._messages.get_unread_live_count(onion) >= unseen_limit
                ):
                    return True
            else:
                unseen_limit = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
                if (
                    unseen_limit != -1
                    and self._messages.get_unread_drop_count(onion) >= unseen_limit
                ):
                    return True
            alias = self._contacts.ensure_alias_for_onion(onion) or onion
            blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
            turn = VoiceTurn(
                alias=alias,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=codec,
                blob_id=blob_id,
                data=bytearray(),
                timestamp=str(timestamp or datetime.now(timezone.utc).isoformat()),
            )
            self._inbound[(onion, msg_id)] = turn
            self._messages.queue_message(
                contact_onion=onion,
                direction=MessageDirection.IN,
                delivery=delivery,
                content_type=ContentType.VOICE,
                payload=self._metadata(turn),
                status=MessageStatus.UNREAD,
                msg_id=msg_id,
                timestamp=turn.timestamp,
            )
            return False

    @staticmethod
    def _send_receive_offset(conn: socket.socket, turn: VoiceTurn) -> None:
        """Acknowledges a resumable byte boundary or completed DROP item."""
        if turn.delivery is Delivery.DROP and turn.finalized:
            conn.sendall(f'{TorCommand.ACK.value} {turn.msg_id}\n'.encode('ascii'))
            return
        conn.sendall(
            f'{TorCommand.VOICE_ACK.value} {turn.msg_id} {len(turn.data)}\n'.encode(
                'ascii'
            )
        )

    def receive_chunk(
        self, conn: socket.socket, onion: str, payload: dict[str, object]
    ) -> bool:
        """Validates, retains, streams, and acknowledges one inbound chunk.

        Args:
            conn (socket.socket): Authenticated LIVE socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded chunk envelope.

        Returns:
            bool: True when local resource policy requires disconnect.
        """
        msg_id = payload.get('id')
        offset = payload.get('offset')
        encoded = payload.get('data')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or type(offset) is not int
            or not isinstance(encoded, str)
        ):
            return True
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return True
        if not chunk or len(chunk) > Constants.VOICE_CHUNK_MAX_BYTES:
            return True
        with self._lock:
            turn = self._inbound.get((onion, msg_id))
            if turn is None or offset != len(turn.data):
                return True
            limit = self._limit()
            if limit >= 0 and self._used_bytes() + len(chunk) > limit:
                return True
            turn.data.extend(chunk)
            old_blob_id = turn.blob_id
            turn.blob_id = self._blobs.put(bytes(turn.data), BlobLifecycle.TEMPORARY)
            if not self._messages.update_inbound_voice_metadata(
                onion, msg_id, len(turn.data), self._metadata(turn)
            ):
                self._blobs.delete(turn.blob_id, BlobLifecycle.TEMPORARY)
                turn.blob_id = old_blob_id
                del turn.data[-len(chunk) :]
                return True
            self._blobs.delete(old_blob_id, BlobLifecycle.TEMPORARY)
            self._broadcast(
                VoiceChunkReceivedEvent(
                    alias=turn.alias,
                    onion=onion,
                    msg_id=msg_id,
                    offset=offset,
                    data=encoded,
                )
            )
            conn.sendall(
                f'{TorCommand.VOICE_ACK.value} {msg_id} {len(turn.data)}\n'.encode(
                    'ascii'
                )
            )
            return False

    def receive_end(
        self, conn: socket.socket, onion: str, payload: dict[str, object]
    ) -> bool:
        """Finalizes one inbound Voice item after exact size validation.

        Args:
            conn (socket.socket): Authenticated LIVE socket.
            onion (str): Authenticated peer identity.
            payload (dict[str, object]): Decoded final envelope.

        Returns:
            bool: True when the sequence is malformed.
        """
        msg_id = payload.get('id')
        size = payload.get('size')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or type(size) is not int
        ):
            return True
        with self._lock:
            turn = self._inbound.get((onion, msg_id))
            if turn is None or size != len(turn.data):
                return True
            turn.finalized = True
            self._messages.update_inbound_voice_metadata(
                onion, msg_id, len(turn.data), self._metadata(turn)
            )
            content = VoiceContent(
                blob_id=turn.blob_id,
                codec=turn.codec,
                size_bytes=len(turn.data),
                duration_ms=turn.duration_ms,
            )
            if turn.delivery is Delivery.DROP:
                self._blobs.promote(turn.blob_id)
                self._inbound.pop((onion, msg_id), None)
                self._notify_inbox(turn)
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('ascii'))
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
            return False

    def _notify_inbox(self, turn: VoiceTurn) -> None:
        """Emits content-free attached or detached unseen notification metadata."""
        if self._has_clients():
            self._broadcast(
                InboxNotificationEvent(alias=turn.alias, onion=turn.onion, count=1)
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

    @staticmethod
    def decode_wire_payload(encoded: str) -> Optional[dict[str, object]]:
        """Strictly decodes one small Voice wire envelope.

        Args:
            encoded (str): Base64 JSON envelope.

        Returns:
            Optional[dict[str, object]]: Decoded object or None.
        """
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > Constants.MAX_STREAM_BYTES:
                return None
            value = json.loads(raw.decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
