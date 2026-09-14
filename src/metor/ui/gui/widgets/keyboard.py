"""Offline QWERTY/QWERTZ keyboard with bounded pages and the approved narrow character keys."""

from collections.abc import Callable
from functools import partial
import time

from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.constants import Geometry, GuiLimits

# Local Package Imports
from .controls import Action, Label, Panel


CHARACTER_PAGES: dict[str, tuple[str, str, str]] = {
    'letters': ('qwertyuiop', 'asdfghjkl', 'zxcvbnm'),
    'numbers': ('1234567890', '-/:;()$&@"', ".,?!'[]"),
    'symbols': ('`~!@#$%^&*', '_+=|\\{}<>', ".,?!'[]"),
}


class KeyboardKey(Action):
    """A touch key that deliberately preserves the native input field's focus."""

    def __init__(
        self,
        text: str,
        callback: Callable[[], object],
        *,
        surface: str = 'raised',
        tone: str = 'text',
        **kwargs: object,
    ) -> None:
        """Creates a full-tile key without geometric hover/press changes.

        Args:
            text: Local character or safely named keyboard operation.
            callback: Explicit local edit operation.
            surface: Named keyboard surface token.
            tone: Named key-label token.
            kwargs: Native layout properties.
        Returns:
            None
        """
        super().__init__(text, callback, surface=surface, tone=tone, **kwargs)
        self.padding = 0
        self.is_focusable = False

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Keeps a software-key press from transferring focus away from its field.

        Args:
            touch: Native input event.
        Returns:
            bool: Whether this exact key handled the event.
        """
        if self.collide_point(*touch.pos) and not self.disabled:
            FocusBehavior.ignored_touch.append(touch)
        return bool(super().on_touch_down(touch))


class LocalKeyboard(Panel):
    """Four local key rows and a 48-unit toolbar; stores no entered content."""

    def __init__(
        self,
        edit: Callable[[str], None],
        hide: Callable[[], None],
        *,
        layout: str = 'qwerty',
        pin: bool = False,
    ) -> None:
        """Builds the approved 264-unit keyboard from bundled font glyphs.

        Args:
            edit: Exact focused-field edit boundary.
            hide: Explicit dismissal retaining no input history.
            layout: Protected QWERTY or QWERTZ preference.
            pin: Whether the focused field requests large numeric PIN targets initially.
        Returns:
            None
        """
        super().__init__(
            orientation='vertical', size_hint_y=None, height=dp(Geometry.KEYBOARD)
        )
        self.edit, self.hide, self.layout = edit, hide, layout
        self.pin = pin
        self.page = 'letters'
        self.shift = False
        self.caps = False
        self._shift_at = 0.0
        toolbar = BoxLayout(
            size_hint_y=None, height=dp(48), padding=(dp(8), 0), spacing=dp(8)
        )
        toolbar.add_widget(KeyboardKey('Hide keyboard', hide))
        self.full = KeyboardKey(
            'ABC', self._full_keyboard, size_hint_x=None, width=dp(48)
        )
        self.full.accessible_name = 'Use full keyboard'
        self.toolbar = toolbar
        self.caption = Label('', role='support', tone='textSecondary', wrap=False)
        toolbar.add_widget(self.caption)
        self.add_widget(toolbar)
        self.rows = BoxLayout(
            orientation='vertical', spacing=dp(4), padding=(dp(8), dp(4), dp(8), dp(8))
        )
        self.add_widget(self.rows)
        self.bind(width=lambda *_args: self._build())
        self._build()

    def configure(self, *, layout: str, pin: bool) -> None:
        """Selects a field's keyboard without carrying modifier state between fields.

        Args:
            layout: Protected QWERTY or QWERTZ preference.
            pin: Whether to begin with the numeric PIN targets.
        Returns:
            None
        """
        self.layout, self.pin = layout, pin
        self.page = 'letters'
        self.shift = self.caps = False
        self._shift_at = 0.0
        self._build()

    def _character(self, value: str) -> None:
        """Edits one character and consumes single-use Shift without storing entered text.

        Args:
            value: Explicit local printable character.
        Returns:
            None
        """
        self.edit(value)
        if self.shift and not self.caps:
            self.shift = False
            self._build()

    def _shift(self) -> None:
        """Locks Caps only on a deliberate double activation within the approved interval.

        Args:
            None
        Returns:
            None
        """
        now = time.monotonic()
        if self.caps:
            self.caps = self.shift = False
        elif self.shift and now - self._shift_at <= GuiLimits.CAPS_SECONDS:
            self.caps = True
        else:
            self.shift = not self.shift
        self._shift_at = now
        self._build()

    def _page(self, page: str) -> None:
        """Selects a fixed offline character page without suggestions or learned state.

        Args:
            page: Application-owned page identifier.
        Returns:
            None
        """
        self.page = page
        self._build()

    def _full_keyboard(self) -> None:
        """Keeps existing nonnumeric PINs accessible without narrowing Core's accepted input.

        Args:
            None
        Returns:
            None
        """
        self.pin = False
        self._build()

    def _build(self) -> None:
        """Measures character tiles while preserving 48-unit special-key targets.

        Args:
            None
        Returns:
            None
        """
        self.rows.clear_widgets()
        if self.pin:
            if self.full.parent is None:
                self.toolbar.add_widget(self.full)
            self.caption.text = 'PIN'
            for values in ('123', '456', '789', '⌫0↵'):
                row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
                for value in values:
                    operation = (
                        'backspace'
                        if value == '⌫'
                        else 'enter'
                        if value == '↵'
                        else value
                    )
                    key = KeyboardKey(value, partial(self.edit, operation))
                    key.accessible_name = (
                        'Backspace'
                        if value == '⌫'
                        else 'Enter or Done'
                        if value == '↵'
                        else value
                    )
                    row.add_widget(key)
                self.rows.add_widget(row)
            return
        if self.full.parent is self.toolbar:
            self.toolbar.remove_widget(self.full)
        characters = CHARACTER_PAGES[self.page]
        character_width = max(0, (self.width - dp(16) - dp(36)) / 10)
        for index, raw in enumerate(characters):
            if self.layout == 'qwertz' and self.page == 'letters':
                raw = raw.translate(str.maketrans('yz', 'zy'))
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
            if index == 2:
                shift = KeyboardKey('⇧', self._shift, size_hint_x=None, width=dp(48))
                shift.accessible_name = 'Caps on' if self.caps else 'Shift'
                row.add_widget(shift)
            else:
                padding = max(
                    0,
                    (
                        self.width
                        - dp(16)
                        - len(raw) * character_width
                        - (len(raw) - 1) * dp(4)
                    )
                    / 2,
                )
                row.padding = (padding, 0)
            for character in raw:
                value = character.upper() if self.shift or self.caps else character
                row.add_widget(KeyboardKey(value, partial(self._character, value)))
            if index == 2:
                backspace = KeyboardKey(
                    '⌫', partial(self.edit, 'backspace'), size_hint_x=None, width=dp(48)
                )
                backspace.accessible_name = 'Backspace'
                row.add_widget(backspace)
            self.rows.add_widget(row)
        bottom = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        bottom.add_widget(
            KeyboardKey(
                '123' if self.page == 'letters' else 'ABC',
                partial(self._page, 'numbers' if self.page == 'letters' else 'letters'),
                size_hint_x=None,
                width=dp(48),
            )
        )
        bottom.add_widget(KeyboardKey('Space', partial(self._character, ' ')))
        bottom.add_widget(
            KeyboardKey(
                '#+=',
                partial(self._page, 'symbols' if self.page != 'symbols' else 'numbers'),
                size_hint_x=None,
                width=dp(48),
            )
        )
        done = KeyboardKey(
            '↵', partial(self.edit, 'enter'), size_hint_x=None, width=dp(48)
        )
        done.accessible_name = 'Enter or Done'
        bottom.add_widget(done)
        self.rows.add_widget(bottom)
        self.caption.text = 'Caps on' if self.caps else self.layout.upper()
