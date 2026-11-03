"""Native text and credential fields with local editing and deliberate focus feedback."""

from typing import ClassVar, Literal, Protocol, cast

from kivy.graphics import Canvas, Color, InstructionGroup, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.textinput import TextInput

from metor.ui.gui.theme import color, font_path


class KeyboardOwner(Protocol):
    """Native field-to-dock boundary without any profile or content persistence."""

    def focused(self, field: 'TextField') -> None:
        """Reports the native field that currently owns keyboard focus.

        Args:
            field: Focused text field.
        Returns:
            None
        """
        ...

    def unfocused(self, field: 'TextField') -> None:
        """Reports a field departure so a later focus can reopen local input.

        Args:
            field: Field that lost native focus.
        Returns:
            None
        """
        ...

    def show(self, field: 'TextField') -> None:
        """Shows the native keyboard for one focused field.

        Args:
            field: Focused text field.
        Returns:
            None
        """
        ...


class TextField(TextInput):
    """Native text editing with clipboard export disabled for selected text."""

    height: float
    background_color: tuple[float, float, float, float]
    keyboard_owner: ClassVar[KeyboardOwner | None] = None
    submit_on_enter = BooleanProperty(False)

    def __init__(
        self, *, accessible_name: str = '', framed: bool = True, **kwargs: object
    ) -> None:
        """Builds an editable field whose device keyboard follows focus.

        Args:
            accessible_name: Persistent field purpose independent of placeholder or value.
            framed: Draw a standalone field boundary. A composer supplies its own surface.
            kwargs: Native text-input properties.
        Returns:
            None
        """
        kwargs.setdefault('font_name', font_path())
        kwargs.setdefault('font_size', '15sp')
        kwargs.setdefault('foreground_color', color('text'))
        kwargs.setdefault('background_color', color('raised'))
        kwargs.setdefault('hint_text_color', color('textSecondary'))
        kwargs.setdefault('cursor_color', color('focus'))
        kwargs.setdefault('padding', ('16dp', '14dp'))
        super().__init__(**kwargs)
        if framed:
            self._install_frame()
        self.accessible_name = accessible_name
        self._minimum_field_height = self.height / dp(1)
        self.bind(minimum_height=self._fit_single_line)
        self._fit_single_line()
        self.bind(text=self._font_coverage)
        self._font_coverage()
        self.local_keyboard_visible = False
        self.input_purpose = 'password' if self.password else 'text'
        self._enter_down = False
        self.bind(focus=self._keyboard_focus)

    def _install_frame(self) -> None:
        """Replace the toolkit's beveled field with an inset outline behind native text and caret."""
        fill = self.background_color[:]
        self.background_color = (0, 0, 0, 0)
        layer = InstructionGroup()
        edge = Color()
        border = RoundedRectangle()
        surface = RoundedRectangle()
        for instruction in (edge, border, Color(*fill), surface):
            layer.add(instruction)
        cast(Canvas, self.canvas).before.insert(0, layer)

        def sync(*_args: object) -> None:
            """Paint focus inside the same target so typing and tabbing never move its neighbors."""
            focused = self.focus and not self.disabled
            stroke = max(1, round(dp(2 if focused else 1)))
            radius = dp(10)
            edge.rgba = color(
                'focus'
                if focused
                else 'line'
                if self.disabled or self.readonly
                else 'controlBoundary'
            )
            border.pos, border.size, border.radius = self.pos, self.size, [radius]
            surface.pos = self.x + stroke, self.y + stroke
            surface.size = (
                max(0, self.width - 2 * stroke),
                max(0, self.height - 2 * stroke),
            )
            surface.radius = [max(0, radius - stroke)]

        self.bind(pos=sync, size=sync, focus=sync, readonly=sync, disabled=sync)
        sync()

    def _fit_single_line(self, *_args: object) -> None:
        """Keeps scaled text and its padding inside fixed-height form fields."""
        if not self.multiline and self.size_hint_y is None:
            self.height = max(dp(self._minimum_field_height), self.minimum_height)

    def enter(self, *, shift: bool = False) -> None:
        """Applies the field's explicit Enter policy for physical and local input.

        Args:
            shift: Whether Shift+Enter requests a multiline line break.
        Returns:
            None
        """
        if self.disabled or self.readonly:
            return
        if self.multiline and (shift or not self.submit_on_enter):
            self.insert_text('\n')
        else:
            self.dispatch('on_text_validate')

    def keyboard_on_key_down(
        self, window: object, keycode: tuple[int, str], text: str, modifiers: list[str]
    ) -> Literal[True] | None:
        """Keeps composer Enter local to its focus owner and suppresses held repeats.

        Args:
            window: Native keyboard owner.
            keycode: Native key identity.
            text: Native text value.
            modifiers: Held modifier keys.
        Returns:
            Literal[True] | None: True for handled input, otherwise no native result.
        """
        if self.submit_on_enter and keycode[1] in {'enter', 'numpadenter'}:
            if self.focus and not self.disabled and not self.readonly:
                if 'shift' in modifiers:
                    self.enter(shift=True)
                elif not self._enter_down:
                    self._enter_down = True
                    self.enter()
            return True
        return (
            True
            if super().keyboard_on_key_down(window, keycode, text, modifiers) is True
            else None
        )

    def keyboard_on_key_up(self, window: object, keycode: tuple[int, str]) -> None:
        """Releases the exact Enter owner without changing composer focus.

        Args:
            window: Native keyboard owner.
            keycode: Released native key identity.
        Returns:
            None: Matches the native text input's release callback contract.
        """
        if self.submit_on_enter and keycode[1] in {'enter', 'numpadenter'}:
            self._enter_down = False
            return
        super().keyboard_on_key_up(window, keycode)

    def _font_coverage(self, *_args: object) -> None:
        """Keeps accepted Unicode editable while masked credentials use a fixed font.

        Args:
            _args: Native text change.
        Returns:
            None
        """
        self.font_name = font_path(text='' if self.password else self.text)

    def _keyboard_focus(self, _widget: object, focused: bool) -> None:
        """Offers newly focused text/password input to the configured local dock.

        Args:
            _widget: Native focus source.
            focused: Current focus state.
        Returns:
            None
        """
        if self.keyboard_owner is not None:
            if focused:
                self.keyboard_owner.focused(self)
            else:
                self.keyboard_owner.unfocused(self)
        if not focused:
            self._enter_down = False

    def copy(self, data: str = '') -> None:
        """Keeps selected profile-linked text out of the host clipboard.

        Args:
            data: Ignored clipboard selection.
        Returns:
            None
        """

    def _cut(self, data: str) -> None:
        """Block the shared Cut path used by Kivy's keyboard and selection menu.

        Args:
            data: Selected field content.
        Returns:
            None
        """

    def _update_cutbuffer(self, *_args: object) -> None:
        """Keep native text selection local when a primary-selection provider exists."""


class SecretInput(TextField):
    """Masked local credential input with clipboard export disabled."""

    def __init__(self, *, accessible_name: str = '', **kwargs: object) -> None:
        """Builds a password field with the bundled font.

        Args:
            accessible_name: Credential purpose without its value or length.
            kwargs: Native input properties.
        Returns:
            None
        """
        super().__init__(
            accessible_name=accessible_name,
            framed=True,
            password=True,
            multiline=False,
            font_name=font_path(),
            font_size='15sp',
            size_hint_y=None,
            height='52dp',
            foreground_color=color('text'),
            background_color=color('raised'),
            cursor_color=color('focus'),
            padding=('16dp', '16dp'),
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
