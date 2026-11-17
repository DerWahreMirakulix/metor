"""Lifecycle binding between GUI presentation and the native accessibility adapter."""

import platform
import ctypes
from ctypes import wintypes
import time
from collections.abc import Callable

from kivy.core.window import Window
from kivy.base import EventLoop
from kivy.uix.widget import Widget

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import GuiState
from metor.ui.gui.widgets import PointerTooltip

# Local Package Imports
from .model import AccessibleState
from .native import NativeAccessibility
from .projection import Projection


class AccessibilityBridge:
    """Owns revocation, context fencing and bounded UI-thread action dispatch."""

    def __init__(
        self, state: GuiState, activity: Callable[[], None], *, simulator: bool = False
    ) -> None:
        """Binds the synchronous privacy fence after the native window exists.

        Args:
            state: GUI-owned presentation state.
            activity: Deliberate user-interaction notification for the idle timer.
            simulator: Explicit nonproduction window identity, never a profile name.
        Returns:
            None
        """
        self.state = state
        self.activity = activity
        self.model = AccessibleState()
        self.projection = Projection()
        handle = (
            int(Window.get_window_info().window)
            if platform.system() == 'Windows'
            else None
        )
        self.native = NativeAccessibility(self.model, handle, simulator=simulator)
        self._stop_uid = EventLoop.fbind('on_stop', self._after_inputs_stopped)
        Window.show()
        if platform.system() == 'Windows':
            # Kivy 2.3.1 queries the active HWND while hidden and can cache zero DPI.
            get_dpi = getattr(ctypes, 'windll').user32.GetDpiForWindow
            get_dpi.argtypes = [wintypes.HWND]
            get_dpi.restype = wintypes.UINT
            dpi = get_dpi(handle)
            if dpi <= 0:
                raise RuntimeError('Native window DPI is unavailable')
            Window.dpi = float(dpi)
            Window._density = dpi / GuiLimits.WINDOWS_REFERENCE_DPI
        self._context: object = None
        self._root: Widget | None = None
        self._next_poll = 0.0
        state.privacy_fence = self.revoke

    def _current_context(self) -> object:
        """Captures the authority-relevant local presentation identity.

        Args:
            None
        Returns:
            object: Profile generation, route and cover state.
        """
        return self.state.generation, self.state.route, self.state.covered

    def rendered(self, root: Widget) -> None:
        """Allows publishing only after the current context has actually been rendered.

        Args:
            root: Completed app root; foreground modal selection happens below.
        Returns:
            None
        """
        if self._context != self._current_context():
            self.revoke()
        self._context = self._current_context()
        self._root = root
        self._publish()

    def _foreground(self) -> Widget | None:
        """Finds the foreground window child so covered modal content is excluded.

        Args:
            None
        Returns:
            Widget | None: Current native foreground widget.
        """
        if Window.children and isinstance(Window.children[0], Widget):
            return Window.children[0]
        return self._root

    def _publish(self) -> None:
        """Publishes current visible widgets or revokes an excessive projection.

        Args:
            None
        Returns:
            None
        """
        if self.native.adapter is None:
            return
        root = self._foreground()
        if root is None or self._context != self._current_context():
            return
        try:
            changed = self.model.publish(self.projection.capture(root))
        except ValueError:
            self.revoke()
            self.native.status = 'projection unavailable'
            return
        if changed:
            self.native.update()

    def poll(self) -> None:
        """Drains finite native requests and observes text/focus changes without reflow.

        Args:
            None
        Returns:
            None
        """
        if self._context != self._current_context():
            self.revoke()
            return
        root = self._foreground()
        for _ in range(GuiLimits.ACCESSIBILITY_ACTIONS):
            request = self.model.take()
            if request is None or root is None:
                break
            if self.projection.invoke(request, root):
                self.activity()
            if (
                self._context != self._current_context()
                or root is not self._foreground()
            ):
                self.revoke()
                break
        now = time.monotonic()
        if now >= self._next_poll:
            self._next_poll = now + GuiLimits.ACCESSIBILITY_POLL_SECONDS
            self._publish()

    def revoke(self) -> None:
        """Removes private native nodes and queued actions before the cover setter returns.

        Args:
            None
        Returns:
            None
        """
        self._context = None
        PointerTooltip.clear_all()
        self.model.revoke()
        self.projection.revoke()
        self.native.update()

    def close(self) -> None:
        """Revokes immediately; native subclass removal follows Kivy input-provider teardown.

        Args:
            None
        Returns:
            None
        """
        self.state.privacy_fence = None
        self.revoke()
        self._root = None
        if EventLoop.status != 'started':
            self._after_inputs_stopped()

    def _after_inputs_stopped(self, *_args: object) -> None:
        """Restores native WndProc ownership only after later Kivy subclasses are removed.

        Args:
            _args: Native event-loop stop notification.
        Returns:
            None
        """
        self.native.close()
        EventLoop.unbind_uid('on_stop', self._stop_uid)
