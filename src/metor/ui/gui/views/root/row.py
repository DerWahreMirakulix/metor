"""Identity-stable measured conversation rows with replaceable public metadata."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp, sp
from kivy.core.text import Label as TextMeasure
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController, ConversationRow
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Label, Panel
from metor.ui.gui.widgets.context import ContextAction
from metor.ui.gui.widgets.symbol import IconAction, Symbol

# Local Package Imports
from .actions import conversation_menu


class RootRow(BoxLayout):
    """Owns one canonical row; metadata changes do not recreate native input or focus targets."""

    def __init__(
        self,
        controller: GuiController,
        entry: ConversationRow,
        navigate: Callable[[Route], None],
        refresh: Callable[[], None],
    ) -> None:
        """Creates fixed identity callbacks and reusable measured content.

        Args:
            controller: Public projection/action owner.
            entry: Original canonical row and permitted metadata.
            navigate: Projection-only navigation.
            refresh: Native repaint request.
        Returns:
            None
        """
        super().__init__(size_hint_y=None, height=dp(84), spacing=dp(8))
        self.entry = entry
        route = Route(
            'V08' if entry.delivery is Delivery.DROP else 'V09',
            entry.peer,
            entry.delivery,
        )
        context = partial(
            conversation_menu, controller, entry.peer, entry.delivery, refresh
        )
        self.action = ContextAction(
            entry.label, partial(navigate, route), context, surface='surface'
        )
        self.action.padding = (dp(12), dp(16))
        self.action.remove_widget(self.action.label)
        self.action.focus_key = ('peer', entry.delivery.value, entry.peer)
        self.group = BoxLayout(spacing=dp(12))
        avatar = Panel(
            surface=entry.delivery.value + 'Surface',
            size_hint=(None, None),
            width=dp(48),
            height=dp(48),
            pos_hint={'center_y': 0.5},
        )
        avatar._rectangle.radius = [dp(24)]
        self.initials = Label('', role='row', tone=entry.delivery.value, wrap=False)
        self.initials.halign = 'center'
        avatar.add_widget(self.initials)
        self.group.add_widget(avatar)
        column = BoxLayout(orientation='vertical', spacing=dp(3))
        self.name_row = BoxLayout(size_hint_y=None, height=sp(22), spacing=dp(4))
        self.name = Label('', role='row', wrap=False)
        self.pin = Symbol('pin', tone='drop', size_hint_x=None, width=dp(24))
        self.name_row.add_widget(self.name)
        column.add_widget(self.name_row)
        self.detail = Label('', role='support', tone='textSecondary')
        column.add_widget(self.detail)
        self.group.add_widget(column)
        self.count = Label('', role='caption', tone='onAccent', wrap=False)
        self.count.halign = 'center'
        self.badge = Panel(
            surface=entry.delivery.value,
            size_hint=(None, None),
            height=max(dp(24), sp(16) + dp(8)),
            pos_hint={'center_y': 0.5},
        )
        self.badge.add_widget(self.count)
        self.action.add_widget(self.group)
        self.add_widget(self.action)
        more = IconAction(
            'ellipsis', 'Conversation actions', context, pos_hint={'center_y': 0.5}
        )
        more.focus_key = ('peer_more', entry.delivery.value, entry.peer)
        self.add_widget(more)
        self.detail.bind(height=self._measure)
        self.update(entry)

    def _measure(self, *_args: object) -> None:
        """Grows metadata without changing canonical input controls.

        Args:
            _args: Native text measurement callback.
        Returns:
            None
        """
        self.action.height = self.height = max(
            dp(84), dp(35) + self.name_row.height + self.detail.height
        )

    def update(self, entry: ConversationRow) -> None:
        """Replaces displayed metadata only for the original identity.

        Args:
            entry: Current authorized projection with the same peer and delivery.
        Returns:
            None
        """
        if (entry.peer, entry.delivery) != (self.entry.peer, self.entry.delivery):
            raise ValueError('Conversation row identity changed')
        self.entry = entry
        self.name.text = self.action.label.text = entry.label
        self.initials.text = ''.join(
            word[0] for word in entry.label.split()[:2] if word
        ).upper()
        if entry.pinned and self.pin.parent is None:
            self.name_row.add_widget(self.pin)
        elif not entry.pinned and self.pin.parent is not None:
            self.name_row.remove_widget(self.pin)
        status = (
            'New Drops'
            if entry.unseen and entry.delivery is Delivery.DROP
            else entry.status
        )
        if entry.pending:
            status += f' · {entry.pending} pending'
        self.detail.text = status
        self.count.text = str(entry.unseen)
        if entry.unseen:
            measure = TextMeasure(
                text=self.count.text,
                font_name=self.count.font_name,
                font_size=self.count.font_size,
            )
            measure.refresh()
            self.badge.width = measure.texture.size[0] + dp(12)
            if self.badge.parent is None:
                self.group.add_widget(self.badge)
        elif self.badge.parent is not None:
            self.group.remove_widget(self.badge)
        self._base_accessible_name = (
            entry.label
            + ': '
            + status
            + (f', {entry.unseen} unseen' if entry.unseen else '')
            + (', pinned' if entry.pinned else '')
        )
        self.action.accessible_name = self._base_accessible_name
        self._measure()

    def select(self, route: Route) -> None:
        """Shows the open detail separately from the transient keyboard focus.

        Args:
            route: Current foreground route.
        Returns:
            None
        """
        selected = (
            route.view == ('V08' if self.entry.delivery is Delivery.DROP else 'V09')
            and route.peer == self.entry.peer
            and route.delivery is self.entry.delivery
        )
        self.action.surface = (
            self.entry.delivery.value + 'Surface' if selected else 'surface'
        )
        self.action.accessible_name = self._base_accessible_name + (
            ', open conversation' if selected else ''
        )
        self.action._feedback()
