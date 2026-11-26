"""Fixed-size conversation avatars that show complete, renderable initials."""

import unicodedata

from kivy.core.text import Label as TextMeasure
from kivy.metrics import Metrics, dp, sp
from kivy.properties import StringProperty

from metor.ui.gui.theme import TYPE, initial_font
from metor.ui.gui.widgets import Label, Panel
from metor.ui.gui.widgets.symbol import Symbol


def _initial(word: str) -> str:
    """Keep a leading letter or number together with its combining marks."""
    if not word[0].isalnum():
        return ''
    end = 1
    while end < len(word) and unicodedata.category(word[end]).startswith('M'):
        end += 1
    if word[end : end + 1] == '\u200d':
        return ''
    return word[:end].upper()


class ConversationAvatar(Panel):
    """Fit short monograms inside the existing circle without growing the row."""

    alias = StringProperty('')

    def __init__(self, tone: str, alias: str) -> None:
        """Place the avatar beside the row's separately accessible full name."""
        super().__init__(
            surface=tone + 'Surface',
            size_hint=(None, None),
            size=('40dp', '40dp'),
            pos_hint={'center_y': 0.5},
        )
        self.initials = Label('', role='row', tone=tone, wrap=False)
        self.initials.halign = 'center'
        self.initials.shorten = False
        self._tone = tone
        self.fallback: Symbol | None = None
        self.alias = alias
        self.bind(alias=self._fit, size=self._fit)
        Metrics.bind(fontscale=self._fit)
        self._fit()

    def _fit(self, *_args: object) -> None:
        """Prefer two complete initials, then one, then the local contact symbol."""
        self._rectangle.radius = [min(self.size) / 2]
        size = min(sp(TYPE['row'][0]), dp(24))
        words = unicodedata.normalize('NFC', self.alias).split(maxsplit=2)
        initials = [_initial(word) for word in words[:2]]
        chosen = ''
        for text in dict.fromkeys((''.join(initials), *initials)):
            if not text or (face := initial_font(text)) is None:
                continue
            width, height = TextMeasure(font_name=face, font_size=size).get_extents(
                text
            )
            if width <= self.width - dp(8) and height <= self.height - dp(4):
                chosen = text
                break
        self.initials.font_size = size
        self.initials.text = chosen
        if not chosen and self.fallback is None:
            self.fallback = Symbol('user-round', tone=self._tone)
        visible = self.initials if chosen else self.fallback
        assert visible is not None
        if visible.parent is not self:
            self.clear_widgets()
            self.add_widget(visible)
