"""Focus-preserving profile name and masked password forms with explicit save outcomes."""

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.client import (
    FrontendProfileAction,
    FrontendProfileChange,
    valid_frontend_profile_name,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField
from metor.ui.gui.widgets.sheet import ActionSheet


class ProfileEditor(ActionSheet):
    """Owns one captured catalog target or the current authenticated profile password."""

    def __init__(self, controller: GuiController, mode: str, profile: str = '') -> None:
        """Captures the displayed host selection before any name or password is entered.

        Args:
            controller: Current GUI public-service owner.
            mode: Create, rename or password operation.
            profile: Original canonical rename target.
        Returns:
            None
        """
        self.mode, self.profile = mode, profile
        page = controller.profiles.page
        self.selected = page.selected_profile if page else ''
        self.name = TextField(
            text=profile, multiline=False, size_hint_y=None, height=dp(52)
        )
        self.current_password = SecretInput()
        self.password = SecretInput()
        self.confirmation = SecretInput()
        self.feedback = Label('', role='support', tone='danger')
        self._serial: int | None = None
        super().__init__(
            controller,
            self._content,
            title={
                'create': 'New profile',
                'rename': 'Rename profile',
                'password': 'Change password',
            }[mode],
            primary=('Create profile' if mode == 'create' else 'Save', self._save),
            primary_tone='text',
            rebuild_on_snapshot=False,
            footer=Label(
                'Current profile · full password required'
                if mode == 'password'
                else 'Local profile catalog · active selection is preserved',
                role='support',
                tone='textSecondary',
            ),
        )
        self.bind(on_dismiss=self._clear)
        Clock.schedule_interval(self._poll, GuiLimits.UI_TICK_SECONDS)

    def _content(self, body: BoxLayout) -> None:
        """Builds a scrollable form above its fixed save/cancel and scope controls.

        Args:
            body: Native modal content column.
        Returns:
            None
        """
        if self.mode != 'password':
            body.add_widget(Label('Name', role='support'))
            body.add_widget(self.name)
            body.add_widget(
                Label(
                    'Letters, numbers, hyphens and underscores.',
                    role='support',
                    tone='textSecondary',
                )
            )
        if self.mode == 'password':
            body.add_widget(Label('Current profile password', role='support'))
            body.add_widget(self.current_password)
        if self.mode != 'rename':
            body.add_widget(Label('New password', role='support'))
            body.add_widget(self.password)
            body.add_widget(Label('Confirm password', role='support'))
            body.add_widget(self.confirmation)
        body.add_widget(self.feedback)

    def _save(self) -> None:
        """Validates exact input and transfers secrets only after one admitted action.

        Args:
            None
        Returns:
            None
        """
        if self._serial is not None or self.controller.state.busy:
            return
        if self.mode != 'password' and not valid_frontend_profile_name(self.name.text):
            self.feedback.text = 'Enter a valid profile name.'
            return
        if self.mode != 'rename' and (
            not self.password.text or self.password.text != self.confirmation.text
        ):
            self.feedback.text = 'Enter matching, nonempty new passwords.'
            return
        if self.mode == 'password':
            if not self.current_password.text:
                self.feedback.text = 'Enter the full current profile password.'
                return
            admitted = self.controller.identity.change_password(
                self.current_password.text, self.password.text
            )
            serial = self.controller.identity.serial
        elif self.mode == 'rename':
            admitted = self.controller.profiles.change(
                FrontendProfileChange(
                    FrontendProfileAction.RENAME,
                    self.profile,
                    self.selected,
                    self.name.text,
                )
            )
            serial = self.controller.profiles.serial
        else:
            admitted = self.controller.profiles.create(
                self.name.text, self.password.text
            )
            serial = self.controller.profiles.serial
        if admitted:
            self._serial = serial
            self.current_password.text = self.password.text = self.confirmation.text = (
                ''
            )
            self.feedback.text = 'Saving'
        else:
            self.feedback.text = (
                'This change is unavailable. Review the current profile state.'
            )

    def _poll(self, _elapsed: float) -> None:
        """Closes only after the correlated positive result and retains rejected name input.

        Args:
            _elapsed: Native scheduler interval.
        Returns:
            None
        """
        owner = (
            self.controller.identity
            if self.mode == 'password'
            else self.controller.profiles
        )
        if self._serial is not None and owner.serial == self._serial:
            if owner.outcome == 'saved':
                self.dismiss(animation=False)
                return
            if owner.outcome in {'rejected', 'unknown'}:
                self._serial = None
                self.feedback.text = owner.error
        for field in (
            self.name,
            self.current_password,
            self.password,
            self.confirmation,
        ):
            field.readonly = self._serial is not None
        for action in self.actions.children:
            if isinstance(action, Action) and action is not self.cancel:
                action.disabled = (
                    self._serial is not None
                    or self.controller.state.busy
                    or owner.unknown
                )

    def _clear(self, *_args: object) -> None:
        """Drops all local input and scheduled callbacks when the form is dismissed or covered.

        Args:
            _args: Native dismissal metadata.
        Returns:
            None
        """
        Clock.unschedule(self._poll)
        for field in (
            self.name,
            self.current_password,
            self.password,
            self.confirmation,
        ):
            field.text = ''
