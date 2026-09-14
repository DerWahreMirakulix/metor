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
        self._bubble = Panel(
            surface='raised' if incoming else delivery + 'Surface',
            orientation='vertical',
            padding=(dp(16), dp(12), dp(16), dp(10)),
            spacing=dp(4),
            size_hint=(None, None),
        )
        self._body = Label(text)
        self._metadata = Label(metadata, role='meta', tone='textSecondary')
        self._bubble.add_widget(self._body)
        self._bubble.add_widget(self._metadata)
        self._bubble.bind(minimum_height=self._bubble.setter('height'))
        self._bubble.bind(height=self._height)
        if not incoming:
            self.add_widget(Widget())
        self.add_widget(self._bubble)
        if incoming:
            self.add_widget(Widget())
        if context is not None:
            self.add_widget(
                IconAction(
                    'ellipsis', 'Message actions', context, pos_hint={'center_y': 0.5}
                )
            )
        self._natural_width: float = dp(Geometry.BUBBLE_MIN)
        self._measure_content(text, metadata)
        self.bind(width=self._width)

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
        measured = CoreLabel(text=text, font_name=font_path(), font_size=sp(15))
        measured.refresh()
        meta = CoreLabel(text=metadata, font_name=font_path(500), font_size=sp(11))
        meta.refresh()
        self._natural_width = max(measured.texture.size[0], meta.texture.size[0]) + dp(
            32
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

    def _height(self, _widget: object, height: float) -> None:
        """Keeps timeline spacing outside the measured bubble.

        Args:
            _widget: Bubble property source.
            height: Measured composition height.
        Returns:
            None
        """
        self.height = height
