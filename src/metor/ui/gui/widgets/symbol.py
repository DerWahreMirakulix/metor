"""Offline Lucide vector symbols with explicit accessible action names."""

from collections.abc import Callable

from kivy.graphics import PopMatrix, PushMatrix, Scale, Translate, Color, Ellipse
from kivy.graphics.svg import Svg
from kivy.metrics import dp
from kivy.uix.widget import Widget
from kivy.properties import StringProperty

from metor.ui.gui.theme import ASSET_ROOT, color

# Local Package Imports
from .controls import Action


class Symbol(Widget):
    """Renders a packaged SVG at the normative 24-unit viewbox size."""

    tone = StringProperty('text')

    def __init__(self, name: str, tone: str = 'text', **kwargs: object) -> None:
        """Loads only a fixed local asset name supplied by application code.

        Args:
            name: Packaged symbol filename stem.
            tone: Palette role.
            kwargs: Layout properties.
        Returns:
            None
        """
        super().__init__(**kwargs)
        self.tone = tone
        path = ASSET_ROOT / 'icons' / f'{name}-native.svg'
        if path.parent != ASSET_ROOT / 'icons' or not path.is_file():
            raise ValueError('Unknown local symbol')
        with self.canvas:
            PushMatrix()
            self._translate = Translate()
            self._scale = Scale(dp(1), dp(1), 1)
            self._svg = Svg(str(path))
            PopMatrix()
        self.bind(center_x=self._place, center_y=self._place)
        self._place()
        self.bind(tone=self._retone)
        self._retone()

    def _retone(self, *_args: object) -> None:
        """Updates SVG currentColor from the semantic palette, including disabled state.

        Args:
            _args: Native property update.
        Returns:
            None
        """
        self._svg.color = color(self.tone)

    def _place(self, *_args: object) -> None:
        """Centers the visible symbol inside its larger hit target.

        Args:
            _args: Geometry event.
        Returns:
            None
        """
        self._translate.x = self.center_x - dp(12)
        self._translate.y = self.center_y - dp(12)


class IconAction(Action):
    """48-unit ordinary action with a vector and separate safe semantic name."""

    def __init__(
        self,
        symbol: str,
        label: str,
        callback: Callable[[], object],
        surface: str = 'raised',
        tone: str = 'text',
        badge: bool = False,
        **kwargs: object,
    ) -> None:
        """Creates a fixed icon target without an emoji/font dependency.

        Args:
            symbol: Local asset stem.
            label: Accessible purpose.
            callback: Explicit action.
            surface: Named action surface color.
            tone: Named text and vector color.
            badge: Whether a content-free unseen-activity dot is attached.
            kwargs: Native layout properties.
        Returns:
            None
        """
        super().__init__(
            label,
            callback,
            surface=surface,
            tone=tone,
            size_hint_x=None,
            width=dp(48),
            **kwargs,
        )
        self.remove_widget(self.label)
        self.label.text = ''
        self.symbol = Symbol(symbol, tone=tone)
        self.add_widget(self.symbol)
        self.bind(disabled=self._symbol_state)
        self._symbol_state()
        if badge:
            with self.canvas.after:
                Color(*color('drop'))
                self._badge = Ellipse(size=(dp(8), dp(8)))
            self.bind(pos=self._badge_position, size=self._badge_position)
            self._badge_position()

    def _symbol_state(self, *_args: object) -> None:
        """Keeps icon eligibility feedback consistent with its action label.

        Args:
            _args: Native disabled-state update.
        Returns:
            None
        """
        self.symbol.tone = 'textDisabled' if self.disabled else self._tone

    def _badge_position(self, *_args: object) -> None:
        """Anchors unseen activity to the moving Notifications target.

        Args:
            _args: Native geometry update.
        Returns:
            None
        """
        self._badge.pos = self.right - dp(12), self.top - dp(12)
