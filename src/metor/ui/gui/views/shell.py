"""Responsive root/master-detail composition preserving one foreground route."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget

from metor.core.api import Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Label
from metor.ui.gui.theme import color

# Local Package Imports
from .entry import entry_view
from .root import root_view
from .peer import PeerView
from .secondary import secondary_view
from .contacts import ContactListView
from .security import security_view, LockedActivity


class Shell(BoxLayout):
    """Owns content edges and responsive panels without changing domain state."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], **kwargs: object
    ) -> None:
        """Creates the application shell after toolkit setup.

        Args:
            controller: Toolkit-independent state and public operations.
            refresh: Native repaint request.
            kwargs: Native layout properties.
        Returns:
            None
        """
        super().__init__(orientation='horizontal', **kwargs)
        self.controller = controller
        self.refresh = refresh
        self._private_render_key: tuple[object, ...] | None = None
        self._peer_key: tuple[object, ...] | None = None
        self._peer_panel: PeerView | None = None
        self._contacts_panel: ContactListView | None = None
        self._contacts_key: tuple[object, ...] | None = None
        self._master: BoxLayout | None = None
        self._master_key: tuple[object, ...] | None = None
        self._detail: BoxLayout | None = None
        self._security_panel: AnchorLayout | None = None
        self.keyboard_inset: float = 0
        with self.canvas.before:
            Color(*color('background'))
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._bounds, size=self._bounds)

    def _bounds(self, *_args: object) -> None:
        """Keeps viewport pixels opaque in the window and exported fixtures.

        Args:
            _args: Native bounds callback.
        Returns:
            None
        """
        self._background.pos = self.pos
        self._background.size = self.size

    def render(self) -> None:
        """Recomposes foreground panels from current authorized state.

        Args:
            None
        Returns:
            None
        """
        if self.width < dp(
            Geometry.MIN_WIDTH
        ) or self.height + self.keyboard_inset < dp(Geometry.MIN_HEIGHT):
            self._private_render_key = None
            self._peer_key = None
            self._peer_panel = None
            self._contacts_panel = None
            self._contacts_key = None
            self._master = None
            self.controller.voice.depart()
            self.controller.playback.stop()
            self.clear_widgets()
            self.add_widget(Label('Increase the window size or reduce display scaling'))
            return
        state = self.controller.state
        if self._security_panel is not None:
            for widget in self._security_panel.walk():
                if isinstance(widget, LockedActivity):
                    widget.update()
        prompt = self.controller.interactions.prompt
        wide = self.width >= dp(Geometry.BREAKPOINT)
        peer_key = (state.generation, state.route, wide)
        if (
            not state.covered
            and prompt is None
            and state.route.view in {'V08', 'V09'}
            and peer_key == self._peer_key
            and self._peer_panel is not None
        ):
            self._peer_panel.update()
            master_key = self._root_key()
            if wide and master_key != self._master_key and self._master is not None:
                self.remove_widget(self._master)
                self._master = self._root()
                self._master.size_hint_x = None
                self._master.width = dp(Geometry.MASTER)
                self.add_widget(self._master, index=len(self.children))
                self._master_key = master_key
            return
        if (
            not state.covered
            and prompt is None
            and state.route.view in {'V11', 'V12'}
            and peer_key == self._contacts_key
            and self._contacts_panel is not None
        ):
            self._contacts_panel.update()
            master_key = self._root_key()
            if wide and master_key != self._master_key and self._master is not None:
                self.remove_widget(self._master)
                self._master = self._root()
                self._master.size_hint_x = None
                self._master.width = dp(Geometry.MASTER)
                self.add_widget(self._master, index=len(self.children))
                self._master_key = master_key
            return
        private = (
            state.covered
            or state.route.view
            in {'V02', 'V03', 'V04', 'V12', 'V13', 'V17', 'V18', 'V19', 'V20', 'V21'}
            or prompt is not None
        )
        if private:
            key = (
                state.generation,
                state.route,
                id(state.snapshot)
                if state.route.view in {'V11', 'V12', 'V13', 'V15'}
                else None,
                (controller_form.serial, controller_form.error, controller_form.unknown)
                if (controller_form := self.controller.contacts.form)
                else None,
                state.busy,
                state.status,
                id(prompt),
                id(self.controller.security.restriction),
                state.preferences.preferences_revision if state.preferences else None,
                self.controller.core_settings.revision,
                self.controller.history.revision,
                self.controller.profiles.revision,
                id(self.controller.voice.routes.endpoints),
                self.controller.voice.routes.scanned,
                self.controller.voice.headset_confirmed,
                self.width >= dp(Geometry.BREAKPOINT),
            )
            if key == self._private_render_key:
                return
            self._private_render_key = key
        else:
            self._private_render_key = None
        contact_search_focused = bool(
            self._contacts_panel is not None
            and self._contacts_panel.search.focus
            and self._contacts_panel.route == state.route
            and not state.covered
        )
        self.clear_widgets()
        self._peer_key = None
        self._peer_panel = None
        self._contacts_panel = None
        self._contacts_key = None
        self._master = None
        self._detail = None
        self._security_panel = None
        if self.controller.interactions.prompt is not None:
            self.add_widget(entry_view(self.controller, self.refresh))
            return
        if state.route.view in ('V04', 'V05'):
            self._security_panel = security_view(self.controller, self.refresh)
            self.add_widget(self._security_panel)
            return
        if state.covered:
            self.add_widget(entry_view(self.controller, self.refresh))
            return
        wide = self.width >= dp(Geometry.BREAKPOINT)
        root = state.route.view in ('V06', 'V07')
        if wide or root:
            master = self._root()
            if wide:
                self._master = master
                self._master_key = self._root_key()
                master.size_hint_x = None
                master.width = dp(Geometry.MASTER)
            self.add_widget(
                master if wide else self._center(master, Geometry.COMPACT_MAX)
            )
            if wide:
                divider = Widget(size_hint_x=None, width=dp(Geometry.DIVIDER))
                with divider.canvas:
                    Color(*color('line'))
                    line = Rectangle(pos=divider.pos, size=divider.size)
                divider.bind(
                    pos=lambda widget, value: setattr(line, 'pos', value),
                    size=lambda widget, value: setattr(line, 'size', value),
                )
                self.add_widget(divider)
        if wide or not root:
            panel = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(16))
            self._detail = panel
            if self.keyboard_inset:
                panel.padding[3] = dp(Geometry.KEYBOARD_GAP)
            if root:
                panel.add_widget(Label('Choose a conversation', tone='textSecondary'))
            elif state.route.view in ('V08', 'V09'):
                self._peer_key = peer_key
                self._peer_panel = PeerView(self.controller, self.refresh, wide=wide)
                panel.add_widget(self._peer_panel)
            else:
                secondary = secondary_view(self.controller, self.refresh)
                panel.add_widget(secondary)
                if isinstance(secondary, ContactListView):
                    self._contacts_panel = secondary
                    self._contacts_key = peer_key
            self.add_widget(
                self._center(panel, Geometry.WIDE_MAX if wide else Geometry.COMPACT_MAX)
            )
            if self._contacts_panel is not None and contact_search_focused:
                self._contacts_panel.search.focus = True

    def set_input_inset(self, height: float) -> None:
        """Reserves keyboard height without replacing focused peer controls.

        Args:
            height: Native logical-pixel dock inset; zero restores the ordinary edge.
        Returns:
            None
        """
        self.keyboard_inset = height
        if self._detail is not None:
            self._detail.padding[3] = dp(
                Geometry.KEYBOARD_GAP if height else Geometry.EDGE
            )

    @staticmethod
    def _center(panel: BoxLayout, content_width: int) -> AnchorLayout:
        """Caps one foreground column while preserving its 24-unit inner edges.

        Args:
            panel: Foreground panel including its own edge padding.
            content_width: Maximum usable content width.
        Returns:
            AnchorLayout: Centered native layout owner.
        """
        wrapper = AnchorLayout(anchor_x='center', anchor_y='center')
        panel.size_hint_x = None
        wrapper.bind(
            width=lambda owner, width: setattr(
                panel, 'width', min(width, dp(content_width + Geometry.EDGE * 2))
            )
        )
        wrapper.add_widget(panel)
        return wrapper

    def inset_locked_media(self, bottom: float) -> None:
        """Keeps the unlock form scrollable above the visible continued-media controls.

        Args:
            bottom: Overlay extent in native logical pixels, including separation.
        Returns:
            None
        """
        if (
            self._security_panel is not None
            and self.controller.state.route.view == 'V05'
        ):
            self._security_panel.padding = (
                dp(24),
                dp(24),
                dp(24),
                max(dp(24), bottom - self.keyboard_inset),
            )

    def _go(self, route: Route) -> None:
        """Navigates through the presentation boundary.

        Args:
            route: Explicit destination.
        Returns:
            None
        """
        self.controller.navigate(route)
        self.refresh()

    def _tab(self, delivery: Delivery) -> None:
        """Changes only the root projection, preserving wide peer focus.

        Args:
            delivery: Selected root mode.
        Returns:
            None
        """
        state = self.controller.state
        state.root_delivery = delivery
        if state.route.view in ('V06', 'V07'):
            state.route = Route(
                'V06' if delivery == Delivery.DROP else 'V07', delivery=delivery
            )
        self.refresh()

    def _root_key(self) -> tuple[object, ...]:
        """Invalidates root presentation for pins, page changes and current Core metadata.

        Args:
            None
        Returns:
            tuple[object, ...]: Root-only repaint identity, leaving peer input intact.
        """
        state = self.controller.state
        return (
            id(state.snapshot),
            state.root_delivery,
            state.status,
            self.controller.notifications.store.revision,
            state.preferences.preferences_revision if state.preferences else None,
            state.root_pages.get(state.root_delivery, 0),
            tuple(conversation_rows(self.controller, state.root_delivery)),
        )

    def _root(self) -> BoxLayout:
        """Builds a bounded root page without replacing an existing wide peer pane.

        Args:
            None
        Returns:
            BoxLayout: Current DROP/LIVE root composition.
        """
        return root_view(self.controller, self._go, self._tab, self.refresh)
