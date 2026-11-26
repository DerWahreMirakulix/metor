"""Protected lock-screen privacy choices with scoped values and explicit disclosure warnings."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import GuiPreferences, NotificationPrivacy
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SettingRow
from metor.ui.gui.widgets.sheet import ActionSheet, confirm


def notification_preference(
    controller: GuiController,
    body: BoxLayout,
    preferences: GuiPreferences,
    save: Callable[[GuiPreferences], None],
) -> None:
    """Adds one scoped notification row with a fixed-choice editor.

    Args:
        controller: Authorized public preference owner.
        body: Scrolling settings column.
        preferences: Original displayed protected document.
        save: Original revision-qualified save callback.
    Returns:
        None
    """
    labels = {
        NotificationPrivacy.OFF: 'Off',
        NotificationPrivacy.ANONYMIZE: 'Anonymize',
        NotificationPrivacy.SHOW_ALL: 'Show all',
    }

    def choose() -> None:
        """Shows privacy choices without increasing the current restricted grant.

        Args:
            None
        Returns:
            None
        """

        def select(policy: NotificationPrivacy) -> None:
            """Warns once before exposing more lock-screen information.

            Args:
                policy: Explicit protected per-profile preference.
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            change = partial(save, replace(preferences, notifications_locked=policy))
            ranking = tuple(labels)
            if ranking.index(policy) > ranking.index(preferences.notifications_locked):
                confirm(
                    controller,
                    'Lock screen notifications',
                    'The next lock cycle may show '
                    + (
                        'peer identities and activity types.'
                        if policy is NotificationPrivacy.SHOW_ALL
                        else 'anonymous activity types and counts.'
                    )
                    + ' Message content is never previewed.',
                    change,
                )
            else:
                change()

        def build(column: BoxLayout) -> None:
            """Labels scope and explicit choices without speculative current values.

            Args:
                column: Native modal scroll column.
            Returns:
                None
            """
            column.add_widget(
                Label(
                    'This profile · applies to the next lock cycle. No message-content previews.',
                    role='support',
                )
            )
            for policy, label in labels.items():
                column.add_widget(
                    Action(
                        label
                        + (
                            ' · selected'
                            if policy is preferences.notifications_locked
                            else ''
                        ),
                        partial(select, policy),
                        disabled=controller.state.busy,
                    )
                )

        sheet = ActionSheet(
            controller,
            build,
            title='Lock screen notifications',
            rebuild_on_snapshot=False,
        )
        sheet.show()

    body.add_widget(
        SettingRow(
            'Lock screen notifications',
            labels[preferences.notifications_locked],
            'This profile · message content is never previewed',
            choose,
            disabled=controller.state.busy,
        )
    )


def profile_name_preference(
    controller: GuiController,
    body: BoxLayout,
    preferences: GuiPreferences,
    save: Callable[[GuiPreferences], None],
) -> None:
    """Adds the explicit profile-name disclosure preference in Device settings.

    Args:
        controller: Authorized preference owner.
        body: Settings column.
        preferences: Original displayed document.
        save: Captured revision-qualified update.
    Returns:
        None
    """

    def change() -> None:
        """Confirms disclosure before enabling it and directly allows hiding it.

        Args:
            None
        Returns:
            None
        """
        update = partial(
            save,
            replace(
                preferences, show_profile_locked=not preferences.show_profile_locked
            ),
        )
        if preferences.show_profile_locked:
            update()
        else:
            confirm(
                controller,
                'Show profile name',
                'This profile name will be visible on the lock screen. Message content remains covered.',
                update,
            )

    body.add_widget(
        SettingRow(
            'Show profile name',
            'On' if preferences.show_profile_locked else 'Off',
            'This profile · name visible on the lock screen',
            change,
            disabled=controller.state.busy,
        )
    )
