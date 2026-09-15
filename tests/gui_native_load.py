"""Native event-loop latency measurements while bounded root metadata is rebuilt."""

from collections.abc import Callable
from dataclasses import replace
import json
from pathlib import Path
import statistics
import threading
import time

from kivy.clock import Clock
from kivy.core.window import Window
import psutil

from metor.core.api import Delivery
from metor.ui.gui.app import MetorApp
from metor.ui.gui.widgets import Action


SAMPLES = 24
PROBE_TIMEOUT_SECONDS = 30.0


def exercise_native_load(
    app: MetorApp, complete: Callable[[], None], result: Path
) -> None:
    """Queues one measured native arrow input at a time during canonical root updates.

    Args:
        app: Running native fixture with 130 synthetic conversation summaries.
        complete: Capture continuation after all measured input has run.
        result: Metadata-only measurement destination.
    Returns:
        None
    """
    latencies: list[float] = []
    rss: list[int] = []
    render_times: list[float] = []
    acknowledged = threading.Event()
    process = psutil.Process()
    controller = app.controller
    assert app.shell is not None
    controller.state.root_pages[Delivery.DROP] = 0
    app.shell.render()
    original_route = controller.state.route

    def deliver(sent: float, sequence: int) -> None:
        """Runs real native key dispatch and then an ordinary synthetic metadata repaint.

        Args:
            sent: Monotonic worker enqueue timestamp.
            sequence: Bounded sample index.
        Returns:
            None
        """
        assert app.shell is not None
        latencies.append((time.monotonic() - sent) * 1000)
        panel = app.shell._root_panel
        first = next(
            item
            for item in panel.walk(restrict=True)
            if isinstance(item, Action) and item.focus_key == ('selector', 'DROP')
        )
        first.focus = True
        Window.dispatch('on_key_down', 275, 79, '', [])
        Window.dispatch('on_key_up', 275, 79)
        assert first.focus_group[1].focus
        assert controller.state.route == original_route and controller.client is None
        snapshot = controller.state.snapshot
        controller.state.snapshot = replace(
            snapshot,
            revision=(snapshot.revision or 0) + 1,
            conversations=[
                replace(item, alias=f'Peer {index:03d} update {sequence}')
                for index, item in enumerate(snapshot.conversations)
            ],
        )
        start = time.monotonic()
        app.shell.render()
        render_times.append((time.monotonic() - start) * 1000)
        rss.append(process.memory_info().rss)
        acknowledged.set()

    def finish(_elapsed: float) -> None:
        """Records bounded measurements without treating synthetic inputs as hardware proof.

        Args:
            _elapsed: Native callback interval.
        Returns:
            None
        """
        assert len(latencies) == SAMPLES
        result.write_text(
            json.dumps(
                {
                    'kind': 'native SDL queued keyboard input during root metadata rebuilds',
                    'synthetic_input': True,
                    'native_audio': False,
                    'core_integration': False,
                    'root_summaries': 130,
                    'attached_rows_maximum': 64,
                    'samples': SAMPLES,
                    'queued_input_maximum': 1,
                    'input_latency_p95_ms': statistics.quantiles(latencies, n=20)[18],
                    'input_latency_max_ms': max(latencies),
                    'input_latency_samples_ms': latencies,
                    'first_input_during_initial_layout_ms': latencies[0],
                    'subsequent_input_p95_ms': statistics.quantiles(
                        latencies[1:], n=20
                    )[18],
                    'root_render_p95_ms': statistics.quantiles(render_times, n=20)[18],
                    'root_render_max_ms': max(render_times),
                    'rss_samples_bytes': rss,
                    'passed_identity_and_no_navigation_checks': True,
                    'scope': 'Linux x86_64 SDL offscreen; excludes native audio and physical device latency',
                },
                indent=2,
            )
            + '\n'
        )
        complete()

    def produce() -> None:
        """Queues bounded synthetic native inputs without reading or mutating widgets.

        Args:
            None
        Returns:
            None
        """
        for sequence in range(SAMPLES):
            acknowledged.clear()
            sent = time.monotonic()
            Clock.schedule_once(
                lambda elapsed, sent=sent, sequence=sequence: deliver(sent, sequence), 0
            )
            if not acknowledged.wait(PROBE_TIMEOUT_SECONDS):
                return
        Clock.schedule_once(finish, 0)

    threading.Thread(
        target=produce, name='metor-native-input-probe', daemon=True
    ).start()
