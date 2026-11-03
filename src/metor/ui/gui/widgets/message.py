"""Content-sized native message bubbles with shared body-to-metadata spacing."""

from collections.abc import Callable

from kivy.core.text import Label as CoreLabel
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from metor.ui.gui.constants import Geometry
from metor.ui.gui.theme import font_path

# Local Package Imports
from .controls import Label, Panel
from .context import ContextAction
from .symbol import IconAction


class MessageBubble(BoxLayout):
    """Measures message content and preserves incoming/outgoing content edges."""

    def __init__(
        self,
        text: str,
        metadata: str,
        incoming: bool,
        delivery: str = 'drop',
        context: Callable[[], object] | None = None,
        **kwargs: object,
    ) -> None:
        """Builds one body/metadata unit without a stretched timeline height.

        Args:
            text: Plain canonical message body.
            metadata: Truthful status/timestamp.
            incoming: Direction used for edge alignment.
            delivery: Palette projection.
            context: Optional exact-item More action.
            kwargs: Native row properties.
        Returns:
            None
        """
        super().__init__(size_hint_y=None, **kwargs)
        surface = 'raised' if incoming else delivery + 'Surface'
        self._bubble = (
            ContextAction('Message actions', lambda: None, context, surface=surface)
            if context is not None
            else Panel(surface=surface)
        )
        self._bubble.clear_widgets()
        if isinstance(self._bubble, ContextAction):
            self._bubble.is_focusable = False
        self._bubble._rectangle.radius = [
            dp(16),
            dp(16),
            dp(16 if incoming else 4),
            dp(4 if incoming else 16),
        ]
        self._bubble.orientation = 'horizontal'
        right = dp(4 if context is not None else 16)
        self._bubble.padding = (dp(16), dp(8), right, dp(8))
        self._bubble.spacing = dp(4)
        self._bubble.size_hint = (None, None)
        self._content = BoxLayout(
            orientation='vertical',
            spacing=dp(4),
            size_hint_y=None,
            pos_hint={'center_y': 0.5},
        )
        self._content.bind(minimum_height=self._content.setter('height'))
        self._body = Label(text)
        self._metadata = Label(metadata, role='meta', tone='textSecondary')
        self._content.add_widget(self._body)
        self._content.add_widget(self._metadata)
        self._bubble.add_widget(self._content)
        if context is not None:
            self._bubble.add_widget(
                IconAction(
                    'ellipsis',
                    'Message actions',
                    context,
                    surface=surface,
                    tone='textSecondary',
                    pos_hint={'center_y': 0.5},
                )
            )
        self._bubble.bind(minimum_height=self._bubble.setter('height'))
        self._bubble.bind(height=self._height)
        if not incoming:
            self.add_widget(Widget())
        self.add_widget(self._bubble)
        if incoming:
            self.add_widget(Widget())
        self._inset_width = dp(16) + right
        if context is not None:
            self._inset_width += self._bubble.spacing + dp(Geometry.TARGET)
        self._natural_width: float = dp(Geometry.BUBBLE_MIN)
        self._measure_content(text, metadata)
        self.bind(width=self._width)
        self._width()

    def set_content(self, text: str, metadata: str) -> None:
        """Updates an existing chronological item without moving or recreating it.

        Args:
            text: Plain current message/recording description.
            metadata: Truthful status or duration.
        Returns:
            None
        """
        if self._body.text == text and self._metadata.text == metadata:
            return
        self._body.text = text
        self._metadata.text = metadata
        self._measure_content(text, metadata)
        self._width()

    def _measure_content(self, text: str, metadata: str) -> None:
        """Measures local font metrics for content-sized bubble width.

        Args:
            text: Plain body text.
            metadata: Plain support text.
        Returns:
            None
        """
        measured = CoreLabel(
            text=text, font_name=font_path(text=text), font_size=sp(15)
        )
        meta = CoreLabel(
            text=metadata, font_name=font_path(500, metadata), font_size=sp(11)
        )
        self._natural_width = (
            max(measured.render()[0], meta.render()[0]) + self._inset_width
        )

    def _width(self, *_args: object) -> None:
        """Reflows text at current width without shrinking glyphs.

        Args:
            _args: Native width event.
        Returns:
            None
        """
        maximum = min(dp(Geometry.BUBBLE_MAX), self.width * Geometry.BUBBLE_RATIO)
        self._bubble.width = min(
            maximum, max(dp(Geometry.BUBBLE_MIN), self._natural_width)
        )
        inner_width = max(0, self._bubble.width - self._inset_width)
        self._body.width = inner_width
        self._metadata.width = inner_width
        self._body.texture_update()
        self._metadata.texture_update()
        self._bubble.do_layout()
        self._content.do_layout()

    def _height(self, _widget: object, height: float) -> None:
        """Keeps timeline spacing outside the measured bubble.

        Args:
            _widget: Bubble property source.
            height: Measured composition height.
        Returns:
            None
        """
        self.height = height
