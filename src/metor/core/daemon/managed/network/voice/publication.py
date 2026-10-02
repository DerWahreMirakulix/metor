"""Explicit Voice draft publication and generation-fenced peer emission."""

import socket
from typing import TYPE_CHECKING

from metor.core.api import Delivery
from metor.core.daemon.managed.models import TorCommand
from metor.data import MessageDirection, MessageStatus, SettingKey
from metor.data.blob import BlobLifecycle

# Local Package Imports
from .capture import VoiceCaptureMixin
from .models import VoiceTurn


class VoicePublicationMixin(VoiceCaptureMixin):
    """Transfers staged messages into delivery only after a confirmed Send."""

    if TYPE_CHECKING:

        def _turn_from_metadata(
            self,
            onion: str,
            msg_id: str,
            payload: str,
            timestamp: str,
            delivery: Delivery,
            lifecycle: BlobLifecycle,
        ) -> VoiceTurn | None:
            """Rehydrates an authenticated local draft or retained message."""
            ...

        @staticmethod
        def _metadata_blob_ids(payload: str) -> tuple[str, ...] | None:
            """Returns the complete bounded canonical object inventory."""
            ...

        def _promote_turn_blobs(self, turn: VoiceTurn) -> None:
            """Idempotently promotes confirmed DROP publication objects."""
            ...

        @staticmethod
        def _wire(command: TorCommand, payload: dict[str, object]) -> bytes:
            """Serializes one bounded authenticated-session Voice frame."""
            ...

    def _send_begin(self, turn: VoiceTurn) -> None:
        """Starts transport only for an explicitly published LIVE message."""
        conn = self._state.get_connection(turn.onion)
        if conn is None or turn.delivery is not Delivery.LIVE or not turn.published:
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
        self,
        turn: VoiceTurn,
        conn: socket.socket,
        payload: bytes,
    ) -> None:
        """Claims current publication authority immediately before socket emission."""
        generation = self._state.get_live_generation(turn.onion, turn.msg_id)
        if generation is None or not turn.published:
            raise ConnectionError('LIVE publication authority has been revoked.')

        def claim() -> bool:
            """Fences stale delivery, purge and fallback writers."""
            with self._lock:
                return (
                    not self._purge_fence.is_set()
                    and turn.published
                    and turn.delivery is Delivery.LIVE
                    and self._state.is_live_generation(
                        turn.onion, turn.msg_id, generation
                    )
                )

        self._state.send_frame(conn, payload, claim)

    def commit_draft(
        self,
        target: str,
        msg_id: str,
        delivery: Delivery | None = None,
        context_generation: int | None = None,
    ) -> bool:
        """Publishes one finalized draft under its exact identity and target.

        Args:
            target: Immutable recording target, resolved again by Core.
            msg_id: Stable staging and publication identity.
            delivery: Omitted preserves mode; DROP explicitly converts a LIVE draft.
            context_generation: Optional explicit current LIVE assertion.
        Returns:
            bool: Confirmed canonical publication, including a repeated request.
        """
        if self._purge_fence.is_set():
            return False
        turn: VoiceTurn | None = None
        with self._lock:
            if self._purge_fence.is_set():
                return False
            resolved = self._contacts.resolve_target(target)
            if resolved is None:
                return False
            onion = resolved[1]
            record = self._messages.get_voice_payload(
                onion, msg_id, MessageDirection.OUT
            )
            if record is None:
                # Delivered ephemeral content may be gone while its receipt is retained.
                return self._messages.commit_voice_draft(onion, msg_id, delivery)
            selected = delivery if delivery is not None else Delivery(record.delivery)
            if record.status != MessageStatus.DRAFT.value:
                return self._messages.commit_voice_draft(onion, msg_id, selected)
            turn = self._outbound.get(msg_id)
            if turn is None:
                turn = self._turn_from_metadata(
                    onion,
                    msg_id,
                    record.payload,
                    next(
                        (
                            item.timestamp
                            for item in self._messages.get_voice_drafts()
                            if item.msg_id == msg_id and item.peer_onion == onion
                        ),
                        '',
                    ),
                    Delivery(record.delivery),
                    BlobLifecycle.TEMPORARY,
                )
            if (
                turn is None
                or turn.onion != onion
                or not turn.finalized
                or turn.size_bytes == 0
            ):
                return False
            if selected is Delivery.LIVE:
                current = self._state.get_live_media_generation(onion)
                if (
                    turn.delivery is not Delivery.LIVE
                    or current is None
                    or current != turn.context_generation
                    or (
                        context_generation is not None and context_generation != current
                    )
                    or self._state.get_connection(onion) is None
                ):
                    return False
            elif turn.delivery is Delivery.LIVE and not self._config.get_bool(
                SettingKey.ALLOW_DROPS
            ):
                return False
            if selected is Delivery.DROP:
                # Promotion precedes the durable publication: outbox never observes
                # a pending receipt whose bytes are still only temporary.
                self._promote_turn_blobs(turn)
            committed = False
            try:
                committed = self._messages.commit_voice_draft(
                    onion,
                    msg_id,
                    selected,
                    self._config.get_int(SettingKey.MAX_PENDING_LIVE_MSGS),
                    self._config.get_int(SettingKey.MAX_PENDING_LIVE_BYTES),
                )
            except Exception:
                canonical = self._messages.get_voice_payload(
                    onion, msg_id, MessageDirection.OUT
                )
                committed = (
                    canonical is not None
                    and canonical.delivery == selected.value
                    and canonical.status != MessageStatus.DRAFT.value
                )
            if not committed:
                return False
            turn.delivery, turn.published = selected, True
            if selected is Delivery.DROP:
                self._outbound.pop(msg_id, None)
            else:
                self._outbound[msg_id] = turn
                self._state.add_unacked_message(
                    onion, msg_id, self._metadata(turn), turn.timestamp
                )
        if turn.delivery is Delivery.LIVE:
            self._send_begin(turn)
        return True

    def cancel_draft(self, target: str, msg_id: str) -> bool:
        """Discards an unpublished draft in either mode without delivery effects."""
        if self._purge_fence.is_set():
            return False
        with self._lock:
            if self._purge_fence.is_set():
                return False
            resolved = self._contacts.resolve_target(target)
            if resolved is None:
                return False
            payload = self._messages.cancel_voice_draft(resolved[1], msg_id)
            if payload is None:
                return False
            self._outbound.pop(msg_id, None)
        blob_ids = self._metadata_blob_ids(payload)
        if blob_ids is None:
            return False
        for blob_id in blob_ids:
            self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
            self._blobs.delete(blob_id, BlobLifecycle.PERSISTENT)
        return True
