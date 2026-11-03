"""Measured multiline list previews that keep the original identity for their owner."""

from kivy.core.text import Label as TextMeasure
from kivy.properties import StringProperty

from metor.ui.gui.theme import font_path

from .controls import Label


class BoundedLabel(Label):
    """Wrap a plain preview to a finite number of lines and mark omitted text."""

    full_text = StringProperty('')

    def __init__(
        self,
        text: str = '',
        *,
        role: str = 'row',
        tone: str = 'text',
        max_lines: int = 3,
        **kwargs: object,
    ) -> None:
        """Bind the full source independently from the responsive, painted prefix."""
        if max_lines < 1:
            raise ValueError('A preview requires at least one line')
        super().__init__(
            '', role=role, tone=tone, wrap=True, max_lines=max_lines, **kwargs
        )
        self.bind(full_text=self._fit, width=self._fit, font_size=self._fit)
        self.full_text = text

    def _fit(self, *_args: object) -> None:
        """Measure wrapped prefixes without allocating a texture for the complete label."""
        text = self.full_text
        face = font_path(self._font_weight, text)
        measure = TextMeasure(
            text=text,
            font_name=face,
            font_size=self.font_size,
            text_size=(max(1, self.width), None),
            max_lines=self.max_lines + 1,
        )
        height_limit = self.max_lines * measure.get_extents('Ag')[1]
        if measure.render()[1] > height_limit:
            low, high = 0, len(text)
            while low < high:
                length = (low + high + 1) // 2
                measure.text = text[:length].rstrip() + '…'
                if measure.render()[1] <= height_limit:
                    low = length
                else:
                    high = length - 1
            text = text[:low].rstrip() + '…'
        self.text = text
        self.font_name = face
