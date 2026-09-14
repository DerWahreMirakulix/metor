"""Durable reclamation of disposable recordings and interrupted LIVE producers."""

import json
from typing import Callable

from metor.core.api import (
    Delivery,
    IpcEvent,
    MessageDirectionCode,
    MessageOperationReason,
    VoiceFinalizedEvent,
    VoiceOperationRejectedEvent,
)
from metor.data import MessageDirection, MessageManager, MessageStatus
from metor.data.blob import BlobLifecycle, BlobStore
from metor.data.sql import VoiceProducerItem, VoiceProducerRepository
from metor.utils import Constants


class ProducerCleanup:
    """Reconciles canonical receipts before any destructive staging cleanup."""

    def __init__(
        self,
        repository: VoiceProducerRepository,
        messages: MessageManager,
        blobs: BlobStore,
        cancel: Callable[[str, str], bool],
        finalize: Callable[[str, str], bool],
    ) -> None:
        """Binds cleanup to the active protected runtime.

        Args:
            repository: Durable claims and deletion journal.
            messages: Canonical receipt owner.
            blobs: Active encrypted object store.
            cancel: Existing exact DROP cancellation operation.
            finalize: Accepted-prefix LIVE finalization operation.
        Returns:
            None
        """
        self.repository = repository
        self._messages = messages
        self._blobs = blobs
        self._cancel = cancel
        self._finalize = finalize

    @staticmethod
    def _blob_ids(payload: str) -> tuple[str, ...]:
        """Validates the bounded canonical inventory before journaling deletion.

        Args:
            payload: Core-authored retained Voice metadata.
        Returns:
            tuple[str, ...]: Exact logical object identifiers.
        """
        if len(payload.encode('utf-8')) > Constants.VOICE_METADATA_MAX_BYTES:
            raise ValueError('Oversized Voice metadata')
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError('Invalid Voice metadata')
        anchor = value.get('blob_id')
        chunks = value.get('chunk_ids')
        if (
            not isinstance(anchor, str)
            or not anchor
            or not isinstance(chunks, list)
            or len(chunks) > Constants.VOICE_MAX_SEGMENTS
            or any(not isinstance(item, str) or not item for item in chunks)
        ):
            raise ValueError('Invalid Voice object inventory')
        return (anchor, *chunks)

    def reclaim(self, item: VoiceProducerItem) -> bool:
        """Reclaims a draft or freezes LIVE without guessing uncertain outcomes.

        Args:
            item: Durable claim belonging to a revoked producer.
        Returns:
            bool: True only after ownership transfer or complete cleanup.
        """
        record = self._messages.get_voice_payload(
            item.onion, item.msg_id, MessageDirection.OUT
        )
        if item.delivery is Delivery.LIVE:
            self.repository.mark_interrupted(item)
            if record is not None and not self._finalize(item.onion, item.msg_id):
                return False
            self.release_transferred(item)
            return True
        payload = item.cleanup_payload
        if record is not None:
            if record.status != MessageStatus.DRAFT.value:
                # A committed receipt wins over a lost Commit response.
                self.release_transferred(item)
                return True
            if record.delivery != Delivery.DROP.value:
                return False
            payload = record.payload
            self._blob_ids(payload)
            self.repository.prepare_cleanup(item, payload)
            self._cancel(item.onion, item.msg_id)
            if (
                self._messages.get_voice_payload(
                    item.onion, item.msg_id, MessageDirection.OUT
                )
                is not None
            ):
                return False
        blob_ids = set(item.allocated_ids)
        if payload is not None:
            blob_ids.update(self._blob_ids(payload))
        self._delete_objects(blob_ids)
        self.repository.release(item)
        return True

    def release_transferred(self, item: VoiceProducerItem) -> None:
        """Reclaims only unaccepted allocation debris before transferring ownership.

        Args:
            item: Claim whose canonical data belongs to normal delivery retention.
        Returns:
            None
        """
        record = self._messages.get_voice_payload(
            item.onion, item.msg_id, MessageDirection.OUT
        )
        retained = set(self._blob_ids(record.payload)) if record is not None else set()
        self._delete_objects(set(item.allocated_ids) - retained)
        self.repository.release(item)

    def has_receipt(self, item: VoiceProducerItem) -> bool:
        """Checks actual admission without converting unavailable storage into absence.

        Args:
            item: Fresh recording reservation.
        Returns:
            bool: Whether canonical Voice metadata exists.
        """
        return (
            self._messages.get_voice_payload(
                item.onion, item.msg_id, MessageDirection.OUT
            )
            is not None
        )

    def _delete_objects(self, blob_ids: set[str]) -> None:
        """Deletes exact IDs in both possible promotion classes idempotently.

        Args:
            blob_ids: Core-owned bounded object inventory.
        Returns:
            None
        """
        for blob_id in blob_ids:
            self._blobs.delete(blob_id, BlobLifecycle.TEMPORARY)
            self._blobs.delete(blob_id, BlobLifecycle.PERSISTENT)

    def finalization_result(self, item: VoiceProducerItem) -> IpcEvent:
        """Projects confirmed finalization for an explicit recovery request.

        Args:
            item: Exact interrupted recording identity.
        Returns:
            IpcEvent: Canonical finalization or a typed unavailable result.
        """
        record = self._messages.get_voice_payload(
            item.onion, item.msg_id, MessageDirection.OUT
        )
        if record is None:
            return VoiceOperationRejectedEvent(
                msg_id=item.msg_id, reason=MessageOperationReason.NOT_FOUND
            )
        metadata = json.loads(record.payload)
        if not isinstance(metadata, dict) or metadata.get('finalized') is not True:
            return VoiceOperationRejectedEvent(
                msg_id=item.msg_id, reason=MessageOperationReason.PERSISTENCE_FAILED
            )
        return VoiceFinalizedEvent(
            msg_id=item.msg_id,
            onion=item.onion,
            direction=MessageDirectionCode.OUT,
            delivery=Delivery(record.delivery),
            size_bytes=metadata['size_bytes'],
            duration_ms=metadata.get('duration_ms'),
        )

    def transferred(self, item: VoiceProducerItem) -> bool:
        """Reconciles successful commit/finalize without cancelling pending bytes.

        Args:
            item: Current producer claim after a domain operation.
        Returns:
            bool: Whether canonical state no longer needs producer ownership.
        """
        record = self._messages.get_voice_payload(
            item.onion, item.msg_id, MessageDirection.OUT
        )
        if record is None:
            return False
        if item.delivery is Delivery.DROP:
            return record.status != MessageStatus.DRAFT.value
        metadata = json.loads(record.payload)
        return isinstance(metadata, dict) and metadata.get('finalized') is True
