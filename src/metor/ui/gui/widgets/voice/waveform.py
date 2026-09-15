"""Native audio-position action with a bounded real waveform and explicit keyboard seeking."""

from collections.abc import Callable

from kivy.graphics import Color, InstructionGroup, Line
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.theme import color

from ..controls import Label
from ..context import ContextAction


class WaveformSeek(ContextAction):
    """Keeps audio seeking distinct from scrolling and leaves unknown samples undrawn."""

    def __init__(
        self, seek: Callable[[float], None], context: Callable[[], object] | None = None
    ) -> None:
        """Creates one keyboard/pointer action; no source read or audio starts during rendering.

        Args:
            seek: Explicit chosen fraction of the currently displayed audio extent.
            context: Equivalent message actions; a contextual gesture never seeks.
        Returns:
            None
        """
        self._seek = seek
        self._fraction = 0.0
        self._available = 0
        self._position = 0
        self._envelope: tuple[int, tuple[int | None, ...]] = (0, ())
        super().__init__('Seek audio', self._activate_seek, context, surface='surface')
        self.padding = 0
        self.spacing = dp(4)
        self.orientation = 'vertical'
        self.remove_widget(self.label)
        self.hint = Label('Play to load waveform', role='caption', tone='textSecondary')
        self.metadata = Label('', role='caption', tone='textSecondary')
        self.add_widget(self.hint)
        self.add_widget(self.metadata)
        self._wave = InstructionGroup()
        self.canvas.after.add(self._wave)
        self.bind(
            pos=self._draw,
            size=self._draw,
            focus=self._draw,
            minimum_height=self._measure,
        )

    def _measure(self, *_args: object) -> None:
        """Keeps the hit target at least 48 logical units and grows for wrapped metadata.

        Args:
            _args: Native measurement callback.
        Returns:
            None
        """
        self.height = max(dp(48), self.minimum_height)

    def set_source(
        self,
        available: int,
        position: int,
        envelope: tuple[int, tuple[int | None, ...]],
    ) -> None:
        """Updates only bounded rendering facts without changing the deliberate seek selection.

        Args:
            available: Current sample-aligned byte extent.
            position: Actual local playback cursor.
            envelope: Bytes per bin and amplitude summaries from validated PCM.
        Returns:
            None
        """
        self._available, self._position, self._envelope = available, position, envelope
        self._draw()

    def _draw(self, *_args: object) -> None:
        """Draws at most the declared bin count; absent data never becomes a fabricated waveform.

        Args:
            _args: Native geometry callback.
        Returns:
            None
        """
        self._wave.clear()
        stride, peaks = self._envelope
        if self._available <= 0 or stride <= 0 or self.hint.text:
            return
        center = self.hint.center_y
        for index, peak in enumerate(peaks):
            offset = index * stride
            if peak is None or offset >= self._available:
                continue
            center_offset = offset + min(stride, self._available - offset) / 2
            x = self.x + self.width * center_offset / self._available
            amplitude = max(dp(1), self.hint.height * 0.45 * peak / (1 << 15))
            self._wave.add(
                Color(*color('live' if offset < self._position else 'textSecondary'))
            )
            self._wave.add(
                Line(points=(x, center - amplitude, x, center + amplitude), width=dp(1))
            )
        if self.focus:
            x = self.x + self.width * self._fraction
            self._wave.add(Color(*color('focus')))
            self._wave.add(Line(points=(x, self.hint.y, x, self.hint.top), width=dp(1)))

    def _activate_seek(self) -> None:
        """Submits only an explicit native activation of the current audio-position selection.

        Args:
            None
        Returns:
            None
        """
        self._seek(self._fraction)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Captures a pointer position while native scroll arbitration still owns cancellation.

        Args:
            touch: Native pointer or touch event.
        Returns:
            bool: Whether this action admitted the press.
        """
        if (
            self.collide_point(*touch.pos)
            and self.width > 0
            and not touch.is_mouse_scrolling
        ):
            self._fraction = min(1.0, max(0.0, (touch.x - self.x) / self.width))
        return bool(super().on_touch_down(touch))

    def keyboard_on_key_down(
        self, window: object, keycode: tuple[int, str], text: str, modifiers: list[str]
    ) -> bool:
        """Chooses a bounded seek position with arrows/Home/End; Enter or Space applies it.

        Args:
            window: Native keyboard source.
            keycode: Focused native key identity.
            text: Native text payload.
            modifiers: Held modifier names.
        Returns:
            bool: Whether this audio-position control consumed the key.
        """
        if (
            self.focus
            and not self.disabled
            and keycode[1] in {'left', 'right', 'home', 'end'}
        ):
            self._fraction = (
                0.0
                if keycode[1] == 'home'
                else 1.0
                if keycode[1] == 'end'
                else min(
                    1.0,
                    max(
                        0.0,
                        self._fraction
                        + (
                            GuiLimits.SEEK_FRACTION_STEP
                            if keycode[1] == 'right'
                            else -GuiLimits.SEEK_FRACTION_STEP
                        ),
                    ),
                )
            )
            self.accessible_name = (
                f'Seek audio to {self._fraction:.0%}; press Enter to play'
            )
            self._draw()
            return True
        return bool(super().keyboard_on_key_down(window, keycode, text, modifiers))
