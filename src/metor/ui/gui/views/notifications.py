"""Native content-free Notification Center with explicit local selection and dismissal."""

from collections.abc import Callable
from datetime import datetime
from functools import partial

from kivy.metrics import dp
from kivy.core.text import Label as TextMeasure
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state.notifications import Notice, NoticeKind
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction, Symbol
from metor.ui.gui.widgets.context import ContextAction


TITLES: dict[NoticeKind, str] = {
    NoticeKind.DROP: 'New Drop',
    NoticeKind.LIVE: 'New Live activity',
    NoticeKind.CALL: 'Incoming Live',
    NoticeKind.PENDING: 'Pending Live',
    NoticeKind.UNSTABLE: 'Connection unstable',
    NoticeKind.FALLBACK: 'Queued as Drop',
}


def notification_center(
    controller: GuiController, refresh: Callable[[], None]
) -> BoxLayout:
    """Builds a bounded center whose actions affect presentation entries only.

    Args:
        controller: Public state and volatile center owner.
        refresh: Coalesced native repaint request.
    Returns:
        BoxLayout: Header, scrolling rows and selection-only action footer.
    """
    store = controller.notifications.store
    store.mark_seen()
    panel = BoxLayout(orientation='vertical', spacing=dp(16))
    header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))

    def back() -> None:
        """Cancels selection or returns to the preceding presentation.

        Args:
            None

        Returns:
            None
        """
        controller.back()
        refresh()

    def clear() -> None:
        """Clears volatile notification-center entries and refreshes the view.

        Args:
            None

        Returns:
            None
        """
        store.clear_center()
        refresh()

    header.add_widget(
        IconAction(
            'chevron-left', 'Cancel selection' if store.selecting else 'Back', back
        )
    )
    header.add_widget(
        Label(
            f'{len(store.selected)} selected' if store.selecting else 'Notifications',
            role='title',
            wrap=False,
        )
    )
    header.add_widget(
        IconAction('trash-2', 'Clear notifications', clear, disabled=not store.items)
    )
    panel.add_widget(header)
    scroll = ScrollView(do_scroll_x=False)
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    scroll.add_widget(body)
    panel.add_widget(scroll)
    if not store.items:
        body.add_widget(Label('No notifications', role='peer'))
    for notice in reversed(tuple(store.items.values())):
        body.add_widget(notice_row(controller, notice, refresh))
    if store.selecting:

        def dismiss_selected() -> None:
            """Dismisses the explicitly selected local notification entries.

            Args:
                None

            Returns:
                None
            """
            store.dismiss(set(store.selected))
            refresh()

        panel.add_widget(
            Action('Dismiss selected', dismiss_selected, disabled=not store.selected)
        )
    return panel


def notice_row(
    controller: GuiController, notice: Notice, refresh: Callable[[], None]
) -> BoxLayout:
    """Builds an 88-unit entry from permitted kind/count/time and current canonical alias.

    Args:
        controller: Current public-state and label resolver.
        notice: Strict content-free local entry.
        refresh: Native repaint callback.
    Returns:
        BoxLayout: Native row with a distinct 48-unit More or selection target.
    """
    store = controller.notifications.store
    key = notice.key
    row = BoxLayout(size_hint_y=None, height=dp(88), spacing=dp(8))

    def activate() -> None:
        """Selects or opens this exact notification entry.

        Args:
            None

        Returns:
            None
        """
        if store.selecting:
            if key in store.selected:
                store.selected.remove(key)
            else:
                store.selected.add(key)
        else:
            controller.notifications.open(key)
        refresh()

    action = ContextAction(
        TITLES[notice.kind],
        activate,
        partial(notice_menu, controller, key, refresh),
        surface='surface',
    )
    action.height = dp(88)
    action.padding = (dp(16), dp(16), dp(16), dp(18))
    action.remove_widget(action.label)
    column = BoxLayout(orientation='vertical', spacing=dp(8))
    top = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
    kind = Label(TITLES[notice.kind], role='row')
    top.add_widget(kind)
    stamp = Label(
        datetime.fromtimestamp(notice.created_at).strftime('%H:%M'),
        role='meta',
        tone='textSecondary',
        wrap=False,
    )
    stamp.size_hint_x = None
    measure_stamp = TextMeasure(
        text=stamp.text, font_name=stamp.font_name, font_size=stamp.font_size
    )
    measure_stamp.refresh()
    stamp.width = max(dp(40), measure_stamp.texture.size[0])
    top.add_widget(stamp)
    column.add_widget(top)
    summary = controller.contacts.alias(notice.peer)
    if notice.count > 1:
        summary += f' · {notice.count}'
    summary_label = Label(summary, role='support', tone='textSecondary')
    summary_row = BoxLayout(size_hint_y=None, height=dp(18), spacing=dp(8))
    summary_row.add_widget(summary_label)
    summary_row.add_widget(
        Symbol('chevron-right', tone='textSecondary', size_hint_x=None, width=dp(24))
    )
    summary_label.bind(
        height=lambda _widget, height: setattr(
            summary_row, 'height', max(dp(18), height)
        )
    )
    column.add_widget(summary_row)
    action.accessible_name = TITLES[notice.kind] + ': ' + summary
    action.add_widget(column)

    def measure(*_args: object) -> None:
        """Recomputes the native row height from rendered text metrics.

        Args:
            _args (object): The  args input.

        Returns:
            None
        """
        top.height = max(dp(28), kind.height)
        action.height = row.height = max(
            dp(88), dp(16 + 8 + 18) + top.height + summary_label.height
        )

    kind.bind(height=measure)
    summary_label.bind(height=measure)
    measure()
    row.add_widget(action)
    if store.selecting:
        row.add_widget(
            IconAction(
                'square-check' if key in store.selected else 'square',
                'Deselect notification'
                if key in store.selected
                else 'Select notification',
                activate,
                pos_hint={'center_y': 0.5},
            )
        )
    else:
        row.add_widget(
            IconAction(
                'ellipsis',
                'Notification actions',
                partial(notice_menu, controller, key, refresh),
                pos_hint={'center_y': 0.5},
            )
        )
    return row


def notice_menu(
    controller: GuiController, key: tuple[NoticeKind, str], refresh: Callable[[], None]
) -> None:
    """Offers local selection/dismissal while keeping its captured entry identity exact.

    Args:
        controller: Current notification and authorization owner.
        key: Exact selected entry.
        refresh: Native repaint callback.
    Returns:
        None
    """
    store = controller.notifications.store

    def build(body: BoxLayout) -> None:
        """Builds actions for the captured notification identity.

        Args:
            body (BoxLayout): The body input.

        Returns:
            None
        """

        def select() -> None:
            """Enters notification selection mode without selecting stale entries.

            Args:
                None

            Returns:
                None
            """
            sheet.dismiss(animation=False)
            store.selecting = True
            store.selected.clear()
            refresh()

        def dismiss() -> None:
            """Dismisses the captured notification when it still exists.

            Args:
                None

            Returns:
                None
            """
            sheet.dismiss(animation=False)
            store.dismiss({key})
            refresh()

        body.add_widget(Action('Select notifications', select))
        body.add_widget(Action('Dismiss', dismiss, disabled=key not in store.items))

    sheet = ActionSheet(
        controller, build, title='Notification actions', compact_menu=True
    )
    sheet.show()
