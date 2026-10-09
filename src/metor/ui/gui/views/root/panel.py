"""Paged root composition retaining native rows across public metadata updates."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, ActionRow, Label
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from .row import RootRow


class RootPanel(BoxLayout):
    """Keeps a bounded page of identity-stable rows and fixed root controls."""

    def __init__(
        self,
        controller: GuiController,
        navigate: Callable[[Route], None],
        tab: Callable[[Delivery], None],
        refresh: Callable[[], None],
    ) -> None:
        """Builds the root shell once for its projection/page context.

        Args:
            controller: Current public GUI state owner.
            navigate: Projection-only navigation.
            tab: Root selector callback.
            refresh: Native repaint request.
        Returns:
            None
        """
        super().__init__(orientation='vertical', padding=dp(24), spacing=dp(16))
        self.controller, self.navigate, self.refresh = controller, navigate, refresh
        self.rows: dict[str, RootRow] = {}
        state = controller.state
        self.delivery = state.root_delivery
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        header.add_widget(Label('METOR', role='wordmark', wrap=False))
        self.header_actions: dict[str, IconAction] = {}
        for icon, title, view in (
            ('bell', 'Notifications', 'V16'),
            ('users', 'Contacts', 'V12'),
            ('settings', 'Settings', 'V17'),
        ):
            action = IconAction(icon, title, partial(navigate, Route(view)))
            action.focus_key = ('header', view)
            self.header_actions[view] = action
            header.add_widget(action)
            if view == 'V16':
                self.notifications = action
        self.add_widget(header)
        tabs = ActionRow(spacing=dp(4))
        self.tabs: dict[Delivery, Action] = {}
        for delivery in (Delivery.DROP, Delivery.LIVE):
            action = Action(
                delivery.value.upper(),
                partial(tab, delivery),
                surface=delivery.value + 'Surface'
                if delivery is self.delivery
                else 'surface',
                tone=delivery.value,
            )
            action.focus_key = ('selector', delivery.value.upper())
            self.tabs[delivery] = action
            tabs.add_widget(action)
        Action.group(tuple(reversed(tabs.children)))
        self.add_widget(tabs)
        self.scroll = ScrollView(do_scroll_x=False)
        self.column = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.column.bind(minimum_height=self.column.setter('height'))
        self.scroll.add_widget(self.column)
        self.add_widget(self.scroll)
        self.empty = Label(
            'No Drops yet'
            if self.delivery is Delivery.DROP
            else 'No Live conversations',
            role='peer',
        )
        self.empty_hint = Label(
            'Choose a saved contact to begin.', tone='textSecondary'
        )
        self.pager = ActionRow(spacing=dp(12))
        self.previous = Action('Previous', partial(self._page, -1))
        self.next = Action('Next', partial(self._page, 1))
        self.previous.focus_key, self.next.focus_key = (
            ('control', 'Previous'),
            ('control', 'Next'),
        )
        self.pager.add_widget(self.previous)
        self.pager.add_widget(self.next)
        self.ended_section = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.ended_section.bind(minimum_height=self.ended_section.setter('height'))
        self.ended_toggle = Action(
            'Ended Live chats', self._toggle_ended, surface='raised'
        )
        self.ended_toggle.focus_key = ('control', 'Ended Live chats')
        self.ended_section.add_widget(self.ended_toggle)
        self.ended_column = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.ended_column.bind(minimum_height=self.ended_column.setter('height'))
        self.ended_pager = ActionRow(spacing=dp(12))
        self.ended_previous = Action('Previous', partial(self._ended_page, -1))
        self.ended_next = Action('Next', partial(self._ended_page, 1))
        self.ended_previous.focus_key = ('control', 'Previous ended Live chats')
        self.ended_next.focus_key = ('control', 'Next ended Live chats')
        self.ended_pager.add_widget(self.ended_previous)
        self.ended_pager.add_widget(self.ended_next)
        self.new = Action(
            'New Drop' if self.delivery is Delivery.DROP else 'Start Live',
            partial(navigate, Route('V11', delivery=self.delivery)),
            surface=self.delivery.value,
            tone='onAccent',
        )
        self.new.focus_key = ('control', 'New')
        self.add_widget(self.new)
        self.update()

    def _page(self, delta: int) -> None:
        """Changes only this projection's explicit bounded page.

        Args:
            delta: Previous/Next offset.
        Returns:
            None
        """
        state = self.controller.state
        state.root_pages[self.delivery] = state.root_pages.get(self.delivery, 0) + delta
        self.refresh()

    def _toggle_ended(self) -> None:
        """Expands retained ended chats without sending, consuming, or reconnecting."""
        state = self.controller.state
        state.ended_live_expanded = not state.ended_live_expanded
        self.update()
        self.refresh()

    def _ended_page(self, delta: int) -> None:
        """Pages the ended section independently of current Live connections."""
        self.controller.state.ended_live_page += delta
        self.update()
        self.refresh()

    def update(self) -> None:
        """Reconciles changed identities/metadata without replacing unchanged native controls.

        Args:
            None
        Returns:
            None
        """
        state = self.controller.state
        contact_parent = next(
            (
                route.view
                for route in reversed(state.back_stack)
                if route.view in {'V11', 'V12'}
            ),
            None,
        )
        section = (
            'V12'
            if state.route.view == 'V12'
            or (state.route.view in {'V13', 'V14', 'V15'} and contact_parent == 'V12')
            else 'V17'
            if state.route.view in {'V17', 'V18', 'V19', 'V20'}
            else state.route.view
        )
        for view, action in self.header_actions.items():
            selected = section == view
            action.surface = 'dropSurface' if selected else 'raised'
            action.accessible_name = (
                'Notifications'
                if view == 'V16'
                else 'Contacts'
                if view == 'V12'
                else 'Settings'
            ) + (', current view' if selected else '')
            action._feedback()
        for delivery, action in self.tabs.items():
            selected = delivery is self.delivery
            action.surface = delivery.value + 'Surface' if selected else 'surface'
            action.accessible_name = delivery.value.upper() + (
                ', current mode' if selected else ''
            )
            action._feedback()
        new_view = state.route.view == 'V11' and state.route.delivery is self.delivery
        self.new.surface = self.delivery.value
        self.new._tone = 'onAccent'
        self.new.accessible_name = self.new.label.text + (
            ', current view' if new_view else ''
        )
        self.new._feedback()
        unseen = any(
            not item.seen for item in self.controller.notifications.store.items.values()
        )
        self.notifications.set_badge(unseen)
        self.notifications.accessible_name = (
            'Notifications'
            + (', current view' if section == 'V16' else '')
            + (', unseen activity' if unseen else '')
        )
        rows = conversation_rows(self.controller, self.delivery)
        ended = [entry for entry in rows if entry.ended]
        rows = [entry for entry in rows if not entry.ended]
        expanded = bool(ended) and state.ended_live_expanded
        ended_page = min(
            max(0, state.ended_live_page),
            max(0, (len(ended) - 1) // GuiLimits.PAGE_ITEMS),
        )
        state.ended_live_page = ended_page
        ended_entries = (
            ended[
                ended_page * GuiLimits.PAGE_ITEMS : (ended_page + 1)
                * GuiLimits.PAGE_ITEMS
            ]
            if expanded
            else []
        )
        self.ended_toggle.label.text = f'Ended Live chats ({len(ended)})'
        self.ended_toggle.accessible_name = self.ended_toggle.label.text + (
            ', expanded' if expanded else ', collapsed'
        )
        if ended and self.ended_section.parent is None:
            self.column.add_widget(self.ended_section, index=0)
        elif not ended and self.ended_section.parent is not None:
            self.column.remove_widget(self.ended_section)
        if expanded and self.ended_column.parent is None:
            self.ended_section.add_widget(self.ended_column)
        elif not expanded and self.ended_column.parent is not None:
            self.ended_section.remove_widget(self.ended_column)
        if expanded and len(ended) > GuiLimits.PAGE_ITEMS:
            if self.ended_pager.parent is None:
                self.ended_section.add_widget(self.ended_pager)
            self.ended_previous.disabled = ended_page == 0
            self.ended_next.disabled = (ended_page + 1) * GuiLimits.PAGE_ITEMS >= len(
                ended
            )
        elif self.ended_pager.parent is not None:
            self.ended_section.remove_widget(self.ended_pager)
        page = min(
            state.root_pages.get(self.delivery, 0),
            max(0, (len(rows) - 1) // GuiLimits.PAGE_ITEMS),
        )
        state.root_pages[self.delivery] = page
        entries = rows[page * GuiLimits.PAGE_ITEMS : (page + 1) * GuiLimits.PAGE_ITEMS]
        if entries:
            for placeholder in (self.empty, self.empty_hint):
                if placeholder.parent is not None:
                    self.column.remove_widget(placeholder)
        visible_entries = entries + ended_entries
        identities = {entry.peer for entry in visible_entries}
        for peer in tuple(self.rows):
            if peer not in identities:
                removed = self.rows.pop(peer)
                for control in removed.walk(restrict=True):
                    if isinstance(control, Action):
                        control.focus = False
                if removed.parent is not None:
                    removed.parent.remove_widget(removed)
        for entry in visible_entries:
            row = self.rows.get(entry.peer)
            if row is None:
                row = RootRow(self.controller, entry, self.navigate, self.refresh)
                self.rows[entry.peer] = row
            elif row.entry != entry:
                row.update(entry)
            row.select(state.route)
        for index, entry in enumerate(reversed(entries)):
            row = self.rows[entry.peer]
            index += int(self.ended_section.parent is self.column)
            if row.parent is not self.column:
                if row.parent is not None:
                    row.parent.remove_widget(row)
                self.column.add_widget(row, index=index)
            elif self.column.children.index(row) != index:
                self.column.remove_widget(row)
                self.column.add_widget(row, index=index)
        for index, entry in enumerate(reversed(ended_entries)):
            row = self.rows[entry.peer]
            if row.parent is not self.ended_column:
                if row.parent is not None:
                    row.parent.remove_widget(row)
                self.ended_column.add_widget(row, index=index)
            elif self.ended_column.children.index(row) != index:
                self.ended_column.remove_widget(row)
                self.ended_column.add_widget(row, index=index)
        Action.group(tuple(self.rows[entry.peer].action for entry in visible_entries))
        for placeholder in (self.empty, self.empty_hint):
            if not entries and placeholder.parent is None:
                self.column.add_widget(
                    placeholder, index=int(self.ended_section.parent is self.column)
                )
            elif entries and placeholder.parent is not None:
                self.column.remove_widget(placeholder)
        if len(rows) > GuiLimits.PAGE_ITEMS:
            if self.pager.parent is None:
                self.add_widget(self.pager, index=1)
            self.previous.disabled = page == 0
            self.next.disabled = (page + 1) * GuiLimits.PAGE_ITEMS >= len(rows)
        elif self.pager.parent is not None:
            self.remove_widget(self.pager)


def root_view(
    controller: GuiController,
    navigate: Callable[[Route], None],
    tab: Callable[[Delivery], None],
    refresh: Callable[[], None],
) -> RootPanel:
    """Creates the bounded native root behind the existing composition facade.

    Args:
        controller: Current public GUI state owner.
        navigate: Projection-only navigation.
        tab: Root selector callback.
        refresh: Native repaint request.
    Returns:
        RootPanel: Identity-stable header, selectors, page and footer.
    """
    return RootPanel(controller, navigate, tab, refresh)
