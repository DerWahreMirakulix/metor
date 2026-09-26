"""Private full-viewport application lock and protected lock-method setup views."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import ClientUnlockMethod, NotificationPrivacy, Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, SecretInput


class LockedActivity(Action):
    """Updates a content-free activity cue without recreating the native unlock field.

    No historical count is inferred from the unread inventory.
    """

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Creates a hidden target until Core permits a current-cycle DROP observation.

        Args:
            controller: Same-client restricted state owner.
            refresh: Native repaint request.
        Returns:
            None
        """
        self.controller = controller

        def activate() -> None:
            """Requests normal unlock before exposing notification state.

            Args:
                None
            Returns:
                None
            """
            controller.notifications.open_locked()
            refresh()

        super().__init__('', activate)
        self.update()

    def update(self) -> None:
        """Repaints only permitted generic activity, preserving focused controls nearby.

        Args:
            None
        Returns:
            None
        """
        security = self.controller.security
        visible = (
            self.controller.state.covered
            and security.restriction is not None
            and security.notification_privacy is not NotificationPrivacy.OFF
            and bool(self.controller.notifications.locked_activity)
        )
        self.opacity = 1 if visible else 0
        self.disabled = not visible
        self.height = dp(48) if visible else 0
        activity = self.controller.notifications.locked_activity
        text = (
            'New Drop'
            if activity == {Delivery.DROP}
            else 'New Live activity'
            if activity == {Delivery.LIVE}
            else 'New activity'
        )
        self.label.text = self.accessible_name = (
            text + ' · Unlock to view' if visible else ''
        )


def security_view(
    controller: GuiController, refresh: Callable[[], None]
) -> AnchorLayout:
    """Uses a full opaque viewport with no contact-bearing master panel.

    Args:
        controller: Active client authorization owner.
        refresh: Native repaint request.
    Returns:
        AnchorLayout: Centered, measured private form.
    """
    outer = AnchorLayout(padding=dp(Geometry.EDGE))
    scroll = ScrollView(
        size_hint=(None, None), width=dp(Geometry.FORM_MAX), do_scroll_x=False
    )
    outer.bind(
        width=lambda owner, value: setattr(
            scroll, 'width', min(dp(Geometry.FORM_MAX), value - dp(Geometry.EDGE * 2))
        )
    )
    body = BoxLayout(
        orientation='vertical', spacing=dp(8), size_hint_y=None, padding=(0, dp(24))
    )
    body.bind(minimum_height=body.setter('height'))

    def fit_cover(*_args: object) -> None:
        """Keeps a fitting lock form fixed while allowing overflow to remain reachable.

        Args:
            _args: Native layout or notification changes.
        Returns:
            None
        """
        available = max(0, outer.height - outer.padding[1] - outer.padding[3])
        scroll.height = min(body.minimum_height, available)
        scroll.do_scroll_y = body.minimum_height > available

    outer.bind(height=fit_cover, padding=fit_cover)
    body.bind(minimum_height=fit_cover)
    scroll.add_widget(body)
    outer.add_widget(scroll)
    body.add_widget(Label('Metor', role='hero'))
    state, security = controller.state, controller.security
    if state.route.view == 'V05':
        body.add_widget(Label('Locked', role='peer'))
        body.add_widget(LockedActivity(controller, refresh))
        if security.profile_label:
            body.add_widget(Label(security.profile_label, role='support'))
        restriction = security.restriction
        if restriction is not None:
            method = restriction.unlock_method
            secret = SecretInput()
            if method is ClientUnlockMethod.PIN:
                secret.input_purpose = 'pin'
            if method is not ClientUnlockMethod.NONE:
                body.add_widget(
                    Label(
                        'PIN'
                        if method is ClientUnlockMethod.PIN
                        else 'Profile password',
                        role='support',
                    )
                )
                body.add_widget(secret)

            def unlock() -> None:
                """Transfers a single secret then clears the native field.

                Args:
                    None
                Returns:
                    None
                """
                value = secret.text
                secret.text = ''
                security.unlock(value)
                refresh()

            secret.bind(on_text_validate=lambda *_args: unlock())
            if method is ClientUnlockMethod.PIN:
                keypad = GridLayout(
                    cols=3, spacing=dp(8), size_hint_y=None, height=dp(48 * 4 + 8 * 3)
                )
                for key in (
                    '1',
                    '2',
                    '3',
                    '4',
                    '5',
                    '6',
                    '7',
                    '8',
                    '9',
                    '⌫',
                    '0',
                    'Unlock',
                ):

                    def press(value: str = key) -> None:
                        """Routes one explicit keypad activation to its masked field.

                        Args:
                            value: Key label.
                        Returns:
                            None
                        """
                        if value == 'Unlock':
                            unlock()
                        elif value == '⌫':
                            secret.do_backspace()
                        else:
                            secret.insert_text(value)

                    keypad.add_widget(Action(key, press, disabled=state.busy))
                body.add_widget(keypad)

                def forgot_pin() -> None:
                    """Requests password recovery without submitting a wrong PIN.

                    Args:
                        None
                    Returns:
                        None
                    """
                    security.unlock(password=True)
                    refresh()

                body.add_widget(
                    Action(
                        'Forgot PIN?',
                        forgot_pin,
                        disabled=state.busy,
                    )
                )
            else:
                body.add_widget(
                    Action(
                        'Unlock',
                        unlock,
                        surface='drop',
                        tone='onAccent',
                        disabled=state.busy,
                    )
                )
    else:
        body.add_widget(Label('Secure Metor', role='peer'))
        body.add_widget(
            Label(
                'Choose how to unlock this application. Opening an encrypted profile still requires its password.',
                tone='textSecondary',
            )
        )
        pin, confirm = SecretInput(), SecretInput()
        pin.input_purpose = confirm.input_purpose = 'pin'
        error = Label('', role='support', tone='danger')

        def configure_pin() -> None:
            """Matches user entry before Core performs sensitive authorization.

            Args:
                None
            Returns:
                None
            """
            if not pin.text or pin.text != confirm.text:
                error.text = 'Enter matching PINs'
                return
            value = pin.text
            pin.text = confirm.text = ''
            security.configure(ClientUnlockMethod.PIN, value)
            refresh()

        def configure(method: ClientUnlockMethod) -> None:
            """Applies an explicit setup choice through protected Core metadata.

            Args:
                method: Selected unlock method.
            Returns:
                None
            """
            security.configure(method)
            refresh()

        def show_pin() -> None:
            """Opens PIN input only after the user selects this setup method.

            Args:
                None
            Returns:
                None
            """
            body.clear_widgets()
            body.add_widget(Label('Set PIN', role='hero'))
            body.add_widget(Label('New PIN', role='support'))
            body.add_widget(pin)
            body.add_widget(Label('Confirm PIN', role='support'))
            body.add_widget(confirm)
            body.add_widget(error)
            body.add_widget(
                Action(
                    'Save PIN',
                    configure_pin,
                    surface='drop',
                    tone='onAccent',
                    disabled=state.busy,
                )
            )
            body.add_widget(
                Action(
                    'Use profile password',
                    lambda: configure(ClientUnlockMethod.PROFILE_PASSWORD),
                    disabled=state.busy,
                )
            )

        body.add_widget(Action('Set PIN', show_pin, disabled=state.busy))
        body.add_widget(
            Action(
                'Use profile password',
                lambda: configure(ClientUnlockMethod.PROFILE_PASSWORD),
                surface='drop',
                tone='onAccent',
                disabled=state.busy,
            )
        )
        warning = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None, height=0
        )
        warning.bind(minimum_height=warning.setter('height'))

        def warn_none() -> None:
            """Requires a separate explicit confirmation before weakening lock policy.

            Args:
                None
            Returns:
                None
            """
            warning.clear_widgets()
            warning.add_widget(
                Label(
                    'Anyone with access to this running application can unlock it. The profile password is still required at startup.',
                    tone='danger',
                )
            )
            warning.add_widget(
                Action(
                    'Confirm no screen lock',
                    lambda: configure(ClientUnlockMethod.NONE),
                    surface='danger',
                    tone='onAccent',
                    disabled=state.busy,
                )
            )

        body.add_widget(Action('No screen lock', warn_none, disabled=state.busy))
        body.add_widget(warning)

        def later() -> None:
            """Leaves the conservative uncompleted password default in force.

            Args:
                None
            Returns:
                None
            """
            state.route = Route('V06')
            refresh()

        body.add_widget(
            Action(
                'Later',
                later,
                disabled=state.busy,
            )
        )
    if state.status:
        body.add_widget(Label(state.status, role='support', tone='info'))
    fit_cover()
    return outer
