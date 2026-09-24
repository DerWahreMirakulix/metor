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
    scroll = ScrollView(size_hint=(None, 1), width=dp(400), do_scroll_x=False)
    outer.bind(
        width=lambda _w, width: setattr(scroll, 'width', min(dp(400), width - dp(48)))
    )
    column = BoxLayout(
        orientation='vertical', spacing=dp(16), size_hint_y=None, padding=(0, dp(48))
    )
    column.bind(minimum_height=column.setter('height'))
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
        if prompt.kind == 'start':
            column.add_widget(Label('Start Metor?', role='peer'))
            column.add_widget(
                Label('Start the local service for this profile.', tone='textSecondary')
            )
            column.add_widget(
                Action(
                    'Start Metor',
                    lambda: controller.interactions.answer(True),
                    surface='drop',
                    tone='onAccent',
                )
            )
            column.add_widget(
                Action('Cancel', lambda: controller.interactions.answer(None))
            )
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
                controller.interactions.answer(value)

            secret.bind(on_text_validate=lambda *_args: answer())
            column.add_widget(
                Action('Open profile', answer, surface='drop', tone='onAccent')
            )
            column.add_widget(
                Action('Cancel', lambda: controller.interactions.answer(None))
            )
    elif controller.lifecycle.active or controller.lifecycle.failed:
        lifecycle_body(controller, column)
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
    if state.status:
        column.add_widget(Label(state.status, role='support', tone='info'))
    return outer
