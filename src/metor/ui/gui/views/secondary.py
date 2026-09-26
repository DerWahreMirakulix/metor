"""Saved-contact navigation and explicit capability failures for the platform slice."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Label
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from .settings import settings_body, advanced_body
from .contacts import contacts_body, ContactListView
from .notifications import notification_center
from .history import history_body, confirm_history_clear
from .profiles import profiles_body


def secondary_view(controller: GuiController, refresh: Callable[[], None]) -> BoxLayout:
    """Builds saved contacts and truthful unavailable integration surfaces.

    Args:
        controller: Public service controller.
        refresh: Native repaint callback.
    Returns:
        BoxLayout: Foreground secondary panel.
    """
    state = controller.state
    if state.route.view in {'V11', 'V12'}:
        return ContactListView(controller, refresh)
    if state.route.view == 'V16':
        return notification_center(controller, refresh)
    route = state.route
    panel = BoxLayout(orientation='vertical', spacing=dp(16))
    title = {
        'V11': 'New Drop' if route.delivery == Delivery.DROP else 'Start Live',
        'V12': 'Contacts',
        'V13': 'Rename contact'
        if controller.contacts.form and controller.contacts.form.intent == 'rename'
        else 'Add contact',
        'V14': 'Scan contact',
        'V15': 'My contact',
        'V16': 'Notifications',
        'V17': 'Settings',
        'V19': 'Advanced',
        'V20': 'Profiles',
        'V18': 'Technical history' if route.history_raw else 'Activity history',
    }.get(route.view, 'Metor')
    header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))

    def back() -> None:
        """Restores caller presentation without a communication command.

        Args:
            None
        Returns:
            None
        """
        controller.back()
        refresh()

    def go(target: Route) -> None:
        """Opens a public view route.

        Args:
            target: Explicit destination.
        Returns:
            None
        """
        controller.navigate(target)
        refresh()

    header.add_widget(IconAction('chevron-left', 'Back', back))
    header.add_widget(Label(title, role='title', wrap=False))
    if route.view == 'V18':
        header.add_widget(
            IconAction(
                'trash-2',
                'Clear activity history',
                lambda: confirm_history_clear(controller),
                disabled=state.busy
                or controller.history.pending
                or 'history_metadata_pages' not in state.capabilities,
            )
        )
    panel.add_widget(header)
    scroll = ScrollView(do_scroll_x=False)
    generation = state.generation
    remembered_scroll = state.secondary_scroll.get(route, 1.0)

    def remember(_widget: ScrollView, value: float) -> None:
        """Retains finite authorized presentation position across background refresh.

        Args:
            _widget: Native scroll owner.
            value: Normalized vertical position.
        Returns:
            None
        """
        if (
            state.covered
            or state.generation != generation
            or panel.get_root_window() is None
        ):
            return
        if (
            route not in state.secondary_scroll
            and len(state.secondary_scroll) >= GuiLimits.TEXT_CONTEXTS
        ):
            state.secondary_scroll.pop(next(iter(state.secondary_scroll)))
        state.secondary_scroll[route] = max(0.0, min(1.0, value))

    def restore(_elapsed: float) -> None:
        """Restores only this attached authorized route after native layout settles.

        Args:
            _elapsed: Toolkit scheduling delay.
        Returns:
            None
        """
        if (
            not state.covered
            and state.generation == generation
            and state.route == route
            and panel.get_root_window() is not None
        ):
            scroll.scroll_y = remembered_scroll
            scroll.bind(scroll_y=remember)

    Clock.schedule_once(restore, 0)
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    if route.view == 'V20':

        def fit_profiles(*_args: object) -> None:
            """Disables profile-page scrolling while every action fits the viewport.

            Args:
                _args: Native viewport or profile-row layout changes.
            Returns:
                None
            """
            scroll.do_scroll_y = body.minimum_height > scroll.height

        body.bind(minimum_height=fit_profiles)
        scroll.bind(height=fit_profiles)
    scroll.add_widget(body)
    panel.add_widget(scroll)
    if route.view in {'V11', 'V12', 'V13', 'V14', 'V15'}:
        contacts_body(controller, body, refresh)
    elif route.view == 'V19':
        body.add_widget(advanced_body(controller))
    elif route.view == 'V18':
        history_body(controller, body)
    elif route.view == 'V20':
        profiles_body(controller, body)
    else:
        body.add_widget(settings_body(controller, refresh))
    if state.status:
        panel.add_widget(Label(state.status, role='support', tone='info'))
    if route.view == 'V20':
        fit_profiles()
    return panel
