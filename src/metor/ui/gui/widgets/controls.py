"""Measured plain text, rounded controls and focus feedback without reflow."""

from collections.abc import Callable
from typing import ClassVar, Protocol

from kivy.graphics import Color, Line, RoundedRectangle
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior, FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label as KivyLabel
from kivy.uix.textinput import TextInput
from kivy.input.motionevent import MotionEvent

from metor.ui.gui.theme import TYPE, color, font_path


class Panel(BoxLayout):
    """Layout-owned rounded surface with geometry-independent state feedback."""

    def __init__(self, surface: str = 'surface', **kwargs: object) -> None:
        """Creates a surface; its parent owns all outer geometry.

        Args:
            surface: Named palette role.
            kwargs: Native layout arguments.
        Returns:
            None
        """
        super().__init__(**kwargs)
        self.surface: str = surface
        with self.canvas.before:
            self._fill = Color(*color(surface))
            self._rectangle = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(16)]
            )
        self.bind(pos=self._paint, size=self._paint)

    def _paint(self, *_args: object) -> None:
        """Updates drawing bounds without affecting layout.

        Args:
            _args: Native property callback arguments.
        Returns:
            None
        """
        self._rectangle.pos = self.pos
        self._rectangle.size = self.size


class Label(KivyLabel):
    """Locally rendered plain text with actual-font height measurement."""

    def __init__(
        self,
        text: str = '',
        role: str = 'body',
        tone: str = 'text',
        wrap: bool = True,
        **kwargs: object,
    ) -> None:
        """Constructs text without markup, URLs or remote asset lookup.

        Args:
            text: Canonical display text.
            role: Typography token.
            tone: Palette token.
            wrap: Whether height follows available-width wrapping.
            kwargs: Native presentation properties.
        Returns:
            None
        """
        size, line, weight = TYPE[role]
        super().__init__(
            text=text,
            font_name=font_path(weight),
            font_size=sp(size),
            color=color(tone),
            markup=False,
            halign='left',
            valign='middle',
            size_hint_y=None,
            **kwargs,
        )
        self._line_height: float = dp(line)
        self.height = self._line_height
        if wrap:
            self.bind(
                width=self._measure, text=self._measure, texture_size=self._height
            )
        else:
            self.size_hint_y = 1
            self.shorten = True
            self.shorten_from = 'right'
            self.bind(size=self._single)

    def _measure(self, *_args: object) -> None:
        """Measures width-constrained body text including unbroken runs.

        Args:
            _args: Property event.
        Returns:
            None
        """
        self.text_size = (self.width, None)

    def _height(self, *_args: object) -> None:
        """Grows the row using rendered font metrics.

        Args:
            _args: Texture event.
        Returns:
            None
        """
        self.height = max(self._line_height, self.texture_size[1])

    def _single(self, *_args: object) -> None:
        """Constrains header labels without reducing font size.

        Args:
            _args: Geometry event.
        Returns:
            None
        """
        self.text_size = self.size


class Action(FocusBehavior, ButtonBehavior, Panel):
    """Focus-scoped, keyboard-operable labelled action with fixed hit geometry."""

    def __init__(
        self,
        text: str,
        callback: Callable[[], object],
        *,
        surface: str = 'raised',
        tone: str = 'text',
        **kwargs: object,
    ) -> None:
        """Binds one explicit action; dynamic state never changes its target.

        Args:
            text: Safe visible and accessible label.
            callback: Explicit action invoked on release.
            surface: Named fill.
            tone: Named label color.
            kwargs: Layout properties.
        Returns:
            None
        """
        super().__init__(
            surface=surface,
            size_hint_y=None,
            height=dp(48),
            padding=(dp(12), dp(8)),
            **kwargs,
        )
        self.accessible_name: str = text
        self._tone = tone
        self._hovered = False
        self._keyboard_armed = False
        self._rectangle.radius = [dp(12)]
        self.is_focusable = True
        self._activate: Callable[[], object] = callback
        self.label = Label(text, role='button', tone=tone, wrap=False)
        self.label.halign = 'center'
        self.add_widget(self.label)
        with self.canvas.after:
            self._focus_color = Color(*color('focus'), group='focus')
            self._ring = Line(
                rounded_rectangle=(*self.pos, *self.size, dp(12)), width=dp(2)
            )
        self.bind(
            on_release=self._release,
            focus=self._feedback,
            state=self._feedback,
            pos=self._feedback,
            size=self._feedback,
            disabled=self._feedback,
        )
        self._feedback()
        Window.bind(mouse_pos=self._pointer)

    def _pointer(self, _window: object, position: tuple[float, float]) -> None:
        """Shows pointer feedback only while attached to the native window.

        Args:
            _window: Native window event source.
            position: Pointer coordinates.
        Returns:
            None
        """
        self._hovered = self.get_root_window() is not None and self.collide_point(
            *self.to_widget(*position, relative=False)
        )
        self._feedback()

    def _release(self, *_args: object) -> None:
        """Invokes only an enabled deliberate release.

        Args:
            _args: Native release event.
        Returns:
            None
        """
        if not self.disabled:
            self._activate()

    def _feedback(self, *_args: object) -> None:
        """Reserves focus stroke inside the target, avoiding hover/press reflow.

        Args:
            _args: Native feedback event.
        Returns:
            None
        """
        self._ring.rounded_rectangle = (
            self.x + dp(2),
            self.y + dp(2),
            max(0, self.width - dp(4)),
            max(0, self.height - dp(4)),
            dp(12),
        )
        self._focus_color.a = 1 if self.focus else 0
        if not self.focus or self.disabled:
            self._keyboard_armed = False
        base = color('raised' if self.disabled else self.surface)
        overlay = (
            0
            if self.disabled
            else 0.1
            if self.state == 'down'
            else 0.06
            if self._hovered
            else 0
        )
        target = 0 if self._tone in ('textSecondary', 'danger') else 1
        self._fill.rgba = tuple(
            channel + (target - channel) * overlay for channel in base[:3]
        ) + (1,)
        self.label.color = color('textDisabled' if self.disabled else self._tone)

    def keyboard_on_key_down(
        self, window: object, keycode: tuple[int, str], text: str, modifiers: list[str]
    ) -> bool:
        """Arms one focused ordinary action without accepting held-key repeats.

        Args:
            window: Native keyboard owner.
            keycode: Native key identity.
            text: Native text value.
            modifiers: Held modifier keys.
        Returns:
            bool: Whether activation input was handled.
        """
        if keycode[1] in ('spacebar', 'enter') and self.focus and not self.disabled:
            self._keyboard_armed = True
            self.state = 'down'
            return True
        return bool(super().keyboard_on_key_down(window, keycode, text, modifiers))

    def keyboard_on_key_up(self, window: object, keycode: tuple[int, str]) -> bool:
        """Activates ordinary controls only on focused Space/Enter release.

        Args:
            window: Keyboard owner.
            keycode: Native key identity.
        Returns:
            bool: Whether the event was handled.
        """
        if keycode[1] in ('spacebar', 'enter'):
            armed, self._keyboard_armed = self._keyboard_armed, False
            self.state = 'normal'
            if armed and self.focus and not self.disabled:
                self._activate()
            return True
        return bool(super().keyboard_on_key_up(window, keycode))


class KeyboardOwner(Protocol):
    """Native field-to-dock boundary without any profile or content persistence."""

    def focused(self, field: 'TextField') -> None: ...
    def show(self, field: 'TextField') -> None: ...


class TextField(TextInput):
    """Native text editing with clipboard export disabled by the platform default."""

    keyboard_owner: ClassVar[KeyboardOwner | None] = None

    def __init__(self, **kwargs: object) -> None:
        """Adds an explicit local keyboard target to every editable field.

        Args:
            kwargs: Native text-input properties.
        Returns:
            None
        """
        kwargs.setdefault('font_name', font_path())
        kwargs.setdefault('font_size', sp(15))
        kwargs.setdefault('foreground_color', color('text'))
        kwargs.setdefault('background_color', color('raised'))
        kwargs.setdefault('cursor_color', color('focus'))
        kwargs.setdefault('padding', (dp(16), dp(14)))
        super().__init__(**kwargs)
        self.local_keyboard_visible = False
        self.input_purpose = 'password' if self.password else 'text'
        # Icon controls depend on Action in this module and load after it exists.
        from .symbol import IconAction

        self._keyboard_action = IconAction(
            'keyboard', 'Show keyboard', self._show_keyboard
        )
        self._keyboard_action.is_focusable = False
        self.add_widget(self._keyboard_action, canvas='after')
        self.padding[2] = max(self.padding[2], dp(48))
        self.bind(
            right=self._keyboard_bounds,
            center_y=self._keyboard_bounds,
            focus=self._keyboard_focus,
            disabled=self._keyboard_bounds,
            readonly=self._keyboard_bounds,
        )
        self._keyboard_bounds()

    def _keyboard_bounds(self, *_args: object) -> None:
        """Reserves a fixed trailing key target without overlapping editable text.

        Args:
            _args: Native property callbacks.
        Returns:
            None
        """
        self._keyboard_action.pos = self.right - dp(48), self.center_y - dp(24)
        self._keyboard_action.disabled = self.disabled or self.readonly

    def _keyboard_focus(self, _widget: object, focused: bool) -> None:
        """Offers newly focused text/password input to the configured local dock.

        Args:
            _widget: Native focus source.
            focused: Current focus state.
        Returns:
            None
        """
        if focused and self.keyboard_owner is not None:
            self.keyboard_owner.focused(self)

    def _show_keyboard(self) -> None:
        """Explicitly requests local input without exposing text to clipboard or logging.

        Args:
            None
        Returns:
            None
        """
        if self.keyboard_owner is not None:
            self.keyboard_owner.show(self)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Prioritizes the keyboard target before native text-selection handling.

        Args:
            touch: Native pointer/touch identity.
        Returns:
            bool: Whether the field or its explicit keyboard target handled input.
        """
        if self._keyboard_action.collide_point(*touch.pos) and not self.disabled:
            FocusBehavior.ignored_touch.append(touch)
            return bool(self._keyboard_action.on_touch_down(touch))
        return bool(super().on_touch_down(touch))

    def copy(self, data: str = '') -> None:
        """Keeps selected profile-linked text out of the host clipboard.

        Args:
            data: Ignored clipboard selection.
        Returns:
            None
        """

    def cut(self) -> None:
        """Disables clipboard Cut while ordinary keyboard editing remains available.

        Args:
            None
        Returns:
            None
        """


class SecretInput(TextField):
    """Masked local credential input with clipboard export disabled."""

    def __init__(self, **kwargs: object) -> None:
        """Builds a password field with the bundled font.

        Args:
            kwargs: Native input properties.
        Returns:
            None
        """
        super().__init__(
            password=True,
            multiline=False,
            font_name=font_path(),
            font_size=sp(15),
            size_hint_y=None,
            height=dp(52),
            foreground_color=color('text'),
            background_color=color('raised'),
            cursor_color=color('focus'),
            padding=(dp(16), dp(16)),
            **kwargs,
        )
        self.use_bubble = False
        self.use_handles = False

    def paste(self) -> None:
        """Keeps credential and PIN input outside clipboard conveniences.

        Args:
            None
        Returns:
            None
        """
