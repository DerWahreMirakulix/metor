"""Finite PCM amplitude summaries with explicit unknown ranges and no listening semantics."""

import struct

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice


class PcmEnvelope:
    """Coarsens real sample peaks as duration grows while preserving a fixed metadata bound."""

    def __init__(self) -> None:
        """Creates empty amplitude bins with one capture frame per initial bin.

        Args:
            None
        Returns:
            None
        """
        self.stride = PcmVoice.FRAME_BYTES
        self.peaks: list[int | None] = [None] * GuiLimits.WAVEFORM_BINS

    def append(self, offset: int, payload: bytes) -> None:
        """Summarizes sample-aligned PCM without storing another copy of the recording.

        Args:
            offset: Absolute encoded byte position.
            payload: Validated little-endian signed PCM samples.
        Returns:
            None
        """
        if (
            offset < 0
            or offset % PcmVoice.SAMPLE_BYTES
            or len(payload) % PcmVoice.SAMPLE_BYTES
        ):
            return
        while offset + len(payload) > self.stride * GuiLimits.WAVEFORM_BINS:
            merged: list[int | None] = []
            for index in range(0, GuiLimits.WAVEFORM_BINS, 2):
                values = [
                    value
                    for value in self.peaks[index : index + 2]
                    if value is not None
                ]
                merged.append(max(values) if values else None)
            self.peaks = merged + [None] * (GuiLimits.WAVEFORM_BINS - len(merged))
            self.stride *= 2
        for index, (sample,) in enumerate(struct.iter_unpack('<h', payload)):
            bucket = (offset + index * PcmVoice.SAMPLE_BYTES) // self.stride
            previous = self.peaks[bucket]
            self.peaks[bucket] = max(previous or 0, abs(sample))

    def snapshot(self) -> tuple[int, tuple[int | None, ...]]:
        """Copies only fixed-size amplitude metadata for native rendering.

        Args:
            None
        Returns:
            tuple: Bytes per bin and peaks; None denotes unavailable sample data.
        """
        return self.stride, tuple(self.peaks)
