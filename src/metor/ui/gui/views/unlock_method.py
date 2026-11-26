"""Unlock-method choice shared by first setup and the retained Settings modal."""

from collections.abc import Callable

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import ClientUnlockMethod
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SecretInput
from metor.ui.gui.widgets.sheet import ActionSheet


def build_unlock_methods(
    controller: GuiController,
    refresh: Callable[[], None],
    body: BoxLayout,
    later: Callable[[], object] | None,
    accepted: Callable[[], object],
) -> None:
    """Build the explicit choices without navigating away from the owning surface."""
    state, security = controller.state, controller.security
    body.add_widget(
        Label(
            'Choose how to unlock this application. Opening an encrypted profile still requires its password.',
            tone='textSecondary',
        )
    )
    pin = SecretInput(accessible_name='New PIN')
    confirm = SecretInput(accessible_name='Confirm PIN')
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
        if security.configure(ClientUnlockMethod.PIN, value):
            accepted()
        refresh()

    def configure(method: ClientUnlockMethod) -> None:
        """Applies an explicit setup choice through protected Core metadata.

        Args:
            method: Selected unlock method.
        Returns:
            None
        """
        if security.configure(method):
            accepted()
        refresh()

    def show_pin() -> None:
        """Opens PIN input only after the user selects this setup method.

        Args:
            None
        Returns:
            None
        """
        body.clear_widgets()
        body.add_widget(Label('Set PIN', role='title'))
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
        orientation='vertical', spacing='12dp', size_hint_y=None, height=0
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

    if later is not None:
        body.add_widget(
            Action(
                'Later',
                later,
                disabled=state.busy,
            )
        )


class UnlockMethodSheet(ActionSheet):
    """Keep Settings and its scroll position behind the protected choice."""

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Close only after an admitted choice or a deliberate cancellation."""
        super().__init__(
            controller,
            lambda body: build_unlock_methods(
                controller, refresh, body, None, self.dismiss
            ),
            title='Unlock method',
            rebuild_on_snapshot=False,
            snapshot_updates=False,
        )
        self.cancel.label.text = 'Later'
