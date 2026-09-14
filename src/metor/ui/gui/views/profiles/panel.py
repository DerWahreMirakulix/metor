"""Bounded native profile rows and explicit current-profile identity actions."""

from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.client import (
    FrontendProfileAction,
    FrontendProfileChange,
    FrontendProfileState,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet, confirm
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from .forms import ProfileEditor


def profiles_body(
    controller: GuiController, body: BoxLayout, *, startup: bool = False
) -> None:
    """Renders one host-provided metadata page without exposing peer or activity previews.

    Args:
        controller: Public profile catalog owner.
        body: Native bounded scroll column.
        startup: Selects a pre-activation entry rather than invoking runtime switch.
    Returns:
        None
    """
    catalog, state = controller.profiles, controller.state
    page = catalog.page
    if catalog.error:
        body.add_widget(Label(catalog.error, role='support', tone='danger'))
    if page is None:
        body.add_widget(
            Label(
                'Loading profiles' if state.busy else 'Profile catalog unavailable',
                tone='textSecondary',
            )
        )
    else:
        if not startup:
            body.add_widget(Label('Current: ' + page.selected_profile, role='peer'))
            body.add_widget(
                Label(
                    'Default: ' + page.default_profile,
                    role='support',
                    tone='textSecondary',
                )
            )
        if not page.entries:
            body.add_widget(Label('No profiles', role='peer'))
        for profile in page.entries:
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
            label = profile.profile + (
                ' · Default' if profile.profile == page.default_profile else ''
            )
            row.add_widget(
                Action(
                    label,
                    partial(select_profile, controller, profile.profile, startup),
                    disabled=state.busy
                    or (not startup and profile.profile == page.selected_profile),
                )
            )
            if not startup:
                row.add_widget(
                    IconAction(
                        'ellipsis',
                        'Profile actions',
                        partial(profile_menu, controller, profile),
                        disabled=state.busy,
                    )
                )
            body.add_widget(row)
        if page.next_after is not None:
            body.add_widget(
                Action(
                    'More profiles',
                    partial(catalog.reload, page.next_after),
                    disabled=state.busy,
                )
            )
    body.add_widget(Action('Reload first page', catalog.reload, disabled=state.busy))
    if startup:
        return
    body.add_widget(
        Action(
            'New profile',
            lambda: ProfileEditor(controller, 'create').show(),
            disabled=catalog.host is None or state.busy,
        )
    )
    body.add_widget(Action('My contact', lambda: controller.navigate(Route('V15'))))
    body.add_widget(
        Action(
            'Change password',
            lambda: ProfileEditor(controller, 'password').show(),
            disabled=state.busy or controller.identity.unknown,
        )
    )
    body.add_widget(
        Action(
            'Generate new address',
            lambda: confirm(
                controller,
                'Generate new address',
                'This replaces the profile’s published identity if Metor permits rotation. Contacts need the new address. Existing conversations are not promised to follow the new identity.',
                controller.identity.generate_address,
            ),
            disabled=state.busy or controller.identity.unknown,
        )
    )
    body.add_widget(
        Label(
            'Address generation is refused while the profile runtime is running.',
            role='support',
            tone='textSecondary',
        )
    )


def select_profile(controller: GuiController, name: str, startup: bool = False) -> None:
    """Separates startup selection from the accepted public runtime switch transaction.

    Args:
        controller: Public host and lifecycle owner.
        name: Exact original profile name selected by the user.
        startup: Whether no active runtime belongs to this GUI.
    Returns:
        None
    """
    if startup:
        controller.profiles.select(name)
        return
    snapshot = controller.state.snapshot
    active = (
        sum(
            item.session_state in {'connected', 'connecting', 'reconnecting', 'pending'}
            for item in snapshot.live_contexts
        )
        if snapshot
        else 0
    )
    pending = (
        sum(item.pending_outbound_count for item in snapshot.live_contexts)
        if snapshot
        else 0
    )
    drafts = len(controller.state.drafts) + len(controller.voice.reviews)
    others = max(0, (snapshot.authenticated_client_count or 1) - 1) if snapshot else 0
    requests = len(snapshot.pending) if snapshot else 0
    shared = (
        f'{others} other attached clients. '
        if snapshot is not None and snapshot.authenticated_client_count is not None
        else 'Other attached clients are also affected. '
    )
    if controller.voice.running:
        drafts += 1
    action = partial(controller.lifecycle.start, name)
    if active or pending or drafts or others or requests:
        confirm(
            controller,
            'Switch profile',
            f'{active} active Live connections · {pending} pending Live messages · {requests} pending calls · {drafts} local drafts or recordings. '
            + shared
            + 'Authorized recording is finalized locally; this GUI’s uncommitted Drop recordings and text drafts are discarded. '
            'Metor preserves queued messages under its current fallback policy and locks this profile for all attached clients.',
            action,
        )
    else:
        action()


def profile_menu(controller: GuiController, profile: FrontendProfileState) -> None:
    """Captures canonical names; Core/base rechecks running/default/active eligibility.

    Args:
        controller: Current permitted host catalog owner.
        profile: Exact metadata row used to open this menu.
    Returns:
        None
    """
    page = controller.profiles.page
    if page is None:
        return
    selected = page.selected_profile

    def change(action: FrontendProfileAction) -> None:
        """Submits one originally captured host selection and target.

        Args:
            action: Explicit local catalog mutation.
        Returns:
            None
        """
        sheet.dismiss(animation=False)
        controller.profiles.change(
            FrontendProfileChange(action, profile.profile, selected)
        )

    def remove() -> None:
        """Shows one effects confirmation for exactly this local profile entry.

        Args:
            None
        Returns:
            None
        """
        sheet.dismiss(animation=False)
        confirm(
            controller,
            'Remove profile',
            (
                'Remove this local remote-connection entry? The remote profile is not destroyed.'
                if profile.remote
                else 'Permanently remove this local profile and its stored data? This cannot be undone.'
            )
            + ' Profile: '
            + profile.profile,
            partial(change, FrontendProfileAction.REMOVE),
        )

    def build(body: BoxLayout) -> None:
        """Presents scope and eligibility without stopping any running runtime.

        Args:
            body: Native modal content column.
        Returns:
            None
        """
        body.add_widget(Label(profile.profile, role='peer'))
        if profile.profile == selected:
            body.add_widget(
                Action(
                    'Change password',
                    lambda: ProfileEditor(controller, 'password').show(),
                )
            )
        body.add_widget(
            Action(
                'Set default',
                partial(change, FrontendProfileAction.SET_DEFAULT),
                disabled=profile.profile == page.default_profile,
            )
        )
        body.add_widget(
            Action(
                'Rename',
                lambda: ProfileEditor(controller, 'rename', profile.profile).show(),
                disabled=profile.daemon_running,
            )
        )
        body.add_widget(
            Action(
                'Remove profile',
                remove,
                tone='danger',
                disabled=profile.daemon_running
                or profile.profile in {selected, page.default_profile},
            )
        )
        if profile.daemon_running:
            body.add_widget(
                Label('Running profiles cannot be renamed or removed.', role='support')
            )
        elif profile.profile in {selected, page.default_profile}:
            body.add_widget(
                Label(
                    'Choose another current and default profile before removal.',
                    role='support',
                )
            )

    sheet = ActionSheet(controller, build, title='Profile actions', compact_menu=True)
    sheet.show()
