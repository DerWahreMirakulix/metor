"""Pointer-grab and focused-key PTT control with lifetime-independent release routing."""

from collections.abc import Callable

from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice import PressSource

# Local Package Imports
from .controls import Action


class PttAction(Action):
    """A labelled microphone target; a held source never becomes an ordinary click."""

    def __init__(
        self,
        controller: GuiController,
        refresh: Callable[[], None],
        unavailable: Callable[[], None] | None = None,
    ) -> None:
        """Binds native input to the current public-service controller.

        Args:
            controller: GUI coordinator retaining native input ownership.
            refresh: Coalesced repaint request.
            unavailable: Explicit local setup help when a released press lacks audio.
        Returns:
            None
        """
        super().__init__('Hold to talk', lambda: None, size_hint_x=None, width=dp(148))
        self.controller = controller
        self.refresh = refresh
        self.unavailable = unavailable
        self._missing_audio = False
        self._touch_identity: str | None = None
        self._key_identity: str | None = None
        self.bind(focus=self._focus_changed, parent=self._parent_changed)

    @property
    def held(self) -> bool:
        """Report whether live capture still depends on this pressed native target.

        Args:
            None
        Returns:
            bool: Whether this widget still owns an active recording press.
        """
        press = self.controller.voice.press
        return (
            (self._touch_identity is not None or self._key_identity is not None)
            and press.active
            and not press.stop_requested
        )

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Captures one eligible pointer identity and rejects a second pointer owner.

        Args:
            touch: Native touch/mouse event.
        Returns:
            bool: Whether the native target handled the pointer event.
        """
        if (
            self.disabled
            or touch.is_mouse_scrolling
            or not self.collide_point(*touch.pos)
        ):
            return False
        if self._touch_identity is not None:
            return True
        handled = bool(super().on_touch_down(touch))
        if handled:
            self._touch_identity = str(touch.uid)
            self._missing_audio = self._needs_audio()
            if not self._missing_audio:
                self.controller.inputs.down(
                    PressSource.POINTER, self._touch_identity, self.controller.voice
                )
            self.refresh()
        return handled

    def on_touch_up(self, touch: MotionEvent) -> bool:
        """Releases the original pointer even when it ends outside the target.

        Args:
            touch: Native release event.
        Returns:
            bool: Whether the native button processed release.
        """
        handled = bool(super().on_touch_up(touch))
        identity = str(touch.uid)
        if identity == self._touch_identity and handled:
            self.controller.inputs.up(PressSource.POINTER, identity)
            self._touch_identity = None
            missing_audio = self._missing_audio
            self._missing_audio = False
            if missing_audio and not self.disabled and self.collide_point(*touch.pos):
                self._show_help()
            self.refresh()
        return handled

    def keyboard_on_key_down(
        self, window: object, keycode: tuple[int, str], text: str, modifiers: list[str]
    ) -> bool:
        """Admits only a fresh focused Space press observed by the native window.

        Args:
            window: Native keyboard source.
            keycode: Actual key identity.
            text: Native text event.
            modifiers: Held modifier names.
        Returns:
            bool: Whether the focused PTT control handled this key.
        """
        if self.focus and keycode[1] == 'enter':
            return True
        if self.focus and keycode[1] == 'spacebar':
            if self.disabled:
                return True
            identity = str(keycode[0])
            if self.controller.inputs.fresh_key(identity):
                self._key_identity = identity
                self._missing_audio = self._needs_audio()
                if not self._missing_audio:
                    self.controller.inputs.down(
                        PressSource.KEYBOARD, identity, self.controller.voice
                    )
                self.state = 'down'
                self.refresh()
            return True
        return bool(super().keyboard_on_key_down(window, keycode, text, modifiers))

    def keyboard_on_key_up(self, window: object, keycode: tuple[int, str]) -> bool:
        """Restores native feedback; the window also routes releases after focus loss.

        Args:
            window: Native keyboard source.
            keycode: Released key identity.
        Returns:
            bool: Whether this was the control's held key.
        """
        if str(keycode[0]) == self._key_identity:
            self.controller.inputs.up(PressSource.KEYBOARD, self._key_identity)
            self._key_identity = None
            self.state = 'normal'
            if self._missing_audio:
                self._show_help()
            self.refresh()
            return True
        return bool(super().keyboard_on_key_up(window, keycode))

    def _needs_audio(self) -> bool:
        """Keeps an unavailable media action intentional without admitting a capture."""
        voice = self.controller.voice
        return self.unavailable is not None and (
            voice.audio is None or not voice.headset_confirmed or voice.audio.failed
        )

    def _show_help(self) -> None:
        """Opens help only after release and never reconstructs the attempted press."""
        self._missing_audio = False
        if self.unavailable is not None and not self.controller.state.covered:
            self.unavailable()

    def _focus_changed(self, _widget: object, focused: bool) -> None:
        """Stops a focused-key recording when its control loses keyboard focus.

        Args:
            _widget: Native focus source.
            focused: Current focus state.
        Returns:
            None
        """
        if not focused and self._key_identity is not None:
            if self._missing_audio:
                self._key_identity = None
                self._missing_audio = False
                self.state = 'normal'
            else:
                self.controller.voice.depart()

    def _parent_changed(self, _widget: object, parent: object) -> None:
        """Treats removal of a held target as input-context departure.

        Args:
            _widget: Native control.
            parent: Current layout owner, or None after removal.
        Returns:
            None
        """
        if parent is None and (
            self._touch_identity is not None or self._key_identity is not None
        ):
            if self._missing_audio:
                self._missing_audio = False
            else:
                self.controller.voice.depart()
