"""Bounded, resumable Voice transfer over authenticated LIVE sessions."""

import base64
import binascii
from datetime import datetime, timezone
import json
import threading
from typing import TYPE_CHECKING, Callable, Optional

from metor.core.api import (
    ContentType,
    Delivery,
    IpcEvent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    ContactManager,
    MessageDirection,
    MessageManager,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants

# Local Package Imports
from ..state import StateTracker
from ...notify import NotificationPayload
from .inbound import VoiceInboundMixin
from .models import VoiceTurn
from .outbound import VoiceOutboundMixin

if TYPE_CHECKING:
    from metor.data.profile import Config


class VoiceTransferManager(VoiceInboundMixin, VoiceOutboundMixin):
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

    def context_token(self, onion: str, msg_id: str, direction: str) -> int | None:
        """Returns immutable runtime provenance of a LIVE recording.

        Args:
            onion (str): Exact peer owner.
            msg_id (str): Exact recording identity.
            direction (str): Inbound or outbound ownership.

        Returns:
            int | None: Admission context; restored or unrelated media has no grant.
        """
        with self._lock:
            turn = (
                self._inbound.get((onion, msg_id))
                if direction == 'in'
                else self._outbound.get(msg_id)
            )
            if (
                turn is None
                or turn.onion != onion
                or turn.delivery is not Delivery.LIVE
            ):
                return None
            return turn.context_generation

    def _reconcile_drop_ownership(self) -> None:
        """Completes interrupted temporary-to-persistent Voice promotions."""
        payloads = [
            row[3]
            for row in self._messages.get_pending_outbox()
            if row[2] == ContentType.VOICE.value
        ]
        payloads.extend(
            payload
            for payload in self._messages.get_voice_draft_payloads()
            if self._metadata_finalized(payload)
        )
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

    def finalize_interrupted(self, onion: str, msg_id: str) -> bool:
        """Freezes a vanished LIVE producer at its durable accepted prefix.

        Args:
            onion: Canonical owner peer.
            msg_id: Exact outbound identity whose producer lease was revoked.
        Returns:
            bool: Whether canonical finalization is confirmed; failures remain retryable.
        """
        if self._purge_fence.is_set():
            return False
        with self._lock:
            record = self._messages.get_voice_payload(
                onion, msg_id, MessageDirection.OUT
            )
            if record is None:
                return True
            if self._metadata_finalized(record.payload):
                return True
            # A failed append may have evicted RAM state while SQL retained its prefix.
            turn = self._outbound.get(msg_id)
            if turn is None:
                turn = self._turn_from_metadata(
                    onion,
                    msg_id,
                    record.payload,
                    datetime.now(timezone.utc).isoformat(),
                    Delivery(record.delivery),
                    BlobLifecycle.TEMPORARY,
                )
                if turn is None:
                    return False
                self._outbound[msg_id] = turn
            if turn.onion != onion:
                return False
        self.finalize(msg_id, turn.duration_ms)
        canonical = self._messages.get_voice_payload(
            onion, msg_id, MessageDirection.OUT
        )
        return canonical is None or self._metadata_finalized(canonical.payload)

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
        if len(payload.encode('utf-8')) > Constants.VOICE_METADATA_MAX_BYTES:
            return None
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
            if len(chunk_ids) > Constants.VOICE_MAX_SEGMENTS:
                return None
            chunk_sizes: list[int] = []
            actual_size = 0
            for chunk_id in chunk_ids:
                chunk_size = len(self._blobs.read(chunk_id, lifecycle))
                if not 0 < chunk_size <= Constants.VOICE_CHUNK_MAX_BYTES:
                    return None
                chunk_sizes.append(chunk_size)
                actual_size += chunk_size
                if actual_size > Constants.VOICE_TURN_HARD_MAX_BYTES:
                    return None
            serialized_size = metadata.get('size_bytes')
            if type(serialized_size) is not int or serialized_size != actual_size:
                return None
            serialized_sizes = metadata.get('chunk_sizes')
            if serialized_sizes is not None:
                if (
                    not isinstance(serialized_sizes, list)
                    or any(type(size) is not int for size in serialized_sizes)
                    or serialized_sizes != chunk_sizes
                ):
                    return None
            codec = metadata.get('codec')
            if (
                not isinstance(codec, str)
                or not codec
                or len(codec) > Constants.VOICE_CODEC_MAX_CHARS
            ):
                return None
            duration = metadata.get('duration_ms')
            if duration is not None and (type(duration) is not int or duration < 0):
                return None
            acknowledged_offset = metadata.get('acknowledged_offset', 0)
            if (
                type(acknowledged_offset) is not int
                or not 0 <= acknowledged_offset <= actual_size
            ):
                return None
            return VoiceTurn(
                alias=self._contacts.ensure_alias_for_onion(onion) or onion,
                onion=onion,
                msg_id=msg_id,
                delivery=delivery,
                codec=codec,
                blob_id=blob_id,
                chunk_ids=chunk_ids,
                chunk_sizes=chunk_sizes,
                data=bytearray(),
                timestamp=timestamp,
                size_bytes=actual_size,
                duration_ms=int(duration) if duration is not None else None,
                finalized=bool(metadata.get('finalized', False)),
                fallback_committed=metadata.get('fallback_committed') is True,
                acknowledged_offset=acknowledged_offset,
            )
        except (KeyError, TypeError, ValueError, OSError):
            return None

    def _canonical_inbound_metadata(self, turn: VoiceTurn) -> bool | None:
        """Resolves ambiguous writes before rollback; unavailable is not absent."""
        try:
            record = self._messages.get_inbound_voice(turn.onion, turn.msg_id)
            return record is not None and json.loads(record.payload) == json.loads(
                self._metadata(turn)
            )
        except Exception:
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
                'chunk_sizes': turn.chunk_sizes,
                'codec': turn.codec,
                'size_bytes': turn.size_bytes,
                'duration_ms': turn.duration_ms,
                'finalized': turn.finalized,
                'fallback_committed': turn.fallback_committed,
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

    def inbound_delivery(self, onion: str, msg_id: str) -> Optional[Delivery]:
        """Returns retained delivery semantics for an exact inbound identity.

        Args:
            onion (str): Stable peer identity.
            msg_id (str): Stable Voice identity.

        Returns:
            Optional[Delivery]: Retained delivery semantics, if present.
        """
        with self._lock:
            turn = self._inbound.get((onion, msg_id))
            if turn is not None:
                return turn.delivery
        record = self._messages.get_inbound_voice(onion, msg_id)
        if record is None:
            return None
        try:
            return Delivery(record.delivery)
        except ValueError:
            return None

    def _used_bytes(self) -> int:
        """Returns current local and inbound in-memory Voice retention.

        Args:
            None

        Returns:
            int: Retained Voice bytes.
        """
        return sum(turn.size_bytes for turn in self._outbound.values()) + sum(
            turn.size_bytes for turn in self._inbound.values()
        )

    def _read_turn_range(
        self,
        turn: VoiceTurn,
        offset: int,
        max_bytes: int,
        lifecycle: BlobLifecycle = BlobLifecycle.TEMPORARY,
    ) -> bytes:
        """Reads an indexed bounded range without decrypting its prefix."""
        if offset < 0 or max_bytes < 0 or offset > turn.size_bytes:
            raise ValueError('Invalid Voice range.')
        remaining = max_bytes
        position = 0
        selected = bytearray()
        for chunk_id, chunk_size in zip(turn.chunk_ids, turn.chunk_sizes, strict=True):
            chunk_end = position + chunk_size
            if offset >= chunk_end:
                position = chunk_end
                continue
            chunk = self._blobs.read(chunk_id, lifecycle)
            if len(chunk) != chunk_size:
                raise ValueError('Voice segment size changed.')
            start = max(0, offset - position)
            portion = chunk[start : start + remaining]
            selected.extend(portion)
            remaining -= len(portion)
            position = chunk_end
            if remaining == 0:
                break
        return bytes(selected)

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
