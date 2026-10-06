"""Stable responsive LIVE header action with explicit keyboard and tooltip semantics."""

from collections.abc import Callable

from kivy.core.text import Label as CoreLabel
from kivy.metrics import dp

from metor.ui.gui.widgets.symbol import IconAction


class LiveHeaderAction(IconAction):
    """Switches one fixed action between icon and text without replacing its input owner."""

    def __init__(
        self,
        label: str,
        symbol: str,
        callback: Callable[[], object],
        *,
        tone: str = 'text',
        surface: str = 'raised',
    ) -> None:
        """Binds immutable action identity while allowing width-only visual reflow."""
        super().__init__(symbol, label, callback, tone=tone, surface=surface)
        self.label.text = label
        self.label.shorten = False
        self._show_text = False
        self._measurement: tuple[str, str, float] | None = None
        self._text_width = dp(48)

    def present(self, *, compact: bool) -> None:
        """Keeps the same keyboard target and exact action callback across widths."""
        show_text = not compact
        if show_text != self._show_text:
            self.remove_widget(self.symbol if show_text else self.label)
            self.add_widget(self.label if show_text else self.symbol)
            self._show_text = show_text
        if compact:
            self.width = dp(48)
        else:
            key = self.label.text, self.label.font_name, self.label.font_size
            if key != self._measurement:
                measured = CoreLabel(
                    text=self.label.text,
                    font_name=self.label.font_name,
                    font_size=self.label.font_size,
                )
                measured.refresh()
                self._text_width = max(dp(48), measured.texture.size[0] + dp(24))
                self._measurement = key
            self.width = self._text_width
