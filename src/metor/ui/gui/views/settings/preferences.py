"""Fixed GUI LIVE policy editors using the protected preference revision captured by the form."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import GuiPreferences, LockedAcceptPolicy
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SettingRow
from metor.ui.gui.widgets.sheet import ActionSheet, confirm


def live_preferences(
    controller: GuiController,
    body: BoxLayout,
    preferences: GuiPreferences,
    save: Callable[[GuiPreferences], None],
) -> None:
    """Adds independent default auto-play, continued-media and locked-call policies.

    Args:
        controller: Authorized public-service GUI owner.
        body: Scrolling settings content.
        preferences: Authoritative document displayed by the containing form.
        save: Revision-qualified mutation callback for that displayed document.
    Returns:
        None
    """
    body.add_widget(Label('Live', role='peer'))
    body.add_widget(
        SettingRow(
            'Auto-play default',
            'On' if preferences.auto_play else 'Off',
            'This profile · new Live conversations only',
            partial(save, replace(preferences, auto_play=not preferences.auto_play)),
            disabled=controller.state.busy,
        )
    )

    def keep_live() -> None:
        """Warns before permitting continued foreground media behind the lock cover.

        Args:
            None
        Returns:
            None
        """
        change = partial(
            save,
            replace(preferences, keep_live_locked=not preferences.keep_live_locked),
        )
        if preferences.keep_live_locked:
            change()
        else:
            confirm(
                controller,
                'Keep Live active while locked',
                'The foreground Live conversation may continue recording and playing while Metor is locked. A visible media control remains. Incoming call acceptance is a separate setting.',
                change,
            )

    body.add_widget(
        SettingRow(
            'Keep Live active while locked',
            'On' if preferences.keep_live_locked else 'Off',
            'This profile · foreground conversation only',
            keep_live,
            disabled=controller.state.busy
            or 'restricted_live_projection' not in controller.state.capabilities,
        )
    )
    labels = {
        LockedAcceptPolicy.NONE: 'None',
        LockedAcceptPolicy.SAVED_CONTACTS: 'Saved contacts',
        LockedAcceptPolicy.ALL: 'All',
    }

    def choose_accept() -> None:
        """Opens the explicit single-choice policy independently of media continuation.

        Args:
            None
        Returns:
            None
        """

        def select(policy: LockedAcceptPolicy) -> None:
            """Confirms wider locked-call permission without opening or calling a peer.

            Args:
                policy: Explicitly selected Core policy.
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            change = partial(save, replace(preferences, accept_live_locked=policy))
            rank = {
                LockedAcceptPolicy.NONE: 0,
                LockedAcceptPolicy.SAVED_CONTACTS: 1,
                LockedAcceptPolicy.ALL: 2,
            }
            if rank[policy] > rank[preferences.accept_live_locked]:
                confirm(
                    controller,
                    'Accept Live while locked',
                    'Allow call acceptance while Metor is locked for: '
                    + labels[policy]
                    + '. Opening a conversation still requires normal unlock.',
                    change,
                )
            else:
                change()

        def build(column: BoxLayout) -> None:
            """Shows the current policy and all meaningful explicit alternatives.

            Args:
                column: Native sheet body.
            Returns:
                None
            """
            column.add_widget(
                Label(
                    'This profile · does not enable automatic acceptance or media playback.',
                    role='support',
                )
            )
            for policy, label in labels.items():
                column.add_widget(
                    Action(
                        label
                        + (
                            ' · selected'
                            if policy is preferences.accept_live_locked
                            else ''
                        ),
                        partial(select, policy),
                        disabled=controller.state.busy,
                    )
                )

        sheet = ActionSheet(
            controller,
            build,
            title='Accept Live while locked',
            rebuild_on_snapshot=False,
        )
        sheet.show()

    body.add_widget(
        SettingRow(
            'Accept Live while locked',
            labels[preferences.accept_live_locked],
            'This profile · permission to accept an incoming request',
            choose_accept,
            disabled=controller.state.busy
            or 'pending_call_handles' not in controller.state.capabilities,
        )
    )
