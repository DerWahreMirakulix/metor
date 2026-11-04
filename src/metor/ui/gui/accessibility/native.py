"""AccessKit platform adapters consume immutable projections, never native widgets."""

import os
import platform
from typing import Any

import accesskit

# Local Package Imports
from .model import AccessibleAction, AccessibleRole, AccessibleState


class NativeAccessibility:
    """Owns the native accessibility tree for exactly one GUI window."""

    def __init__(
        self,
        state: AccessibleState,
        window_handle: int | None,
        *,
        simulator: bool = False,
    ) -> None:
        """Registers only the platform implementation available in this process.

        Args:
            state: Thread-safe, revocable visible projection.
            window_handle: Windows HWND, absent on other platforms.
            simulator: Explicit deployment identity, with no profile or peer metadata.
        Returns:
            None
        """
        self.state = state
        self.adapter: Any = None
        self.system = platform.system()
        self.status = 'unavailable'
        self.title = 'Metor · Simulator' if simulator else 'Metor'
        if self.system == 'Windows' and window_handle is not None:
            self.adapter = accesskit.windows.SubclassingAdapter(
                window_handle, self._tree, self._action
            )
        elif self.system == 'Linux' and os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            self.adapter = accesskit.unix.Adapter(
                self._tree, self._action, self._deactivate
            )
        if self.adapter is not None:
            self.status = 'registered'

    def _tree(self) -> Any:
        """Builds a complete replacement with no reference to UI-thread objects.

        Args:
            None
        Returns:
            TreeUpdate: Current visible tree, or a content-free privacy root.
        """
        snapshot = self.state.read()
        update = accesskit.TreeUpdate(snapshot.focus * 2)
        update.tree = accesskit.Tree(0)
        root = accesskit.Node(accesskit.Role.WINDOW)
        root.set_label(self.title)
        root.set_bounds(accesskit.Rect(0, 0, snapshot.width, snapshot.height))
        root.set_children([item.identity * 2 for item in snapshot.nodes])
        update.nodes.append((0, root))
        roles = {
            AccessibleRole.LABEL: accesskit.Role.LABEL,
            AccessibleRole.BUTTON: accesskit.Role.BUTTON,
            AccessibleRole.TEXT: accesskit.Role.TEXT_INPUT,
            AccessibleRole.PASSWORD: accesskit.Role.PASSWORD_INPUT,
        }
        for item in snapshot.nodes:
            node = accesskit.Node(roles[item.role])
            node.set_label(item.name)
            if item.role is AccessibleRole.LABEL:
                node.set_value(item.name)
            node.set_bounds(accesskit.Rect(*item.bounds))
            if item.value is not None:
                node.set_value(item.value)
            if not item.enabled:
                node.set_disabled()
            if item.focusable:
                node.add_action(accesskit.Action.FOCUS)
            if item.clickable:
                node.add_action(accesskit.Action.CLICK)
            if item.editable:
                node.add_action(accesskit.Action.SET_VALUE)
            if item.readonly:
                node.set_read_only()
            identity = item.identity * 2
            if item.role is AccessibleRole.TEXT and item.value is not None:
                text = accesskit.Node(accesskit.Role.TEXT_RUN)
                text.set_value(item.value)
                text.set_bounds(accesskit.Rect(*item.bounds))
                text.set_character_lengths(
                    [len(character.encode('utf-8')) for character in item.value]
                )
                node.set_children([identity + 1])
                update.nodes.append((identity + 1, text))
            update.nodes.append((identity, node))
        return update

    def _action(self, request: Any) -> None:
        """Queues only finite advertised operations; never invokes widgets off-thread.

        Args:
            request: Native AccessKit action.
        Returns:
            None
        """
        if request.target % 2:
            return
        target = request.target // 2
        action = None
        if request.action == accesskit.Action.FOCUS:
            action = AccessibleAction.FOCUS
        elif request.action == accesskit.Action.CLICK:
            action = AccessibleAction.CLICK
        elif request.action == accesskit.Action.SET_VALUE:
            data = request.data
            if (
                isinstance(data, tuple)
                and len(data) == 2
                and data[0] == accesskit.ActionDataKind.VALUE
                and isinstance(data[1], str)
            ):
                self.state.request(target, AccessibleAction.SET_VALUE, data[1])
            return
        if action is not None:
            self.state.request(target, action)

    def _deactivate(self) -> None:
        """Leaves data ownership with the GUI privacy barrier across AT reconnects.

        Args:
            None
        Returns:
            None
        """

    def update(self) -> None:
        """Synchronously replaces active native nodes, including on privacy revocation.

        Args:
            None
        Returns:
            None
        """
        if self.adapter is not None:
            events = self.adapter.update_if_active(self._tree)
            if events is not None:
                events.raise_events()

    def focus(self, focused: bool) -> None:
        """Reports Unix window focus; Windows obtains it through HWND subclassing.

        Args:
            focused: Actual native window focus.
        Returns:
            None
        """
        if self.adapter is not None and self.system == 'Linux':
            self.adapter.update_window_focus_state(focused)

    def close(self) -> None:
        """Removes all content before releasing the native platform registration.

        Args:
            None
        Returns:
            None
        """
        self.state.revoke()
        self.update()
        self.adapter = None
        self.status = 'closed'
