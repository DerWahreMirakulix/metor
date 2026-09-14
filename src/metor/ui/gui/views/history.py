"""Activity and technical history as metadata-only, explicitly paged native rows."""

from datetime import datetime

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.theme import TYPE
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet


def confirm_history_clear(controller: GuiController) -> None:
    """Explains the exact all-profile ledger operation before its only submission.

    Args:
        controller: Current public SDK action owner.
    Returns:
        None
    """

    def content(column: BoxLayout) -> None:
        """States persisted-ledger and orphan-contact consequences.

        Args:
            column: Measured confirmation content.
        Returns:
            None
        """
        column.add_widget(
            Label(
                'Clear all activity history for this profile, including technical history? '
                'Core also removes discovered contacts that become unused. '
                'Saved contacts and pending or retained messages are preserved. '
                'Recording settings stay as configured.',
                role='body',
            )
        )

    def accept() -> None:
        """Closes the confirmation after admitting its single ledger operation.

        Args:
            None
        Returns:
            None
        """
        if controller.history.clear():
            sheet.dismiss(animation=False)

    sheet = ActionSheet(
        controller,
        content,
        title='Clear activity history',
        primary=('Clear', accept),
    )
    sheet.show()


def history_body(controller: GuiController, body: BoxLayout) -> None:
    """Builds one finite metadata page, current retention and safe retry controls.

    Args:
        controller: Authorized history projection owner.
        body: Outer secondary-view scrolling column.
    Returns:
        None
    """
    history = controller.history
    if 'history_metadata_pages' not in controller.state.capabilities:
        body.add_widget(
            Label(
                'Activity history requires service support for bounded metadata pages.',
                role='support',
            )
        )
        return
    page = history.page
    busy = controller.state.busy or history.pending
    if history.error:
        body.add_widget(Label(history.error, role='support', tone='danger'))
    if page is None:
        body.add_widget(
            Label(
                'Loading activity history'
                if controller.state.busy
                else 'Activity history has not been loaded.',
                role='support',
            )
        )
    else:
        if page.record_live is False and page.record_drop is False:
            body.add_widget(Label('Activity recording is off', role='body'))
            body.add_widget(
                Action(
                    'Open privacy settings', lambda: controller.navigate(Route('V17'))
                )
            )
        else:
            body.add_widget(
                Label(
                    'Recording: Live '
                    + ('On' if page.record_live else 'Off')
                    + ' · Drop '
                    + ('On' if page.record_drop else 'Off'),
                    role='support',
                )
            )
        if not page.entries:
            body.add_widget(
                Label(
                    'No displayable activity on this page'
                    if page.has_older or len(history.anchors) > 1
                    else 'No activity recorded',
                    tone='textSecondary',
                )
            )
        for entry in page.entries:
            row = BoxLayout(
                orientation='vertical',
                spacing=dp(4),
                padding=(0, dp(12)),
                size_hint_y=None,
            )
            row.bind(minimum_height=row.setter('height'))
            row.add_widget(
                Label(
                    entry.event_code.value.replace('_', ' ').capitalize(), role='body'
                )
            )
            identity = entry.alias or entry.peer_onion
            if identity:
                identity_label = Label(identity, role='support', wrap=False)
                identity_label.size_hint = (1, None)
                identity_label.height = sp(TYPE['support'][1])
                row.add_widget(identity_label)
            try:
                timestamp = (
                    datetime.fromisoformat(entry.timestamp)
                    .astimezone()
                    .strftime('%Y-%m-%d %H:%M')
                )
            except ValueError:
                timestamp = 'Time unavailable'
            row.add_widget(Label(timestamp, role='support', tone='textSecondary'))
            details = [entry.family.value, entry.actor.value]
            if entry.detail_code is not None:
                details.append(entry.detail_code.value.replace('_', ' '))
            if history.raw and entry.trigger is not None:
                details.append(entry.trigger.value.replace('_', ' '))
            row.add_widget(Label(' · '.join(details), role='support'))
            body.add_widget(row)
    navigation = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
    navigation.add_widget(
        Action(
            'Newer',
            lambda: history.move('newer'),
            disabled=busy or len(history.anchors) <= 1,
        )
    )
    navigation.add_widget(
        Action(
            'Older',
            lambda: history.move('older'),
            disabled=busy
            or page is None
            or not page.has_older
            or len(history.anchors) >= GuiLimits.HISTORY_ANCHORS,
        )
    )
    body.add_widget(navigation)
    if len(history.anchors) >= GuiLimits.HISTORY_ANCHORS:
        body.add_widget(
            Label(
                'History navigation limit reached. Return to the newest page to refresh.',
                role='support',
            )
        )
    body.add_widget(
        Action(
            'Refresh newest',
            lambda: history.move('first'),
            disabled=controller.state.busy,
        )
    )
