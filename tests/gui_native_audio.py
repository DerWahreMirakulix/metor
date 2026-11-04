"""Runs an explicitly selected headset duplex probe without retaining microphone data.

This probe emits one quiet test tone and records only timing/count diagnostics.
It does not verify echo cancellation, intelligibility, GUI PTT or Core staging.
"""

# ruff: noqa: E402

import argparse
import json
import math
from pathlib import Path
import platform
import struct
import sys
import time

CHECKOUT = Path(__file__).resolve().parents[1]
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument('--mode', choices=('source', 'installed'), required=True)
bootstrap_args, _bootstrap_unknown = bootstrap.parse_known_args()
if bootstrap_args.mode == 'source':
    sys.path.insert(0, str(CHECKOUT / 'src'))

import sounddevice

from gui_native_route import (  # type: ignore[import-not-found]
    select_audio_route,
    verify_gui_module_origin,
)
from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice


FRAME_COUNT: int = 50
TONE_HZ: int = 440
TONE_AMPLITUDE: int = 655


def _validate_format(input_index: int, output_index: int) -> None:
    """Checks the production PCM format on both selected backend directions."""
    sounddevice.check_input_settings(
        device=input_index,
        samplerate=PcmVoice.SAMPLE_RATE,
        channels=PcmVoice.CHANNELS,
        dtype='int16',
    )
    sounddevice.check_output_settings(
        device=output_index,
        samplerate=PcmVoice.SAMPLE_RATE,
        channels=PcmVoice.CHANNELS,
        dtype='int16',
    )


def main() -> None:
    """Exercises one admitted native input/output pair concurrently.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('source', 'installed'), required=True)
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--input-device', type=int)
    parser.add_argument('--output-device', type=int)
    parser.add_argument('--headset-confirmed', action='store_true')
    parser.add_argument('--result', type=Path)
    parser.add_argument('--revision')
    args = parser.parse_args()
    endpoints = HeadsetAudio.endpoints()
    if args.list_devices:
        print(json.dumps([endpoint.__dict__ for endpoint in endpoints], indent=2))
        return
    if (
        args.input_device is None
        or args.output_device is None
        or args.result is None
        or not args.revision
    ):
        parser.error(
            'a probe requires --input-device, --output-device, --result and --revision'
        )
    route = select_audio_route(
        endpoints,
        args.input_device,
        args.output_device,
        headset_confirmed=args.headset_confirmed,
        validate_format=_validate_format,
    )
    module_file = sys.modules[HeadsetAudio.__module__].__file__
    assert module_file is not None
    verify_gui_module_origin(
        module_file,
        mode=args.mode,
        checkout=CHECKOUT,
        environment_root=Path(sys.prefix),
    )
    capture_info = sounddevice.query_devices(route.source.index)
    output_info = sounddevice.query_devices(route.sink.index)
    hostapis = sounddevice.query_hostapis()
    audio = HeadsetAudio(route.source.index, route.sink.index)
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
        'revision_or_artifact': args.revision,
        'mode': args.mode,
        'system': platform.system(),
        'python': platform.python_version(),
        'input_device': route.source.index,
        'output_device': route.sink.index,
        'input_backend': hostapis[capture_info['hostapi']]['name'],
        'output_backend': hostapis[output_info['hostapi']]['name'],
        'input_channels_available': capture_info['max_input_channels'],
        'output_channels_available': output_info['max_output_channels'],
        'codec': PcmVoice.CODEC,
        'captured_bytes_discarded': received,
        'output_bytes': submitted,
        'output_encoded_ms': PcmVoice.duration_ms(submitted),
        'elapsed_seconds': time.monotonic() - started,
        'microphone_payload_retained': False,
        'gui_ptt_or_core_staging': False,
        'aec_or_acoustic_quality_verified': False,
        'module_origin_verified': True,
        'test_frame_count': FRAME_COUNT,
    }
    args.result.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('NATIVE_HEADSET_DUPLEX_PORT_OK')


if __name__ == '__main__':
    main()
