"""Bounded, resumable Voice transfer over authenticated LIVE sessions."""

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

# Local Package Imports
from ..state import StateTracker
from ..router.admission import FrameAdmission
from ...notify import NotificationPayload
from .models import VoiceTurn
from .outbound import VoiceOutboundMixin

if TYPE_CHECKING:
    from metor.data.profile import Config


class VoiceTransferManager(VoiceOutboundMixin):
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
        transition_lock: Optional[threading.RLock] = None,
        purge_fence: Optional[threading.Event] = None,
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
            transition_lock (Optional[threading.RLock]): Shared identity transition lock.
            purge_fence (Optional[threading.Event]): Destructive lifecycle fence.

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
        self._lock = transition_lock or threading.RLock()
        self._purge_fence = purge_fence or threading.Event()
        self._outbound: dict[str, VoiceTurn] = {}
        self._inbound: dict[tuple[str, str], VoiceTurn] = {}
        self._reconcile_drop_ownership()
        self._hydrate_retained_turns()

    @staticmethod
    def _metadata_blob_ids(payload: str) -> Optional[tuple[str, ...]]:
        """Parses the complete segmented object inventory from Voice metadata."""
        try:
            metadata = json.loads(payload)
        except (TypeError, ValueError):
            return None
        if not isinstance(metadata, dict) or not isinstance(
            metadata.get('blob_id'), str
        ):
            return None
        raw_chunks = metadata.get('chunk_ids')
        if not isinstance(raw_chunks, list) or any(
            not isinstance(chunk_id, str) for chunk_id in raw_chunks
        ):
            return None
        return (str(metadata['blob_id']), *(str(item) for item in raw_chunks))

    def _reconcile_drop_ownership(self) -> None:
        """Completes interrupted temporary-to-persistent Voice promotions."""
        payloads = [
            row[3]
            for row in self._messages.get_pending_outbox()
            if row[2] == ContentType.VOICE.value
        ]
        payloads.extend(self._messages.get_voice_draft_payloads())
        payloads.extend(
            record.payload
            for record in self._messages.get_unread_inbound_voices()
            if record.delivery == Delivery.DROP.value
            and self._metadata_finalized(record.payload)
        )
        for payload in payloads:
            blob_ids = self._metadata_blob_ids(payload)
            if blob_ids is None:
                continue
            for blob_id in blob_ids:
                if self._blobs.exists(blob_id, BlobLifecycle.PERSISTENT):
                    continue
                if self._blobs.exists(blob_id, BlobLifecycle.TEMPORARY):
                    self._blobs.promote(blob_id)

    @staticmethod
    def _metadata_finalized(payload: str) -> bool:
        """Reports whether one Voice metadata document is finalized."""
        try:
            metadata = json.loads(payload)
        except (TypeError, ValueError):
            return False
        return isinstance(metadata, dict) and metadata.get('finalized') is True

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
        for inbound_record in self._messages.get_unread_inbound_voices():
            delivery = Delivery(inbound_record.delivery)
            if delivery is Delivery.DROP and self._metadata_finalized(
                inbound_record.payload
            ):
                continue
            turn = self._turn_from_metadata(
                inbound_record.peer_onion,
                inbound_record.msg_id,
                inbound_record.payload,
                inbound_record.timestamp,
                delivery,
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
            raw_chunk_ids = metadata.get('chunk_ids')
            if not isinstance(raw_chunk_ids, list) or any(
                not isinstance(chunk_id, str) for chunk_id in raw_chunk_ids
            ):
                return None
            chunk_ids = [str(chunk_id) for chunk_id in raw_chunk_ids]
            data = b''.join(
                self._blobs.read(chunk_id, lifecycle) for chunk_id in chunk_ids
            )
            if int(metadata.get('size_bytes', -1)) != len(data):
                return None
            duration = metadata.get('duration_ms')
            return VoiceTurn(
                alias=self._contacts.ensure_alias_for_onion(onion) or onion,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=str(metadata['codec']),
                blob_id=blob_id,
                chunk_ids=chunk_ids,
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
                'chunk_ids': turn.chunk_ids,
                'codec': turn.codec,
                'size_bytes': len(turn.data),
                'duration_ms': turn.duration_ms,
                'finalized': turn.finalized,
                'acknowledged_offset': turn.acknowledged_offset,
            },
            separators=(',', ':'),
        )

    @staticmethod
    def _blob_ids(turn: VoiceTurn) -> tuple[str, ...]:
        """Returns every object owned by one segmented Voice turn.

        Args:
            turn (VoiceTurn): Logical Voice turn.

        Returns:
            tuple[str, ...]: Manifest anchor followed by ordered chunks.
        """
        return (turn.blob_id, *turn.chunk_ids)

    def _delete_turn_blobs(self, turn: VoiceTurn, lifecycle: BlobLifecycle) -> None:
        """Deletes every segmented object owned by one Voice turn."""
        for blob_id in self._blob_ids(turn):
            self._blobs.delete(blob_id, lifecycle)

    def _promote_turn_blobs(self, turn: VoiceTurn) -> None:
        """Idempotently promotes every segmented Voice object."""
        for blob_id in self._blob_ids(turn):
            if self._blobs.exists(blob_id, BlobLifecycle.PERSISTENT):
                continue
            self._blobs.promote(blob_id)

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

    def dismiss_inbound(self, onion: str) -> None:
        """Shreds all retained inbound LIVE Voice payloads for one context."""
        if self._purge_fence.is_set():
            return
        with self._lock:
            if self._purge_fence.is_set():
                return
            keys = [
                key
                for key, turn in self._inbound.items()
                if key[0] == onion and turn.delivery is Delivery.LIVE
            ]
            for key in keys:
                turn = self._inbound.pop(key)
                self._delete_turn_blobs(turn, BlobLifecycle.TEMPORARY)

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
        timestamp = payload.get('timestamp')
        if (
            not isinstance(msg_id, str)
            or not is_valid_message_id(msg_id)
            or not isinstance(codec, str)
        ):
            return FrameAdmission.MALFORMED
        if not codec or len(codec) > Constants.VOICE_CODEC_MAX_CHARS:
            return FrameAdmission.MALFORMED
        with self._lock:
            if self._purge_fence.is_set():
                return FrameAdmission.PURGING
            if (onion, msg_id) in self._inbound:
                turn = self._inbound[(onion, msg_id)]
                if delivery is Delivery.DROP and turn.delivery is Delivery.LIVE:
                    turn.delivery = Delivery.DROP
                    if not self._messages.promote_inbound_voice_to_drop(
                        onion, msg_id, self._metadata(turn), len(turn.data)
                    ):
                        return FrameAdmission.MALFORMED
                    if turn.finalized:
                        self._promote_turn_blobs(turn)
                self._send_receive_offset(conn, turn)
                return FrameAdmission.ACCEPTED
            retained = self._messages.get_inbound_voice(onion, msg_id)
            if retained is not None:
                try:
                    metadata = json.loads(retained.payload)
                    if not isinstance(metadata, dict):
                        return FrameAdmission.MALFORMED
                    stored_delivery = Delivery(retained.delivery)
                    finalized = bool(metadata.get('finalized', False))
                    blob_id = str(metadata['blob_id'])
                    lifecycle = (
                        BlobLifecycle.PERSISTENT
                        if stored_delivery is Delivery.DROP and finalized
                        else BlobLifecycle.TEMPORARY
                    )
                    raw_chunk_ids = metadata.get('chunk_ids')
                    if not isinstance(raw_chunk_ids, list) or any(
                        not isinstance(chunk_id, str) for chunk_id in raw_chunk_ids
                    ):
                        return FrameAdmission.MALFORMED
                    chunk_ids = [str(chunk_id) for chunk_id in raw_chunk_ids]
                    retained_data = b''.join(
                        self._blobs.read(chunk_id, lifecycle) for chunk_id in chunk_ids
                    )
                    turn = VoiceTurn(
                        alias=self._contacts.ensure_alias_for_onion(onion) or onion,
                        onion=onion,
                        msg_id=msg_id,
                        delivery=stored_delivery,
                        codec=str(metadata['codec']),
                        blob_id=blob_id,
                        chunk_ids=chunk_ids,
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
                    return FrameAdmission.MALFORMED
                if delivery is Delivery.DROP and turn.delivery is Delivery.LIVE:
                    turn.delivery = Delivery.DROP
                    if not self._messages.promote_inbound_voice_to_drop(
                        onion, msg_id, self._metadata(turn), len(turn.data)
                    ):
                        return FrameAdmission.MALFORMED
                    if turn.finalized:
                        self._promote_turn_blobs(turn)
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
                blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
                turn = VoiceTurn(
                    alias=alias,
                    onion=onion,
                    msg_id=msg_id,
                    delivery=Delivery.DROP,
                    codec=codec,
                    blob_id=blob_id,
                    chunk_ids=[],
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
            blob_id = self._blobs.put(b'', BlobLifecycle.TEMPORARY)
            turn = VoiceTurn(
                alias=alias,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=codec,
                blob_id=blob_id,
                chunk_ids=[],
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
            f'{TorCommand.VOICE_ACK.value} {turn.msg_id} {len(turn.data)}\n'.encode(
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
            if turn is None or turn.finalized or offset > len(turn.data):
                return FrameAdmission.MALFORMED
            if offset < len(turn.data):
                duplicate_end = offset + len(chunk)
                if (
                    duplicate_end > len(turn.data)
                    or bytes(turn.data[offset:duplicate_end]) != chunk
                ):
                    return FrameAdmission.MALFORMED
            else:
                limit = self._limit()
                if limit >= 0 and self._used_bytes() + len(chunk) > limit:
                    return FrameAdmission.RESOURCE_LIMIT
                chunk_id = self._blobs.put(chunk, BlobLifecycle.TEMPORARY)
                turn.chunk_ids.append(chunk_id)
                turn.data.extend(chunk)
                if not self._messages.update_inbound_voice_metadata(
                    onion, msg_id, len(turn.data), self._metadata(turn)
                ):
                    self._blobs.delete(chunk_id, BlobLifecycle.TEMPORARY)
                    turn.chunk_ids.pop()
                    del turn.data[-len(chunk) :]
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
            next_offset = len(turn.data)
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
            or (duration_ms is not None and type(duration_ms) is not int)
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
                        self._state.send_frame(
                            conn,
                            f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode(
                                'ascii'
                            ),
                        )
                        return FrameAdmission.ACCEPTED
                return FrameAdmission.MALFORMED
            if turn.finalized:
                self._state.send_frame(
                    conn,
                    f'{TorCommand.VOICE_COMMIT_ACK.value} {msg_id}\n'.encode('ascii'),
                )
                return FrameAdmission.ACCEPTED
            if size != len(turn.data):
                return FrameAdmission.MALFORMED
            turn.duration_ms = duration_ms
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
                self._promote_turn_blobs(turn)
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
                    size_bytes=len(turn.data),
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
