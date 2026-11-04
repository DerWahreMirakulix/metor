"""One bounded new-DROP upload; uncertain appends or commits are never repeated here."""

import base64
import threading

from metor.client import MetorClient, MetorRequestRejectedError
from metor.core.api import (
    Delivery,
    DropQueuedEvent,
    IpcEvent,
    SendMessageCommand,
    TextContent,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
)
from metor.shared import Constants
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.media import MediaCache

# Local Package Imports
from .source import ResendSource


class ResendWorker:
    """Pins a complete bounded source and owns one new message identity through upload."""

    def __init__(
        self,
        client: MetorClient,
        source: ResendSource,
        msg_id: str,
        owner: str | None,
        cache: MediaCache,
    ) -> None:
        """Captures immutable target and connection; no view lookup occurs during upload.

        Args:
            client: Original authenticated SDK connection.
            source: Complete source selected by the explicit user action.
            msg_id: Fresh DROP identity retained across outcome uncertainty.
            owner: Current staging owner for Voice, or None for text.
            cache: Shared finite volatile encoded source cache.
        Returns:
            None
        """
        self.client, self.source, self.msg_id, self.owner = (
            client,
            source,
            msg_id,
            owner,
        )
        self.cache = cache
        self.cancelled = threading.Event()
        self.phase = 'source'
        self.rejected = False
        self.begun = False

    def run(self) -> IpcEvent | None:
        """Runs one exact send intent without retrying any state-changing request.

        Args:
            None
        Returns:
            IpcEvent | None: Actual positive or typed refused result; None remains unknown.
        """
        try:
            if self.cancelled.is_set():
                return None
            if self.source.text is not None:
                self.phase = 'send'
                return self.client.request(
                    SendMessageCommand(
                        self.source.target.peer,
                        Delivery.DROP,
                        TextContent(self.source.text),
                        self.msg_id,
                    ),
                    DropQueuedEvent,
                )
            with self.cache.retain(self.source.target) as retained:
                if (
                    not retained
                    or self.cache.complete_size(self.source.target) != self.source.size
                ):
                    return None
                return self._voice()
        except MetorRequestRejectedError as exc:
            self.rejected = True
            return exc.event

    def _voice(self) -> IpcEvent | None:
        """Copies complete encoded chunks into a distinct owned draft, then finalizes and commits once.

        Args:
            None
        Returns:
            IpcEvent | None: Actual final result; an incomplete copy is never committed.
        """
        peer = self.source.target.peer
        if self.cancelled.is_set():
            return None
        self.phase = 'begin'
        started = self.client.begin_voice(
            peer, Delivery.DROP, self.msg_id, PcmVoice.CODEC, owner_token=self.owner
        )
        if (
            started is None
            or started.msg_id != self.msg_id
            or started.onion != peer
            or started.delivery is not Delivery.DROP
        ):
            return None
        self.begun = True
        offset = 0
        while offset < self.source.size:
            if self.cancelled.is_set():
                return None
            source = self.cache.read(
                self.source.target, offset, Constants.VOICE_CHUNK_MAX_BYTES
            )
            if source is None or source[1] != self.source.size or not source[0]:
                return None
            payload = source[0]
            PcmVoice.validate(payload, final=True)
            self.phase = 'append'
            result = self.client.append_voice(
                self.msg_id,
                offset,
                base64.b64encode(payload).decode('ascii'),
                owner_token=self.owner,
            )
            if (
                not isinstance(result, VoiceChunkAcceptedEvent)
                or result.msg_id != self.msg_id
                or result.next_offset != offset + len(payload)
            ):
                return result
            offset = result.next_offset
        if self.cancelled.is_set():
            return None
        self.phase = 'finalize'
        final = self.client.finalize_voice(
            self.msg_id, PcmVoice.duration_ms(self.source.size), owner_token=self.owner
        )
        if (
            not isinstance(final, VoiceFinalizedEvent)
            or final.msg_id != self.msg_id
            or final.onion != peer
            or final.delivery is not Delivery.DROP
            or final.size_bytes != self.source.size
        ):
            return None
        if self.cancelled.is_set():
            return None
        self.phase = 'commit'
        return self.client.commit_voice(peer, self.msg_id, owner_token=self.owner)
