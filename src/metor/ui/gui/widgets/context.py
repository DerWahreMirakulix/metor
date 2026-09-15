"""Native contextual actions with equivalent More, keyboard, pointer and hold access."""

from collections.abc import Callable

from kivy.clock import Clock, ClockEvent
from kivy.core.window import Window
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp

from metor.ui.gui.constants import GuiLimits

# Local Package Imports
from .controls import Action


class ContextAction(Action):
    """Keeps an ordinary primary action distinct from explicit contextual gestures."""

    def __init__(
        self,
        text: str,
        callback: Callable[[], object],
        context: Callable[[], object] | None = None,
        surface: str = 'surface',
        tone: str = 'text',
        **kwargs: object,
    ) -> None:
        """Binds both actions to the same originally displayed item identity.

        Args:
            text: Primary accessible action label.
            callback: Ordinary release action.
            context: Same operation as the visible More target.
            surface: Named action surface color.
            tone: Named action text color.
            kwargs: Native Action properties.
        Returns:
            None
        """
        self.context = context
        self._hold: ClockEvent | None = None
        self._origin = (0.0, 0.0)
        self._pointer_identity: str | None = None
        self._context_used = False
        self._context_key_code: int | None = None
        super().__init__(text, callback, surface=surface, tone=tone, **kwargs)
        self.bind(parent=self._cancel_hold, disabled=self._cancel_hold)
        Window.bind(on_key_up=self._window_key_up)

    def _cancel_hold(self, *_args: object) -> None:
        """Cancels a pending hold when its target departs or becomes unavailable.

        Args:
            _args: Native lifetime event.
        Returns:
            None
        """
        if self._hold is not None:
            self._hold.cancel()
            self._hold = None

    def _open_context(self, _elapsed: float = 0.0) -> None:
        """Consumes the primary press before opening one context menu.

        Args:
            _elapsed: Native hold delay.
        Returns:
            None
        """
        self._cancel_hold()
        if self.context is None or self.disabled or self.get_root_window() is None:
            return
        self._context_used = True
        self._keyboard_armed = False
        self.state = 'normal'
        self.context()

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Starts a bounded hold or explicitly consumes a right-click context gesture.

        Args:
            touch: Native pointer event.
        Returns:
            bool: Whether this target owns the gesture.
        """
        if self.context is None:
            return bool(super().on_touch_down(touch))
        if (
            self.disabled
            or touch.is_mouse_scrolling
            or not self.collide_point(*touch.pos)
        ):
            return False
        if self._pointer_identity is not None:
            return True
        self._context_used = False
        self._pointer_identity = str(touch.uid)
        self._origin = touch.pos
        if getattr(touch, 'button', None) == 'right':
            self._open_context()
            return True
        handled = bool(super().on_touch_down(touch))
        if handled:
            self._hold = Clock.schedule_once(
                self._open_context, GuiLimits.LONG_PRESS_SECONDS
            )
        else:
            self._pointer_identity = None
        return handled

    def on_touch_move(self, touch: MotionEvent) -> bool:
        """Cancels long press after the approved travel threshold without triggering an action.

        Args:
            touch: Native pointer motion.
        Returns:
            bool: Ordinary native gesture handling result.
        """
        if str(touch.uid) == self._pointer_identity:
            travel = (touch.x - self._origin[0]) ** 2 + (touch.y - self._origin[1]) ** 2
            if travel > dp(GuiLimits.LONG_PRESS_TRAVEL) ** 2:
                self._cancel_hold()
        return bool(super().on_touch_move(touch))

    def on_touch_up(self, touch: MotionEvent) -> bool:
        """Releases the original pointer without activating an item after its context menu.

        Args:
            touch: Native release event.
        Returns:
            bool: Whether this target handled release.
        """
        owned = str(touch.uid) == self._pointer_identity
        if owned:
            self._cancel_hold()
            self._pointer_identity = None
        return bool(super().on_touch_up(touch) or owned)

    def _release(self, *_args: object) -> None:
        """Suppresses ordinary activation after a consumed context gesture.

        Args:
            _args: Native button release.
        Returns:
            None
        """
        if not self._context_used:
            super()._release(*_args)

    def keyboard_on_key_down(
        self, window: object, keycode: tuple[int, str], text: str, modifiers: list[str]
    ) -> bool:
        """Maps focused Shift+F10 and the native menu key to the visible More action.

        Args:
            window: Native keyboard source.
            keycode: Native key identity.
            text: Native text event.
            modifiers: Held modifier names.
        Returns:
            bool: Whether this action consumed the shortcut.
        """
        if (
            self.context is not None
            and self.focus
            and (keycode[1] == 'menu' or (keycode[1] == 'f10' and 'shift' in modifiers))
        ):
            if self._context_key_code is None:
                self._context_key_code = keycode[0]
                self._open_context()
            return True
        self._context_used = False
        return bool(super().keyboard_on_key_down(window, keycode, text, modifiers))

    def keyboard_on_key_up(self, window: object, keycode: tuple[int, str]) -> bool:
        """Rearms contextual keys only after actual release.

        Args:
            window: Native keyboard source.
            keycode: Released key identity.
        Returns:
            bool: Whether this was a contextual shortcut release.
        """
        if keycode[1] in {'menu', 'f10'}:
            self._context_key_code = None
            return True
        return bool(super().keyboard_on_key_up(window, keycode))

    def _window_key_up(self, _window: object, key: int, _scancode: int) -> bool:
        """Observes actual release even after a native modal takes keyboard focus.

        Args:
            _window: Native release source.
            key: Released native key code.
            _scancode: Platform scan code.
        Returns:
            bool: False permits ordinary native key handling.
        """
        if key == self._context_key_code:
            self._context_key_code = None
        return False
