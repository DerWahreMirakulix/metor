"""Paged DROP/LIVE roots with protected pins and immutable contextual action targets."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp, sp
from kivy.core.text import Label as TextMeasure
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController, ConversationRow, conversation_rows
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, Panel
from metor.ui.gui.widgets.context import ContextAction
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction, Symbol


# Local Package Imports
from .actions import clear_drops, live_context_actions


def conversation_menu(
    controller: GuiController, entry: ConversationRow, refresh: Callable[[], None]
) -> None:
    """Uses a stable canonical identity for More, right-click and hold actions.

    Args:
        controller: Public state and action owner.
        entry: Originally displayed immutable conversation target.
        refresh: Native repaint request.
    Returns:
        None
    """

    def build(body: BoxLayout) -> None:
        """Resolves current eligibility and labels each time canonical state changes.

        Args:
            body: Scrolling native menu body.
        Returns:
            None
        """
        current = next(
            (
                row
                for row in conversation_rows(controller, entry.delivery)
                if row.peer == entry.peer
            ),
            None,
        )
        if current is None:
            body.add_widget(Label('Conversation no longer available'))
            return

        def pin() -> None:
            """Applies a protected pin change only to the displayed DROP identity.

            Args:
                None
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            controller.preferences.pin(entry.peer)
            refresh()

        def delete() -> None:
            """Moves from More to a separate local DROP confirmation.

            Args:
                None
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            clear_drops(controller, entry.peer)

        if entry.delivery is Delivery.DROP:
            body.add_widget(
                Action(
                    'Unpin' if current.pinned else 'Pin',
                    pin,
                    disabled=controller.state.busy
                    or controller.state.preferences is None,
                )
            )
            body.add_widget(
                Action(
                    'Delete conversation',
                    delete,
                    tone='danger',
                    disabled=controller.state.busy
                    or controller.drop.pending is not None,
                )
            )
        else:

            def open_live() -> None:
                """Navigates to the existing peer without initiating a call.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.navigate(Route('V09', entry.peer, Delivery.LIVE))
                refresh()

            body.add_widget(Action('Open Live', open_live))
            live_context_actions(
                controller, entry.peer, body, lambda: sheet.dismiss(animation=False)
            )
        snapshot = controller.state.snapshot
        saved = snapshot is not None and any(
            contact.onion == entry.peer and contact.saved
            for contact in snapshot.contacts
        )
        if not saved:

            def save_contact() -> None:
                """Opens Save-only contact promotion without changing communication state.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.contacts.begin('save', entry.peer)
                refresh()

            body.add_widget(
                Action('Save contact', save_contact, disabled=controller.state.busy)
            )

    sheet = ActionSheet(
        controller,
        build,
        title=lambda: controller.contacts.alias(entry.peer),
        compact_menu=True,
    )
    sheet.show()


def conversation_row(
    controller: GuiController,
    entry: ConversationRow,
    navigate: Callable[[Route], None],
    refresh: Callable[[], None],
) -> BoxLayout:
    """Builds one growing 84-unit row with distinct More and navigation controls.

    Args:
        controller: Current public state owner.
        entry: Immutable row target and permitted metadata.
        navigate: Normal projection-only navigation.
        refresh: Native repaint request.
    Returns:
        BoxLayout: One bounded native conversation row.
    """
    row = BoxLayout(size_hint_y=None, height=dp(84), spacing=dp(8))
    route = Route(
        'V08' if entry.delivery is Delivery.DROP else 'V09', entry.peer, entry.delivery
    )
    context = partial(conversation_menu, controller, entry, refresh)
    action = ContextAction(
        entry.label, partial(navigate, route), context, surface='surface'
    )
    action.height = dp(84)
    action.padding = (dp(12), dp(16))
    action.remove_widget(action.label)
    group = BoxLayout(spacing=dp(12))
    avatar = Panel(
        surface=entry.delivery.value + 'Surface',
        size_hint=(None, None),
        width=dp(48),
        height=dp(48),
        pos_hint={'center_y': 0.5},
    )
    avatar._rectangle.radius = [dp(24)]
    initials = ''.join(word[0] for word in entry.label.split()[:2] if word).upper()
    initials_label = Label(initials, role='row', tone=entry.delivery.value, wrap=False)
    initials_label.halign = 'center'
    avatar.add_widget(initials_label)
    group.add_widget(avatar)
    column = BoxLayout(orientation='vertical', spacing=dp(3))
    name_row = BoxLayout(size_hint_y=None, height=sp(22), spacing=dp(4))
    name_row.add_widget(Label(entry.label, role='row', wrap=False))
    if entry.pinned:
        name_row.add_widget(Symbol('pin', tone='drop', size_hint_x=None, width=dp(24)))
    column.add_widget(name_row)
    status = entry.status
    if entry.unseen:
        status = 'New Drops' if entry.delivery is Delivery.DROP else status
    if entry.pending:
        status += f' · {entry.pending} pending'
    detail = Label(status, role='support', tone='textSecondary')
    column.add_widget(detail)
    group.add_widget(column)
    if entry.unseen:
        count = Label(str(entry.unseen), role='caption', tone='onAccent', wrap=False)
        count.halign = 'center'
        measure_count = TextMeasure(
            text=count.text, font_name=count.font_name, font_size=count.font_size
        )
        measure_count.refresh()
        badge = Panel(
            surface=entry.delivery.value,
            size_hint=(None, None),
            width=measure_count.texture.size[0] + dp(12),
            height=max(dp(24), sp(16) + dp(8)),
            pos_hint={'center_y': 0.5},
        )
        badge.add_widget(count)
        group.add_widget(badge)
    action.add_widget(group)
    action.accessible_name = (
        entry.label
        + ': '
        + status
        + (f', {entry.unseen} unseen' if entry.unseen else '')
        + (', pinned' if entry.pinned else '')
    )

    def measure(*_args: object) -> None:
        """Grows metadata while retaining the approved avatar and hit-target sizes.

        Args:
            _args: Native font/line-height update.
        Returns:
            None
        """
        action.height = row.height = max(
            dp(84), dp(32 + 3) + name_row.height + detail.height
        )

    detail.bind(height=measure)
    measure()
    row.add_widget(action)
    row.add_widget(
        IconAction(
            'ellipsis', 'Conversation actions', context, pos_hint={'center_y': 0.5}
        )
    )
    return row


def root_view(
    controller: GuiController,
    navigate: Callable[[Route], None],
    tab: Callable[[Delivery], None],
    refresh: Callable[[], None],
) -> BoxLayout:
    """Renders at most one bounded page while keeping root tabs independent of peer focus.

    Args:
        controller: Current authorized public-service state.
        navigate: Explicit projection-only navigation.
        tab: Root-tab selection preserving wide foreground media.
        refresh: Native repaint request.
    Returns:
        BoxLayout: Header, selector, scrolling page and fixed contextual New action.
    """
    state = controller.state
    panel = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(16))
    header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
    header.add_widget(Label('METOR', role='wordmark', wrap=False))
    unseen = any(
        not item.seen for item in controller.notifications.store.items.values()
    )
    for icon, title, view in (
        ('bell', 'Notifications', 'V16'),
        ('users', 'Contacts', 'V12'),
        ('settings', 'Settings', 'V17'),
    ):
        badge = view == 'V16' and unseen
        header.add_widget(
            IconAction(
                icon,
                title + (', unseen activity' if badge else ''),
                partial(navigate, Route(view)),
                badge=badge,
            )
        )
    panel.add_widget(header)
    tabs = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
    for delivery in (Delivery.DROP, Delivery.LIVE):
        tabs.add_widget(
            Action(
                delivery.value.upper(),
                partial(tab, delivery),
                surface=delivery.value + 'Surface'
                if delivery is state.root_delivery
                else 'surface',
                tone=delivery.value,
            )
        )
    panel.add_widget(tabs)
    scroll = ScrollView(do_scroll_x=False)
    column = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    column.bind(minimum_height=column.setter('height'))
    scroll.add_widget(column)
    panel.add_widget(scroll)
    rows = conversation_rows(controller, state.root_delivery)
    page = min(
        state.root_pages.get(state.root_delivery, 0),
        max(0, (len(rows) - 1) // GuiLimits.PAGE_ITEMS),
    )
    state.root_pages[state.root_delivery] = page
    for entry in rows[page * GuiLimits.PAGE_ITEMS : (page + 1) * GuiLimits.PAGE_ITEMS]:
        column.add_widget(conversation_row(controller, entry, navigate, refresh))
    if not rows:
        column.add_widget(
            Label(
                'No Drops yet'
                if state.root_delivery is Delivery.DROP
                else 'No Live conversations',
                role='peer',
            )
        )
        column.add_widget(
            Label('Choose a saved contact to begin.', tone='textSecondary')
        )
    if len(rows) > GuiLimits.PAGE_ITEMS:
        pager = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))

        def select_page(delta: int) -> None:
            """Changes only the bounded root list page.

            Args:
                delta: Explicit Previous/Next page direction.
            Returns:
                None
            """
            state.root_pages[state.root_delivery] = page + delta
            refresh()

        pager.add_widget(
            Action('Previous', partial(select_page, -1), disabled=page == 0)
        )
        pager.add_widget(
            Action(
                'Next',
                partial(select_page, 1),
                disabled=(page + 1) * GuiLimits.PAGE_ITEMS >= len(rows),
            )
        )
        panel.add_widget(pager)
    if state.status:
        panel.add_widget(Label(state.status, role='support', tone='info'))
    panel.add_widget(
        Action(
            'New Drop' if state.root_delivery is Delivery.DROP else 'Start Live',
            partial(navigate, Route('V11', delivery=state.root_delivery)),
            surface=state.root_delivery.value,
            tone='onAccent',
        )
    )
    return panel
