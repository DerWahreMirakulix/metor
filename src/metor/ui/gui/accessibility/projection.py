"""UI-thread projection of visible controls with stable weak widget identities."""

from weakref import WeakKeyDictionary, WeakValueDictionary

from kivy.core.window import Window
from kivy.uix.behaviors import ButtonBehavior, FocusBehavior
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from metor.ui.gui.widgets.controls import Action
from metor.ui.gui.widgets.ptt import PttAction

# Local Package Imports
from .model import (
    AccessibleAction,
    AccessibleNode,
    AccessibleRequest,
    AccessibleRole,
    AccessibleSnapshot,
)


class Projection:
    """Reads visible native widgets; no widget reference crosses to an AT thread."""

    def __init__(self) -> None:
        """Creates monotonically allocated identities without retaining removed widgets.

        Args:
            None
        Returns:
            None
        """
        self._identities: WeakKeyDictionary[Widget, int] = WeakKeyDictionary()
        self._targets: WeakValueDictionary[int, Widget] = WeakValueDictionary()
        self._next_identity = 1

    def capture(self, root: Widget) -> AccessibleSnapshot:
        """Projects clipped visible labels and controls in geometric reading order.

        Args:
            root: Foreground application or modal root.
        Returns:
            AccessibleSnapshot: Plain immutable native-window-relative data.
        """
        nodes: list[AccessibleNode] = []
        focus = 0
        self._targets.clear()
        for widget in root.walk():
            bounds = self._bounds(widget, root)
            if bounds is None:
                continue
            role: AccessibleRole
            value: str | None = None
            if isinstance(widget, TextInput):
                role = (
                    AccessibleRole.PASSWORD if widget.password else AccessibleRole.TEXT
                )
                name = widget.hint_text or (
                    'Password' if widget.password else 'Text input'
                )
                value = None if widget.password else widget.text
            elif isinstance(widget, ButtonBehavior):
                role = AccessibleRole.BUTTON
                name = str(
                    getattr(widget, 'accessible_name', getattr(widget, 'text', ''))
                )
            elif isinstance(widget, Label):
                if isinstance(widget.parent, Action) and widget is widget.parent.label:
                    continue
                if widget.color[3] <= 0:
                    continue
                role, name = AccessibleRole.LABEL, widget.text
            else:
                continue
            if not name and value is None:
                continue
            identity = self._identities.get(widget)
            if identity is None:
                identity = self._next_identity
                self._next_identity += 1
                self._identities[widget] = identity
            self._targets[identity] = widget
            focusable = isinstance(widget, FocusBehavior) and widget.is_focusable
            if focusable and widget.focus:
                focus = identity
            nodes.append(
                AccessibleNode(
                    identity=identity,
                    role=role,
                    name=name,
                    bounds=bounds,
                    value=value,
                    enabled=not widget.disabled,
                    focusable=focusable,
                    clickable=isinstance(widget, ButtonBehavior)
                    and not isinstance(widget, PttAction),
                    editable=isinstance(widget, TextInput)
                    and not widget.password
                    and not widget.readonly,
                    readonly=isinstance(widget, TextInput) and widget.readonly,
                )
            )
        nodes.sort(key=lambda item: (item.bounds[1], item.bounds[0], item.identity))
        return AccessibleSnapshot(
            tuple(nodes), focus, float(Window.width), float(Window.height)
        )

    @staticmethod
    def _bounds(
        widget: Widget, root: Widget
    ) -> tuple[float, float, float, float] | None:
        """Rejects hidden or fully clipped widgets before copying any private text.

        Args:
            widget: Candidate semantic control.
            root: Foreground boundary.
        Returns:
            tuple | None: Clipped client bounds, or no visible presentation.
        """
        x, y = widget.to_window(*widget.pos)
        left, bottom = max(0.0, x), max(0.0, y)
        right, top = (
            min(float(Window.width), x + widget.width),
            min(float(Window.height), y + widget.height),
        )
        parent: Widget | None = widget
        while isinstance(parent, Widget):
            if parent.opacity <= 0:
                return None
            if isinstance(parent, ScrollView):
                px, py = parent.to_window(*parent.pos)
                left, bottom = max(left, px), max(bottom, py)
                right, top = min(right, px + parent.width), min(top, py + parent.height)
            if parent is root:
                break
            parent = parent.parent
        else:
            return None
        if right <= left or top <= bottom:
            return None
        return left, float(Window.height) - top, right, float(Window.height) - bottom

    def invoke(self, request: AccessibleRequest, root: Widget) -> bool:
        """Revalidates exact attached targets before invoking ordinary native semantics.

        Args:
            request: Previously admitted request from a native thread.
            root: Current foreground root, excluding background modal content.
        Returns:
            bool: Whether a current enabled control accepted the action.
        """
        widget = self._targets.get(request.target)
        if widget is None or widget.disabled or self._bounds(widget, root) is None:
            return False
        if request.action is AccessibleAction.FOCUS and isinstance(
            widget, FocusBehavior
        ):
            widget.focus = True
            return True
        if (
            request.action is AccessibleAction.CLICK
            and isinstance(widget, ButtonBehavior)
            and not isinstance(widget, PttAction)
        ):
            widget.dispatch('on_release')
            return True
        if (
            request.action is AccessibleAction.SET_VALUE
            and isinstance(widget, TextInput)
            and not widget.password
            and not widget.readonly
            and request.value is not None
        ):
            widget.text = request.value
            return True
        return False

    def revoke(self) -> None:
        """Drops every actionable target on privacy or presentation-context changes.

        Args:
            None
        Returns:
            None
        """
        self._targets.clear()
