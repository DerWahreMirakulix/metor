"""Measures bounded production playback of a synthetic item larger than the replay cache.

This explicit stress probe uses the real PCM worker/cache and an indexed synthetic
SDK source plus counting output. It does not prove native audio or Core transport.
"""

import argparse
import base64
import json
from pathlib import Path
import time
import tracemalloc
from typing import cast

import psutil

from metor.client import MetorClient
from metor.core.api import Delivery, MessageDirectionCode, VoiceDataEvent
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime.playback.worker import PlaybackWorker
from metor.ui.gui.state.mailbox import Mailbox
from metor.ui.gui.state.media import MediaCache, PlaybackTarget


class IndexedSource:
    """Generates one bounded PCM range at its exact requested offset, without retaining a source."""

    def __init__(self, size: int) -> None:
        """Creates a synthetic outgoing source, which never needs inbound consumption.

        Args:
            size: Total finalized source bytes, exceeding optional replay capacity.
        Returns:
            None
        """
        self.size = size
        self.next_offset = 0
        self.maximum_read = 0
        self.reads = 0

    def get_voice_chunk(
        self,
        peer: str,
        msg_id: str,
        direction: MessageDirectionCode,
        offset: int,
        maximum: int,
        *,
        owner_token: str | None,
    ) -> VoiceDataEvent:
        """Requires strictly forward bounded requests and returns only their exact PCM bytes.

        Args:
            peer: Original synthetic peer.
            msg_id: Original message.
            direction: Outgoing retained LIVE direction.
            offset: Next unread byte.
            maximum: Public request limit.
            owner_token: No review lease is used by this finalized source.
        Returns:
            VoiceDataEvent: Exact synthetic public range DTO.
        """
        assert (
            peer == 'peer'
            and msg_id == 'large'
            and direction is MessageDirectionCode.OUT
        )
        assert offset == self.next_offset and owner_token is None
        assert 0 < maximum <= Constants.VOICE_CHUNK_MAX_BYTES
        payload = b'\x01\x00' * (min(maximum, self.size - offset) // 2)
        self.next_offset += len(payload)
        self.maximum_read = max(self.maximum_read, len(payload))
        self.reads += 1
        return VoiceDataEvent(
            'Peer',
            msg_id,
            direction,
            Delivery.LIVE,
            PcmVoice.CODEC,
            offset,
            self.next_offset,
            self.size,
            base64.b64encode(payload).decode('ascii'),
            self.next_offset == self.size,
            onion=peer,
        )


class CountingOutput:
    """Checks each complete PCM frame without retaining or emitting audio."""

    def __init__(self) -> None:
        """Creates only bounded output counters.

        Args:
            None
        Returns:
            None
        """
        self.bytes = 0
        self.maximum_frame = 0
        self.drains = 0

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Checks every byte and counts only accepted complete frames.

        Args:
            frame: Current complete PCM fragment.
            headset_confirmed: Explicit worker output policy.
        Returns:
            None
        """
        assert headset_confirmed and frame == b'\x01\x00' * (len(frame) // 2)
        assert len(frame) <= PcmVoice.FRAME_BYTES
        self.bytes += len(frame)
        self.maximum_frame = max(self.maximum_frame, len(frame))

    def stop_output(self) -> None:
        """Records a successful synthetic drain without opening an output device.

        Args:
            None
        Returns:
            None
        """
        self.drains += 1


def main() -> None:
    """Streams beyond cache capacity and reports measured working set and queue occupancy.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    source = IndexedSource(GuiLimits.MEDIA_CACHE_BYTES + GuiLimits.DECODE_BYTES)
    output, cache, mailbox = CountingOutput(), MediaCache(), Mailbox()
    target = PlaybackTarget(
        1, 'instance', 'epoch', 'peer', Delivery.LIVE, MessageDirectionCode.OUT, 'large'
    )
    worker = PlaybackWorker(
        cast(MetorClient, source), target, 1, output, mailbox, cache
    )
    process = psutil.Process()
    rss_before = process.memory_info().rss
    rss_peak, cache_peak, queue_peak = rss_before, 0, 0
    started = time.monotonic()
    tracemalloc.start()
    worker.start()
    while not worker.done.wait(0.01):
        rss_peak = max(rss_peak, process.memory_info().rss)
        with cache._lock:
            cache_peak = max(cache_peak, cache._bytes)
            assert cache._bytes <= GuiLimits.MEDIA_CACHE_BYTES
            assert (
                sum(len(items) for items in cache._items.values())
                <= GuiLimits.MEDIA_CACHE_BYTES // GuiLimits.MEDIA_CACHE_BLOCK_BYTES
            )
        with mailbox._lock:
            queue_peak = max(queue_peak, len(mailbox._records))
            assert mailbox._bytes <= GuiLimits.QUEUE_BYTES
        while mailbox.take() is not None:
            pass
        if time.monotonic() - started > 120:
            worker.stop()
            raise AssertionError('Bounded streaming did not complete')
    _current, allocated_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert worker.position == source.size == output.bytes
    assert output.drains and source.next_offset == source.size
    assert cache.read(target, 0, PcmVoice.FRAME_BYTES) is None
    assert not cache.released(target)
    assert not mailbox.overloaded
    result = {
        'kind': 'production PCM worker/cache; synthetic indexed SDK and counting output',
        'native_audio': False,
        'core_integration': False,
        'source_bytes': source.size,
        'output_bytes': output.bytes,
        'source_reads': source.reads,
        'maximum_read_bytes': source.maximum_read,
        'maximum_frame_bytes': output.maximum_frame,
        'cache_peak_sampled_bytes': cache_peak,
        'cache_limit_bytes': GuiLimits.MEDIA_CACHE_BYTES,
        'queue_peak_sampled_records': queue_peak,
        'python_allocations_peak_bytes': allocated_peak,
        'rss_before_bytes': rss_before,
        'rss_peak_sampled_bytes': rss_peak,
        'elapsed_seconds': time.monotonic() - started,
        'passed': True,
    }
    args.result.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
