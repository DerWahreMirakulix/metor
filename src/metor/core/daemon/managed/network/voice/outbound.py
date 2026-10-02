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
    VoiceOperationRejectedEvent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    MessageStatus,
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
                if (
                    turn.onion != onion
                    or turn.delivery is not Delivery.LIVE
                    or not turn.published
                ):
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
            if turn is None or turn.onion != onion or not turn.published:
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
                or not turn.published
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
