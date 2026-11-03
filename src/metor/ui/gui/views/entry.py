"""Graphical profile selection, creation and deferred password/start prompts."""

from collections.abc import Callable

from kivy.metrics import sp
from kivy.uix.anchorlayout import AnchorLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.theme import color, font_path
from metor.ui.gui.widgets import Action, ActionRow, Label, SecretInput, TextField

# Local Package Imports
from .cover import PrivateForm
from .profiles import profiles_body, lifecycle_body


def entry_view(controller: GuiController, refresh: Callable[[], None]) -> AnchorLayout:
    """Builds the full-application entry cover without exposing a private master.

    Args:
        controller: Active public-host controller.
        refresh: Repaint callback.
    Returns:
        AnchorLayout: Centered scrollable authentication composition.
    """
    outer = PrivateForm()
    column = outer.body
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

    if controller.native_lifecycle_failed:
        column.add_widget(Label('Restart Metor', role='title'))
        column.add_widget(
            Label(
                'Desktop security monitoring stopped. Close and restart Metor to continue safely.',
                role='support',
            )
        )
        if controller.purge.active:
            column.add_widget(Label(controller.purge.title, role='support'))
            column.add_widget(Label(controller.purge.detail, role='support'))
        column.add_widget(Action('Close Metor', controller.lifecycle.start))
    elif prompt is not None:

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
            column.add_widget(Label('Start Metor?', role='title'))
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
            start_session = prompt.kind == 'new_session_password'
            label = {
                'new_session_password': 'New session password',
                'unlock_password': 'Profile password',
                'session_auth': 'Profile or session password',
            }[prompt.kind]
            title = 'Start local service' if start_session else 'Open profile'
            column.add_widget(Label(title, role='title'))
            if start_session:
                column.add_widget(
                    Label(
                        'Choose a password for this run of the service.', role='support'
                    )
                )
            elif prompt.kind == 'session_auth':
                column.add_widget(
                    Label(
                        'For an encrypted profile, use its profile password. '
                        'For a plaintext profile, use the password chosen at startup.',
                        role='support',
                    )
                )
            column.add_widget(Label(label, role='support'))
            secret = SecretInput(accessible_name=label)
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
            column.add_widget(Action(title, answer, surface='drop', tone='onAccent'))
            column.add_widget(Action('Cancel', lambda: respond(None)))
    elif controller.lifecycle.active or controller.lifecycle.failed:
        lifecycle_body(controller, column)
    elif state.busy and state.route.view == 'V01':
        column.add_widget(Label('Opening profile', role='title'))
        column.add_widget(
            Label(state.status or 'Please wait…', role='support', tone='textSecondary')
        )
    elif state.route.view == 'V02':
        column.add_widget(Label('Choose profile', role='title'))
        profiles_body(controller, column, startup=True)
        column.add_widget(
            Action('New profile', lambda: navigate('V03'), disabled=state.busy)
        )
        column.add_widget(Action('Back', lambda: navigate('V01'), disabled=state.busy))
    elif state.route.view == 'V03':
        column.add_widget(Label('New profile', role='title'))
        column.add_widget(Label('Name', role='support'))
        name = TextField(
            accessible_name='Profile name',
            multiline=False,
            font_name=font_path(),
            size_hint_y=None,
            height='52dp',
            foreground_color=color('text'),
            background_color=color('raised'),
        )
        name.text = controller.initial_missing_profile or ''
        column.add_widget(name)
        column.add_widget(Label('Password', role='support'))
        password = SecretInput(accessible_name='Password')
        column.add_widget(password)
        column.add_widget(Label('Confirm password', role='support'))
        confirmation = SecretInput(accessible_name='Confirm password')
        column.add_widget(confirmation)
        error = Label('', role='support', tone='danger')

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
                if error.parent is None:
                    column.add_widget(error, index=column.children.index(submit) + 1)
                error.text = 'Enter a name and matching passwords.'
                return
            if controller.create_profile(name.text.strip(), password.text):
                password.text = confirmation.text = ''
                refresh()

        submit = Action(
            'Create profile',
            create,
            surface='drop',
            tone='onAccent',
            disabled=state.busy,
        )
        column.add_widget(submit)
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
        column.add_widget(Label(profile_name, role='title'))
        column.add_widget(
            Action(
                'Open profile',
                open_profile,
                surface='drop',
                tone='onAccent',
                disabled=state.busy,
            )
        )
        alternatives = ActionRow(spacing='8dp')
        alternatives.add_widget(
            Action('Switch profile', lambda: navigate('V02'), disabled=state.busy)
        )
        alternatives.add_widget(
            Action('New profile', lambda: navigate('V03'), disabled=state.busy)
        )

        def arrange(*_args: object) -> None:
            """Stack the secondary choices before their short labels would wrap unevenly."""
            alternatives.orientation = (
                'vertical' if alternatives.width < sp(240) else 'horizontal'
            )

        alternatives.bind(width=arrange)
        arrange()
        column.add_widget(alternatives)
    if (
        state.status
        and not controller.native_lifecycle_failed
        and not (state.busy and state.route.view == 'V01' and prompt is None)
    ):
        column.add_widget(Label(state.status, role='support', tone='info'))
    return outer
