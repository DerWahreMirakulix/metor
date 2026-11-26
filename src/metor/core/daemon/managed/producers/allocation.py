"""Pre-write encrypted object allocation for connection-owned Voice capture."""

import secrets

from metor.data.blob import BLOB_ID_BYTES, BlobLifecycle, BlobStore
from metor.data.sql import VoiceProducerRepository


class ProducerBlobAllocator:
    """Journals owned object IDs before any bytes can reach the blob store."""

    def __init__(self, repository: VoiceProducerRepository, blobs: BlobStore) -> None:
        """Binds the SQL claim and encrypted object owners.

        Args:
            repository: Active profile producer journal.
            blobs: Active profile object store.
        Returns:
            None
        """
        self._repository = repository
        self._blobs = blobs

    def put(self, msg_id: str, payload: bytes) -> str:
        """Allocates one capture object with a durable pre-write claim.

        Args:
            msg_id: Recording identity supplied by the Core capture owner.
            payload: Already bounded anchor or encoded chunk.
        Returns:
            str: Newly stored opaque object ID.
        """
        item = self._repository.get(msg_id)
        if item is None:
            return self._blobs.put(payload, BlobLifecycle.TEMPORARY)
        blob_id = secrets.token_hex(BLOB_ID_BYTES)
        self._repository.reserve_blob(item, blob_id)
        self._blobs.put_with_id(blob_id, payload, BlobLifecycle.TEMPORARY)
        return blob_id
