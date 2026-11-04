"""Actual endpoint-scan scheduling and native pressed-dismissal regression probe."""

from contextlib import ExitStack
import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

from kivy.clock import Clock

from frontend_e2e_runtime import FIXTURE_WAIT_SECONDS
from gui_native_x11 import rectangle
from metor.client.platform import AudioEndpoint
from metor.ui.gui.platform.audio import HeadsetAudio
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet

if TYPE_CHECKING:
    from gui_native_core import NativeCoreApp


class NativeAudioProbe:
    """Holds only actual enumeration delivery while an OS mouse button is down."""

    def __init__(self, app: 'NativeCoreApp') -> None:
        """Owns bounded scheduling instrumentation and no synthetic endpoint results."""
        self.app = app
        self.records: dict[str, object] = {}
        self._release = threading.Event()
        self._patch: ExitStack | None = None
        self._action: Action | None = None
        self._sheet: ActionSheet | None = None
        self._rectangle: tuple[float, float, float, float] | None = None
        self._pressed_at: float | None = None

    def hold_scan(self) -> None:
        """Calls native enumeration unchanged, delaying its real value or exception."""
        original = HeadsetAudio.endpoints

        def held() -> tuple[AudioEndpoint, ...]:
            """Preserves the native outcome while exposing its scheduling boundary."""
            try:
                result = original()
            except Exception:
                assert self._release.wait(FIXTURE_WAIT_SECONDS), (
                    'Native enumeration exception delivery barrier timed out'
                )
                raise
            assert self._release.wait(FIXTURE_WAIT_SECONDS), (
                'Native enumeration delivery barrier timed out'
            )
            return result

        assert not self.app.controller.voice.routes.scanned
        self._patch = ExitStack()
        self._patch.enter_context(patch.object(HeadsetAudio, 'endpoints', held))

    def press_close(self, action: Action) -> None:
        """Arms observation before native input presses the original dismissal target."""
        self._action, self._sheet = action, ActionSheet.current
        assert self._sheet is not None and not self.app.controller.voice.routes.scanned
        self._rectangle = rectangle(action)
        action.bind(on_press=self._pressed)
        self.app.native.click(action)

    def _pressed(self, *_args: object) -> None:
        """Releases actual scan delivery only after SDL dispatches the native press."""
        assert self._action is not None
        self._action.unbind(on_press=self._pressed)
        Clock.unschedule(self.app.native._release)
        self._pressed_at = time.monotonic()
        self._release.set()

    def frame(self) -> None:
        """Requires unchanged hit ownership after the scan's first reconciled draw."""
        if self._pressed_at is None:
            return
        assert time.monotonic() - self._pressed_at < FIXTURE_WAIT_SECONDS
        sheet, action = self._sheet, self._action
        assert sheet is not None and action is not None
        if not self.app.controller.voice.routes.scanned:
            return
        if sheet._eligibility_key != sheet._eligibility_revision():
            return
        current = self.app.action('Close')
        record = {
            'same_close_widget': current is action,
            'press_rect': self._rectangle,
            'release_rect': rectangle(action),
            'current_close_rect': rectangle(current) if current is not None else None,
            'original_attached': action.get_root_window() is not None,
            'original_pressed': action.state == 'down',
            'original_enabled': not action.disabled,
            'scan_completed_while_pressed': True,
        }
        self.records['close_across_native_enumeration'] = record
        self._pressed_at = None
        self.app.native._release(0)
        assert ActionSheet.current is sheet and current is action, record
        assert record['original_attached'] and record['original_pressed'], record
        assert record['original_enabled'] and rectangle(action) == self._rectangle, (
            record
        )
        self.app.checks['audio_close_stable_across_native_enumeration'] = True
        self.app.capture('audio-enumeration-pressed-close')

    def close(self) -> None:
        """Releases the worker, pressed pointer, and observers even after a failure."""
        self._release.set()
        if self._action is not None:
            self._action.unbind(on_press=self._pressed)
        if self._pressed_at is not None:
            self._pressed_at = None
            self.app.native._release(0)
        if self._patch is not None:
            self._patch.close()
            self._patch = None
