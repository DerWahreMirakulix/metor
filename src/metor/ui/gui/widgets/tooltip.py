"""Pointer-only hints whose canvas lifetime is confined to their owning action."""

from typing import TYPE_CHECKING, ClassVar
from weakref import WeakSet

from kivy.clock import Clock, ClockEvent
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.widget import Widget

from metor.ui.gui.constants import Geometry, GuiLimits
from metor.ui.gui.theme import color

# Local Package Imports
from .controls import Label

if TYPE_CHECKING:
    from .symbol import IconAction


class PointerTooltip:
    """Draws in the owner's root canvas, never in a detached OS/window overlay."""

    _instances: ClassVar[WeakSet['PointerTooltip']] = WeakSet()

    def __init__(self, owner: 'IconAction') -> None:
        """Creates an inert hint without retaining a copy of the action label.

        Args:
            owner: Exact action whose lifecycle and privacy cover control visibility.
        Returns:
            None
        """
        self.owner = owner
        self.label: Label | None = None
        self._pending: ClockEvent | None = None
        self._canvas_owner: Widget | None = None
        self.visible = False
        self._instances.add(self)
        owner.bind(
            parent=self.cancel,
            disabled=self.cancel,
            pos=self.cancel,
            size=self.cancel,
            on_press=self.cancel,
        )

    @classmethod
    def clear_all(cls) -> None:
        """Revokes pending and visible hints before a privacy cover or window departure.

        Args:
            None
        Returns:
            None
        """
        for tooltip in tuple(cls._instances):
            tooltip.cancel()

    def hover(self, hovered: bool) -> None:
        """Schedules a hint only while its native pointer target remains attached.

        Args:
            hovered: Current pointer hit result from the owner.
        Returns:
            None
        """
        if not hovered or self.owner.disabled:
            self.cancel()
        elif not self.visible and self._pending is None:
            self._pending = Clock.schedule_once(self._show, GuiLimits.TOOLTIP_SECONDS)

    def cancel(self, *_args: object) -> None:
        """Removes pixels immediately and drops transient hint text on departure.

        Args:
            _args: Optional native lifetime or interaction event.
        Returns:
            None
        """
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        if self.visible and self.label is not None and self._canvas_owner is not None:
            self._canvas_owner.canvas.after.remove(self.label.canvas)
        self._canvas_owner = None
        self.visible = False
        if self.label is not None:
            self.label.text = ''
        self.label = None

    def _show(self, _elapsed: float) -> None:
        """Paints the current safe action name without activating or focusing it.

        Args:
            _elapsed: Native pointer dwell duration.
        Returns:
            None
        """
        self._pending = None
        owner = self.owner
        if owner.disabled or not owner._hovered or owner.get_root_window() is None:
            self.cancel()
            return
        root: Widget = owner
        while isinstance(root.parent, Widget):
            root = root.parent
        if Window.children and root is not Window.children[0]:
            self.cancel()
            return
        maximum_width = min(dp(Geometry.TOOLTIP_MAX), Window.width - dp(16))
        label = Label(owner.accessible_name, role='support', size_hint=(None, None))
        label.padding = (dp(8), dp(6))
        label.text_size = (None, None)
        label.texture_update()
        width = min(maximum_width, max(dp(48), label.texture_size[0]))
        label.width = width
        label.text_size = (width, None)
        label.texture_update()
        label.height = max(dp(32), label.texture_size[1])
        x, y = owner.to_window(owner.x, owner.y)
        x = max(dp(8), min(x, Window.width - width - dp(8)))
        y = y - label.height - dp(6)
        if y < dp(8):
            _, y = owner.to_window(owner.x, owner.top)
            y += dp(6)
        y = max(dp(8), min(y, Window.height - label.height - dp(8)))
        label.pos = root.to_widget(x, y, relative=False)
        with label.canvas.before:
            Color(*color('raised'))
            RoundedRectangle(pos=label.pos, size=label.size, radius=[dp(8)])
        root.canvas.after.add(label.canvas)
        self._canvas_owner = root
        self.label = label
        self.visible = True
