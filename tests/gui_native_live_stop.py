"""First-draw Cancel evidence while actual qualified Core execution is held."""

from contextlib import ExitStack
import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

from kivy.clock import Clock

from frontend_e2e_runtime import FIXTURE_WAIT_SECONDS

if TYPE_CHECKING:
    from gui_native_core import NativeCoreApp


RELEASE_SETTLE_SECONDS = 0.15


class NativeLiveStopProbe:
    """Holds server scheduling, preserving production GUI/SDK commands and results."""

    def __init__(self, app: 'NativeCoreApp') -> None:
        """Creates one finite barrier for the fixture's explicit outgoing cancel."""
        self.app = app
        self.entered = threading.Event()
        self.release = threading.Event()
        self.patches = ExitStack()
        self.calls = 0
        self.started: float | None = None
        self.recorded = False

    def cancel(self) -> None:
        """Clicks the native Cancel once after a real counterpart request exists."""
        network = self.app.runtime.daemon._network
        original = network.disconnect_qualified

        def held(target: str, generation: int | None, attempt: str | None) -> bool:
            """Waits before invoking the original exact-identity Core operation."""
            self.calls += 1
            self.entered.set()
            assert self.release.wait(FIXTURE_WAIT_SECONDS), 'Cancel barrier timed out'
            return original(target, generation, attempt)

        self.patches.enter_context(patch.object(network, 'disconnect_qualified', held))
        peer = self.app.peer()
        assert peer is not None

        def released(*_args: object) -> None:
            """Records actual native input release independently of fixture polling."""
            peer.end.unbind(on_release=released)
            self.started = time.monotonic()

        peer.end.bind(on_release=released)
        self.app.click('Cancel Live', peer)

    def frame(self) -> None:
        """Requires immediate disabled Cancelling on the first actual native draw."""
        if self.started is None or self.recorded:
            return
        peer = self.app.peer()
        assert peer is not None
        assert peer.end.disabled and peer.end.accessible_name == 'Cancelling Live…', (
            'First cancel draw lacks progress',
            peer.end.accessible_name,
            peer.end.disabled,
        )
        assert peer.subtitle.text == 'Cancelling Live…'
        self.app.ux.records['live_cancel_first_draw'] = {
            'release_to_first_draw_ms': round(
                (time.monotonic() - self.started) * 1000, 3
            ),
            'disabled': True,
            'label': peer.end.accessible_name,
            'before_core_completion': not self.release.is_set(),
        }
        self.recorded = True

    def pending_visible(self) -> bool:
        """Requires both the real Core barrier and the actual rendered progress."""
        return self.entered.is_set() and self.recorded

    def duplicate(self) -> None:
        """Clicks the disabled target once, then permits real cancellation to complete."""
        peer = self.app.peer()
        assert peer is not None
        self.app.native.click(peer.end, allow_disabled=True)

        def finish(_elapsed: float) -> None:
            """Releases the server only after duplicate native input has settled."""
            assert self.calls == 1, 'Duplicate cancel reached Core'
            self.app.checks['live_cancel_duplicate_suppressed'] = True
            self.close()

        Clock.schedule_once(finish, RELEASE_SETTLE_SECONDS)

    def ended(self) -> bool:
        """Waits for authoritative cancellation and an available fresh start."""
        peer = self.app.peer()
        return bool(
            peer is not None
            and self.release.is_set()
            and self.app.controller.live.pending is None
            and peer.subtitle.text == 'No Live connection'
            and not peer.connect.disabled
            and peer.connect.parent is peer.live_slot
            and peer.connect.get_root_window() is not None
        )

    def close(self) -> None:
        """Releases fixture scheduling on success or early GUI failure."""
        self.release.set()
        self.patches.close()
