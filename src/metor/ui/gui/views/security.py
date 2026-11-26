"""Private full-viewport application lock and protected lock-method setup views."""

from collections.abc import Callable

from kivy.core.text import Label as TextMeasure
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout

from metor.core.api import ClientUnlockMethod, NotificationPrivacy, Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, SecretInput

# Local Package Imports
from .cover import PrivateForm
from .unlock_method import build_unlock_methods


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

    def _measure(self, *_args: object) -> None:
        """Exclude an absent activity cue from the private form's height."""
        if self.opacity:
            super()._measure(*_args)
        else:
            self.height = 0

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
        self._measure()


class LockFeedback(Label):
    """Reserve the ordinary failure message's measured space before the first attempt."""

    def _measure(self, *_args: object) -> None:
        """Measure reserved feedback even while its native text texture is empty."""
        super()._measure(*_args)
        self._height()

    def _height(self, *_args: object) -> None:
        """Keep the centered form steady when empty or failed attempts report feedback."""
        measured = TextMeasure(
            text='Could not unlock. Try again.',
            font_name=self.font_name,
            font_size=self.font_size,
            text_size=(self.width, None),
        )
        self.height = max(
            dp(self._line_units), measured.render()[1], self.texture_size[1]
        )


class LockedView(PrivateForm):
    """Retain masked input and layout while a challenge or cooldown updates."""

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Build one cover for the current unlock method and generation."""
        super().__init__()
        self.controller = controller
        state, security = controller.state, controller.security
        self.identity = self.current_identity()
        body = self.body
        body.add_widget(Label('Locked', role='title'))
        self.activity = LockedActivity(controller, refresh)
        body.add_widget(self.activity)
        if security.profile_label:
            body.add_widget(Label(security.profile_label, role='support'))
        restriction = security.restriction
        if restriction is not None:
            method = restriction.unlock_method
            self.secret = secret = SecretInput(
                accessible_name='PIN'
                if method is ClientUnlockMethod.PIN
                else 'Profile password'
            )
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
                if state.busy or security.retry_seconds:
                    return
                value = secret.text
                secret.text = ''
                security.unlock(value)
                refresh()

            secret.bind(on_text_validate=lambda *_args: unlock())
            if method is ClientUnlockMethod.PIN:
                keypad = GridLayout(
                    cols=3,
                    spacing='8dp',
                    size_hint_y=None,
                )
                keypad.bind(minimum_height=keypad.setter('height'))
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

                    button = Action(
                        key,
                        press,
                        surface='drop' if key == 'Unlock' else 'raised',
                        tone='onAccent' if key == 'Unlock' else 'text',
                        disabled=state.busy or bool(security.retry_seconds),
                    )
                    button.padding = ('4dp', '8dp')
                    if key == 'Unlock':
                        width, _ = TextMeasure(
                            font_name=button.label.font_name,
                            font_size=button.label.font_size,
                        ).get_extents(key)
                        button.size_hint_min_x = (
                            width + button.padding[0] + button.padding[2]
                        )
                    elif key == '⌫':
                        button.accessible_name = 'Delete last PIN digit'
                    keypad.add_widget(button)
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
                        disabled=state.busy or bool(security.retry_seconds),
                    )
                )
            else:
                body.add_widget(
                    Action(
                        'Unlock',
                        unlock,
                        surface='drop',
                        tone='onAccent',
                        disabled=state.busy or bool(security.retry_seconds),
                    )
                )
        self.feedback = LockFeedback('', role='support', tone='info')
        self.body.add_widget(self.feedback)
        self.update()

    def current_identity(self) -> tuple[object, ...]:
        """Separate method transitions and client generations from new challenges."""
        security = self.controller.security
        return (
            self.controller.state.generation,
            security.restriction.unlock_method if security.restriction else None,
            security.profile_label,
        )

    def update(self) -> None:
        """Refresh safe feedback and submission eligibility without rebuilding controls."""
        state, security = self.controller.state, self.controller.security
        self.activity.update()
        seconds = security.retry_seconds
        unit = 'second' if seconds == 1 else 'seconds'
        self.feedback.text = (
            f'Try again in {seconds} {unit}' if seconds else state.status
        )
        for widget in self.body.walk():
            if isinstance(widget, Action) and widget is not self.activity:
                widget.disabled = state.busy or bool(security.retry_seconds)

    def revoke(self) -> None:
        """Clear a departing challenge's input and native focus before detaching it."""
        for widget in self.body.walk():
            if isinstance(widget, SecretInput):
                widget.text = ''
                widget.focus = False
                widget.disabled = True
            elif isinstance(widget, Action):
                widget.cancel_input()
                widget.focus = False
                widget.disabled = True


def security_view(
    controller: GuiController, refresh: Callable[[], None]
) -> AnchorLayout:
    """Present the opaque lock cover or initial profile setup."""
    if controller.state.route.view == 'V05':
        return LockedView(controller, refresh)
    outer = PrivateForm()
    outer.body.add_widget(Label('Secure Metor', role='title'))

    def later() -> None:
        """Leave the conservative initial password policy in place."""
        controller.state.route = Route('V06')
        refresh()

    build_unlock_methods(controller, refresh, outer.body, later, lambda: None)
    if controller.state.status:
        outer.body.add_widget(
            Label(controller.state.status, role='support', tone='info')
        )
    return outer
