"""Explicitly authorized native GUI PTT/review probe with temporary encrypted Core data.

The input event is synthetic; capture, output, native widgets, SDK, IPC and storage
are real. No audio is exported. This is not physical-key, AEC or acoustic-quality proof.
"""

# ruff: noqa: E402

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import platform
import sys
import time
from unittest.mock import Mock

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
CHECKOUT = Path(__file__).resolve().parents[1]
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument('--mode', choices=('source', 'installed'), required=True)
bootstrap_args, _bootstrap_unknown = bootstrap.parse_known_args()
if bootstrap_args.mode == 'source':
    sys.path.insert(0, str(CHECKOUT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sounddevice

from gui_native_route import (  # type: ignore[import-not-found]
    select_audio_route,
    verify_gui_module_origin,
)
from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice

if '--list-devices' in sys.argv:
    print(
        json.dumps(
            [endpoint.__dict__ for endpoint in HeadsetAudio.endpoints()], indent=2
        )
    )
    raise SystemExit(0)

from kivy.clock import Clock
from kivy.core.window import Window
import psutil

import test_gui_producers as support  # type: ignore[import-not-found]
from metor.client import FrontendLaunchContext
from metor.client.platform import OutputPort
from metor.core.api import Delivery, MessageDirectionCode
from metor.data.message import MessageDirection
from metor.ui.gui.app import MetorApp
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.state import Route
from metor.ui.gui.views.peer import PeerView


RECORD_SECONDS: float = 1.0
PROBE_DEADLINE_SECONDS: float = 40.0
POLL_SECONDS: float = 0.05


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


class ObservedNativeOutput:
    """Delegates every byte to the real device while recording capture overlap."""

    def __init__(self, output: OutputPort, capture_running: Callable[[], bool]) -> None:
        """Bind the selected production output and a read-only capture predicate."""
        self.output = output
        self.capture_running = capture_running
        self.overlap = False

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Observe worker concurrency immediately before the real PortAudio write."""
        self.overlap = self.overlap or bool(self.capture_running())
        self.output.play_frame(frame, headset_confirmed=headset_confirmed)

    def stop_output(self) -> None:
        """Delegate the real drain/close boundary unchanged."""
        self.output.stop_output()


def main() -> None:
    """Exercises one brief deliberate PTT/review cycle on an explicit route.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('source', 'installed'), required=True)
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--input-device', type=int, required=True)
    parser.add_argument('--output-device', type=int, required=True)
    parser.add_argument('--headset-confirmed', action='store_true')
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    route = select_audio_route(
        HeadsetAudio.endpoints(),
        args.input_device,
        args.output_device,
        headset_confirmed=args.headset_confirmed,
        validate_format=_validate_format,
    )
    source, sink = route.source, route.sink
    module_file = sys.modules[MetorApp.__module__].__file__
    assert module_file is not None
    verify_gui_module_origin(
        module_file,
        mode=args.mode,
        checkout=CHECKOUT,
        environment_root=Path(sys.prefix),
    )
    input_info = sounddevice.query_devices(source.index)
    output_info = sounddevice.query_devices(sink.index)
    hostapis = sounddevice.query_hostapis()
    fixture = support.GuiProducerTests()
    app: MetorApp | None = None
    try:
        fixture.setUp()
        app = MetorApp(
            FrontendLaunchContext('voice-owned', Mock()),
            DeviceConfiguration(mode='desktop', width_px=480, height_px=800),
        )
        gui = app.controller
        gui.client = fixture.client
        gui.state.snapshot = fixture.client.runtime_snapshot()
        gui.state.capabilities = frozenset(fixture.client.init_event.capabilities)
        gui.state.covered = False
        gui.state.route = Route('V08', fixture.onion, Delivery.DROP)
        gui.voice_owner.token = fixture.owner
        gui.voice.configure(
            HeadsetAudio(source.index, sink.index), headset_confirmed=True
        )
        gui.playback.configure(sink.index)
        native_output = gui.playback.audio
        assert native_output is not None
        observed_output = ObservedNativeOutput(native_output, lambda: gui.voice.running)
        gui.playback.audio = observed_output
        fixture.capture('native-duplex-source')
        fixture.client.finalize_voice(
            'native-duplex-source', 20, owner_token=fixture.owner
        )
        fixture.client.commit_voice(
            fixture.onion, 'native-duplex-source', owner_token=fixture.owner
        )
        duplex_target = gui.playback.target(
            fixture.onion,
            Delivery.DROP,
            MessageDirectionCode.OUT,
            'native-duplex-source',
        )
        assert duplex_target is not None
        started = time.monotonic()
        phase = 'entry'
        recording_at = 0.0
        identity = ''
        size = 0
        complete = False

        def step(_elapsed: float) -> bool:
            """Drives native key events and observes actual Core/worker completion.

            Args:
                _elapsed: Native scheduler interval.
            Returns:
                bool: Whether the probe requires another bounded poll.
            """
            nonlocal phase, recording_at, identity, size, complete
            assert app is not None and app.shell is not None
            if time.monotonic() - started > PROBE_DEADLINE_SECONDS:
                raise RuntimeError('Native GUI Voice probe did not complete in time')
            peer = next(
                (widget for widget in app.shell.walk() if isinstance(widget, PeerView)),
                None,
            )
            if peer is None:
                return True
            if phase == 'entry':
                if not Window.focus:
                    return True
                peer.composer.ptt.focus = True
                Window.dispatch('on_key_down', 32, 44, ' ', [])
                assert gui.voice.press.binding is not None, (
                    'Native focused PTT did not bind a target'
                )
                identity = gui.voice.press.binding.msg_id
                phase = 'starting'
            elif phase == 'starting' and gui.voice.press.phase.value == 'recording':
                recording_at = time.monotonic()
                assert gui.playback.play(duplex_target)
                phase = 'duplex'
            elif (
                phase == 'duplex'
                and gui.playback.progress is not None
                and not gui.playback.running
            ):
                assert observed_output.overlap, (
                    'Native playback did not overlap active capture'
                )
                assert gui.playback.progress.state == 'complete'
                assert gui.playback.progress.position == PcmVoice.FRAME_BYTES
                phase = 'recording'
            elif (
                phase == 'recording'
                and time.monotonic() - recording_at >= RECORD_SECONDS
            ):
                Window.dispatch('on_key_up', 32, 44)
                phase = 'review'
            elif phase == 'review' and fixture.onion in gui.voice.reviews:
                review = gui.voice.reviews[fixture.onion]
                assert review.binding.msg_id == identity and review.size_bytes > 0
                size = review.size_bytes
                assert peer.composer.preview.parent is not None
                peer.composer._play_review()
                phase = 'playback'
            elif (
                phase == 'playback'
                and gui.playback.progress is not None
                and gui.playback.progress.state != 'playing'
                and not gui.playback.running
            ):
                assert gui.playback.progress.state == 'complete', (
                    gui.playback.progress.state
                )
                assert gui.playback.progress.position == size
                record = fixture.messages.get_voice_payload(
                    fixture.onion, identity, MessageDirection.OUT
                )
                assert record is not None and record.status == 'draft'
                pending = fixture.messages.get_pending_outbox()
                assert [row[4] for row in pending] == ['native-duplex-source']
                args.result.parent.mkdir(parents=True, exist_ok=True)
                app.shell.export_to_png(str(args.result.with_suffix('.png')))
                evidence = {
                    'kind': 'native GUI synthetic-key PTT, explicit headset route, public SDK and temporary encrypted Core',
                    'revision_or_artifact': args.revision,
                    'mode': args.mode,
                    'system': platform.system(),
                    'python': platform.python_version(),
                    'module_origin_verified': True,
                    'input_device': source.index,
                    'output_device': sink.index,
                    'input_backend': hostapis[input_info['hostapi']]['name'],
                    'output_backend': hostapis[output_info['hostapi']]['name'],
                    'input_channels_available': input_info['max_input_channels'],
                    'output_channels_available': output_info['max_output_channels'],
                    'codec': PcmVoice.CODEC,
                    'captured_and_played_bytes': size,
                    'simultaneous_sdk_playback_bytes': PcmVoice.FRAME_BYTES,
                    'simultaneous_capture_output_observed': observed_output.overlap,
                    'encoded_duration_ms': PcmVoice.duration_ms(size),
                    'elapsed_seconds': time.monotonic() - started,
                    'canonical_result': 'unsent owned DROP draft plus one synthetic pending duplex source; no captured-audio publication',
                    'physical_input': False,
                    'microphone_audio_exported': False,
                    'aec_or_acoustic_quality_verified': False,
                    'rss_bytes': psutil.Process().memory_info().rss,
                    'probe_deadline_seconds': PROBE_DEADLINE_SECONDS,
                }
                args.result.write_text(
                    json.dumps(evidence, indent=2) + '\n', encoding='utf-8'
                )
                complete = True
                app.stop()
                return False
            return True

        Clock.schedule_interval(step, POLL_SECONDS)
        app.run()
        if not complete:
            raise RuntimeError('Native GUI Voice probe stopped before validation')
    finally:
        if app is not None:
            app.controller.close()
        fixture.doCleanups()
    print('NATIVE_GUI_HEADSET_REVIEW_OK')


if __name__ == '__main__':
    main()
