"""Graphical profile selection, creation and deferred password/start prompts."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.theme import color, font_path
from metor.ui.gui.widgets import TextField, Action, Label, SecretInput

# Local Package Imports
from .profiles import profiles_body, lifecycle_body


def entry_view(controller: GuiController, refresh: Callable[[], None]) -> AnchorLayout:
    """Builds the full-application entry cover without exposing a private master.

    Args:
        controller: Active public-host controller.
        refresh: Repaint callback.
    Returns:
        AnchorLayout: Centered scrollable authentication composition.
    """
    outer = AnchorLayout(padding=dp(24))
    scroll = ScrollView(size_hint=(None, None), width=dp(400), do_scroll_x=False)
    outer.bind(
        width=lambda _w, width: setattr(scroll, 'width', min(dp(400), width - dp(48)))
    )
    column = BoxLayout(
        orientation='vertical', spacing=dp(8), size_hint_y=None, padding=(0, dp(24))
    )
    column.bind(minimum_height=column.setter('height'))

    def fit_cover(*_args: object) -> None:
        """Centers a fitting cover and scrolls only when its controls overflow.

        Args:
            _args: Native layout changes.
        Returns:
            None
        """
        available = max(0, outer.height - outer.padding[1] - outer.padding[3])
        scroll.height = min(column.minimum_height, available)
        scroll.do_scroll_y = column.minimum_height > available

    outer.bind(height=fit_cover, padding=fit_cover)
    column.bind(minimum_height=fit_cover)
    scroll.add_widget(column)
    outer.add_widget(scroll)
    column.add_widget(Label('Metor', role='hero'))
    prompt = controller.interactions.prompt
    state = controller.state

    def navigate(view: str) -> None:
        """Changes startup presentation without activating another runtime.

        Args:
            view: Startup view ID.
        Returns:
            None
        """
        state.route = Route(view)
        if view == 'V02':
            controller.profiles.reload()
        refresh()

    def open_profile() -> None:
        """Starts graphical entry and updates its busy state.

        Args:
            None
        Returns:
            None
        """
        controller.open_profile()
        refresh()

    if prompt is not None:

        def respond(value: str | bool | None) -> None:
            """Replace an answered prompt with the pending startup state.

            Args:
                value: Start confirmation, one-use password, or cancellation.
            Returns:
                None
            """
            controller.interactions.answer(value)
            refresh()

        if prompt.kind == 'start':
            column.add_widget(Label('Start Metor?', role='peer'))
            column.add_widget(
                Label('Start the local service for this profile.', tone='textSecondary')
            )
            column.add_widget(
                Action(
                    'Start Metor',
                    lambda: respond(True),
                    surface='drop',
                    tone='onAccent',
                )
            )
            column.add_widget(Action('Cancel', lambda: respond(None)))
        else:
            column.add_widget(Label('Open profile', role='peer'))
            column.add_widget(Label('Profile password', role='support'))
            secret = SecretInput()
            column.add_widget(secret)

            def answer() -> None:
                """Hands off and clears the password field immediately.

                Args:
                    None
                Returns:
                    None
                """
                value = secret.text
                secret.text = ''
                respond(value)

            secret.bind(on_text_validate=lambda *_args: answer())
            column.add_widget(
                Action('Open profile', answer, surface='drop', tone='onAccent')
            )
            column.add_widget(Action('Cancel', lambda: respond(None)))
    elif controller.lifecycle.active or controller.lifecycle.failed:
        lifecycle_body(controller, column)
    elif state.busy and state.route.view == 'V01':
        column.add_widget(Label('Opening profile', role='peer'))
        column.add_widget(
            Label(state.status or 'Please wait…', role='support', tone='textSecondary')
        )
    elif state.route.view == 'V02':
        column.add_widget(Label('Choose profile', role='peer'))
        profiles_body(controller, column, startup=True)
        column.add_widget(
            Action('New profile', lambda: navigate('V03'), disabled=state.busy)
        )
        column.add_widget(Action('Back', lambda: navigate('V01'), disabled=state.busy))
    elif state.route.view == 'V03':
        column.add_widget(Label('New profile', role='peer'))
        column.add_widget(Label('Name', role='support'))
        name = TextField(
            multiline=False,
            font_name=font_path(),
            size_hint_y=None,
            height=dp(52),
            foreground_color=color('text'),
            background_color=color('raised'),
        )
        name.text = controller.initial_missing_profile or ''
        column.add_widget(name)
        column.add_widget(Label('Password', role='support'))
        password = SecretInput()
        column.add_widget(password)
        column.add_widget(Label('Confirm password', role='support'))
        confirmation = SecretInput()
        column.add_widget(confirmation)
        error = Label('', role='support', tone='danger')
        column.add_widget(error)

        def create() -> None:
            """Validates matching credentials then invokes encrypted creation.

            Args:
                None
            Returns:
                None
            """
            if (
                not name.text.strip()
                or not password.text
                or password.text != confirmation.text
            ):
                error.text = 'Enter a name and matching passwords.'
                return
            if controller.create_profile(name.text.strip(), password.text):
                password.text = confirmation.text = ''
                refresh()

        column.add_widget(
            Action(
                'Create profile',
                create,
                surface='drop',
                tone='onAccent',
                disabled=state.busy,
            )
        )
        column.add_widget(Action('Back', lambda: navigate('V01'), disabled=state.busy))
    else:
        selected = (
            None if controller.simulator else controller.context.host.profile_state()
        )
        profile_name = (
            'Simulator'
            if controller.simulator
            else (selected.profile if selected is not None else 'Choose profile')
        )
        column.add_widget(Label(profile_name, role='peer'))
        column.add_widget(
            Action(
                'Open profile',
                open_profile,
                surface='drop',
                tone='onAccent',
                disabled=state.busy,
            )
        )
        column.add_widget(
            Action('Switch profile', lambda: navigate('V02'), disabled=state.busy)
        )
        column.add_widget(
            Action('New profile', lambda: navigate('V03'), disabled=state.busy)
        )
    if state.status and not (
        state.busy and state.route.view == 'V01' and prompt is None
    ):
        column.add_widget(Label(state.status, role='support', tone='info'))
    fit_cover()
    return outer
