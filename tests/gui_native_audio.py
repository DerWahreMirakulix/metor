"""Runs an explicitly selected headset duplex probe without retaining microphone data.

This probe emits one quiet test tone and records only timing/count diagnostics.
It does not verify echo cancellation, intelligibility, GUI PTT or Core staging.
"""

import argparse
import json
import math
from pathlib import Path
import platform
import struct
import time

import sounddevice

from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice


FRAME_COUNT: int = 50
TONE_HZ: int = 440
TONE_AMPLITUDE: int = 655


def main() -> None:
    """Exercises one admitted native input/output pair concurrently.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-device', type=int, required=True)
    parser.add_argument('--output-device', type=int, required=True)
    parser.add_argument('--headset-confirmed', action='store_true', required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    capture_info = sounddevice.query_devices(args.input_device)
    output_info = sounddevice.query_devices(args.output_device)
    audio = HeadsetAudio(args.input_device, args.output_device)
    received = 0
    submitted = 0
    started = time.monotonic()
    try:
        audio.start_capture(headset_confirmed=args.headset_confirmed)
        for frame_index in range(FRAME_COUNT):
            samples = [
                round(
                    TONE_AMPLITUDE
                    * math.sin(
                        2
                        * math.pi
                        * TONE_HZ
                        * (frame_index * PcmVoice.FRAME_SAMPLES + offset)
                        / PcmVoice.SAMPLE_RATE
                    )
                )
                for offset in range(PcmVoice.FRAME_SAMPLES)
            ]
            frame = struct.pack('<' + 'h' * PcmVoice.FRAME_SAMPLES, *samples)
            audio.play_frame(frame, headset_confirmed=args.headset_confirmed)
            submitted += len(frame)
            while captured := audio.take_frame():
                PcmVoice.validate(captured)
                received += len(captured)
                captured = b''
        assert not audio.failed, 'Native capture overflowed or failed'
        assert received > 0, 'No native capture frames arrived during output'
    finally:
        audio.stop()
    result = {
        'kind': 'native headset port, simultaneous capture and quiet test-tone output',
        'system': platform.system(),
        'python': platform.python_version(),
        'input': capture_info['name'],
        'output': output_info['name'],
        'captured_bytes_discarded': received,
        'output_bytes': submitted,
        'output_encoded_ms': PcmVoice.duration_ms(submitted),
        'elapsed_seconds': time.monotonic() - started,
        'microphone_payload_retained': False,
        'gui_ptt_or_core_staging': False,
        'aec_or_acoustic_quality_verified': False,
    }
    args.result.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('NATIVE_HEADSET_DUPLEX_PORT_OK')


if __name__ == '__main__':
    main()
