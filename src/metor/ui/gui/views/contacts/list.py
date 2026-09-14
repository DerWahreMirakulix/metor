"""Stable native contact search with bounded pages and explicit immutable bulk selection."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.contacts import ContactIntent
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, TextField
from metor.ui.gui.widgets.context import ContextAction
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet, confirm

# Local Package Imports
from .panel import contact_sheet


class ContactListView(BoxLayout):
    """Keeps search/focus and page ownership independent of new snapshot object identities."""

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Builds one fixed navigation/search/footer around at most 64 native contact rows.

        Args:
            controller: Current public-service presentation owner.
            refresh: Native shell repaint callback.
        Returns:
            None
        """
        super().__init__(orientation='vertical', spacing=dp(16))
        self.controller, self.refresh = controller, refresh
        self.route = controller.state.route
        self._key: object = None
        self._rows: dict[str, Action] = {}
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.back = IconAction('chevron-left', 'Back', controller.back)
        self.title = Label(role='title', wrap=False)
        header.add_widget(self.back)
        header.add_widget(self.title)
        header.add_widget(IconAction('ellipsis', 'Contact actions', self.more))
        self.add_widget(header)
        self.search = TextField(
            multiline=False,
            hint_text='Search saved contacts',
            size_hint_y=None,
            height=dp(52),
            text=controller.contacts.query,
        )
        self.search.bind(text=self.filter)
        self.add_widget(self.search)
        self.scroll = ScrollView(do_scroll_x=False)
        self.rows = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
        self.rows.bind(minimum_height=self.rows.setter('height'))
        self.scroll.add_widget(self.rows)
        self.add_widget(self.scroll)
        pages = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.previous = IconAction(
            'chevron-left', 'Previous contact page', partial(self.page, -1)
        )
        self.next = IconAction(
            'chevron-right', 'Next contact page', partial(self.page, 1)
        )
        self.page_label = Label(role='support', wrap=False)
        for widget in (self.previous, self.page_label, self.next):
            pages.add_widget(widget)
        self.add_widget(pages)
        self.footer = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.footer.bind(minimum_height=self.footer.setter('height'))
        self.add_widget(self.footer)
        self.update()

    def filter(self, _field: TextField, value: str) -> None:
        """Filters rows without replacing the focused search field or changing selection.

        Args:
            _field: Current native search field.
            value: User-entered local query.
        Returns:
            None
        """
        if len(value.encode('utf-8')) > GuiLimits.CONTACT_BYTES:
            self.search.text = self.controller.contacts.query
            return
        self.controller.contacts.query = value
        self.controller.contacts.book.page = 0
        self.scroll.scroll_y = 1
        self.update()

    def page(self, delta: int) -> None:
        """Moves one bounded page without selecting a peer or initiating communication.

        Args:
            delta: Previous or next page direction.
        Returns:
            None
        """
        self.controller.contacts.book.page = max(
            0, self.controller.contacts.book.page + delta
        )
        self.scroll.scroll_y = 1
        self.update()

    def select(self, peer: str) -> None:
        """Toggles only the original explicit row identity.

        Args:
            peer: Captured canonical saved peer.
        Returns:
            None
        """
        self.controller.contacts.book.toggle(peer)
        self.update()

    def cancel(self) -> None:
        """Leaves selection without mutating contacts.

        Args:
            None
        Returns:
            None
        """
        self.controller.contacts.book.cancel_selection()
        self.update()

    def remove(self) -> None:
        """Confirms the exact selected identities once with the actual demotion consequences.

        Args:
            None
        Returns:
            None
        """
        peers = tuple(sorted(self.controller.contacts.book.selected))
        if peers:
            confirm(
                self.controller,
                'Remove selected contacts',
                'Remove '
                + str(len(peers))
                + ' saved contacts. Retained conversations and active communication may remain.',
                lambda: self.controller.contacts.book.remove(peers),
            )

    def more(self) -> None:
        """Keeps secondary actions in a reachable compact native menu.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller

        def run(action: Callable[[], object]) -> None:
            """Dismisses the menu before an explicit navigation or selection action.

            Args:
                action: Original user-selected operation.
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            action()
            self.update()

        def add() -> None:
            """Preserves picker intent in the shared contact form.

            Args:
                None
            Returns:
                None
            """
            controller.contacts.begin(
                'save'
                if self.route.view == 'V12'
                else 'live'
                if self.route.delivery is Delivery.LIVE
                else 'drop'
            )

        def manage() -> None:
            """Enters selection with no automatically chosen peers.

            Args:
                None
            Returns:
                None
            """
            controller.contacts.book.selecting = True

        def build(body: BoxLayout) -> None:
            """Builds navigation and separately confirmed address-book management.

            Args:
                body: Native scrolling menu column.
            Returns:
                None
            """
            body.add_widget(
                Action(
                    'Add contact' if self.route.view == 'V12' else 'Enter contact data',
                    lambda: run(add),
                )
            )
            body.add_widget(
                Action('My QR', lambda: run(lambda: controller.navigate(Route('V15'))))
            )
            if self.route.view == 'V12':
                body.add_widget(Action('Manage contacts', lambda: run(manage)))
                body.add_widget(
                    Action(
                        'Clear all contacts',
                        lambda: run(
                            lambda: confirm(
                                controller,
                                'Clear all contacts',
                                'Remove all saved contacts. Retained conversations and active communication may remain.',
                                controller.contacts.clear,
                            )
                        ),
                        tone='danger',
                        disabled=controller.state.busy
                        or controller.contacts.book.pending
                        or controller.contacts.book.unknown,
                    )
                )

        sheet = ActionSheet(controller, build, title='Contacts', compact_menu=True)
        sheet.show()

    def update(self) -> None:
        """Reconciles a finite page while preserving search and exact surviving row focus.

        Args:
            None
        Returns:
            None
        """
        controller, book = self.controller, self.controller.contacts.book
        contacts = book.rows()
        maximum = max(0, (len(contacts) - 1) // GuiLimits.PAGE_ITEMS)
        book.page = min(book.page, maximum)
        page = contacts[
            book.page * GuiLimits.PAGE_ITEMS : (book.page + 1) * GuiLimits.PAGE_ITEMS
        ]
        selecting = self.route.view == 'V12' and book.selecting
        self.title.text = (
            str(len(book.selected)) + ' selected'
            if selecting
            else 'Contacts'
            if self.route.view == 'V12'
            else 'Start Live'
            if self.route.delivery is Delivery.LIVE
            else 'New Drop'
        )
        self.previous.disabled, self.next.disabled = (
            book.page == 0,
            book.page >= maximum,
        )
        self.page_label.text = str(book.page + 1) + ' / ' + str(maximum + 1)
        key = (
            tuple(
                (item.onion, item.alias, controller.contacts.active(item.onion))
                for item in page
            ),
            selecting,
            frozenset(book.selected),
            book.pending,
            book.unknown,
            controller.state.busy,
            controller.state.status,
        )
        if self._key == key:
            return
        self._key = key
        focused = next((peer for peer, row in self._rows.items() if row.focus), None)
        scroll = self.scroll.scroll_y
        self.rows.clear_widgets()
        self._rows.clear()
        if not page:
            self.rows.add_widget(
                Label(
                    'No matching contacts'
                    if controller.contacts.query
                    else 'No saved contacts',
                    role='peer',
                )
            )
        for item in page:
            context = partial(contact_sheet, controller, item.onion, self.refresh)
            intent: ContactIntent = (
                'live' if self.route.delivery is Delivery.LIVE else 'drop'
            )
            activate = (
                partial(self.select, item.onion)
                if selecting
                else context
                if self.route.view == 'V12'
                else partial(controller.contacts.select, item.onion, intent)
            )
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
            if selecting:
                row.add_widget(
                    IconAction(
                        'square-check' if item.onion in book.selected else 'square',
                        'Deselect contact'
                        if item.onion in book.selected
                        else 'Select contact',
                        partial(self.select, item.onion),
                        disabled=book.pending or book.unknown,
                    )
                )
            action = ContextAction(
                item.alias,
                activate,
                context,
                disabled=selecting and (book.pending or book.unknown),
            )
            action.accessible_name = (
                item.alias
                + ': '
                + (
                    'Select contact'
                    if selecting
                    else 'Contact actions'
                    if self.route.view == 'V12'
                    else 'Open active Live'
                    if intent == 'live' and controller.contacts.active(item.onion)
                    else 'Start Live'
                    if intent == 'live'
                    else 'Open Drop'
                )
            )
            self._rows[item.onion] = action
            action.label.halign = 'left'
            row.add_widget(action)
            if not selecting:
                row.add_widget(
                    IconAction('ellipsis', 'Actions for ' + item.alias, context)
                )
            self.rows.add_widget(row)
        self.scroll.scroll_y = scroll
        if focused is not None:
            if focused in self._rows:
                self._rows[focused].focus = True
            else:
                self.back.focus = True
        self.footer.clear_widgets()
        if selecting:
            self.footer.add_widget(
                Action(
                    'Remove selected (' + str(len(book.selected)) + ')',
                    self.remove,
                    tone='danger',
                    disabled=not book.selected
                    or book.pending
                    or book.unknown
                    or controller.state.busy,
                )
            )
            self.footer.add_widget(Action('Cancel selection', self.cancel))
        if book.unknown and not book.pending:
            self.footer.add_widget(Action('Check saved contacts', book.check))
        if controller.state.status:
            self.footer.add_widget(
                Label(controller.state.status, role='support', tone='info')
            )
