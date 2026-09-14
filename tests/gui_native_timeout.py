"""Native timeout-editor checks for disable confirmation and rejected-save input preservation."""

from collections.abc import Callable
from dataclasses import replace
from unittest.mock import patch

from kivy.clock import Clock
from kivy.core.window import Window

from metor.ui.gui.app import MetorApp
from metor.ui.gui.views.settings.timeout import TimeoutEditor
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet


def exercise_timeout(app: MetorApp, complete: Callable[[], None]) -> None:
    """Uses focused native keys without issuing a real profile policy mutation.

    Args:
        app: Native simulator with synthetic protected preferences.
        complete: Continuation after the failure layout settles.
    Returns:
        None
    """
    current = app.controller.state.preferences
    assert current is not None
    sheet = TimeoutEditor(app.controller, current)
    sheet.show()

    def enter() -> None:
        """Activates the currently labelled primary action through native focus.

        Args:
            None
        Returns:
            None
        """
        primary = next(
            widget
            for widget in sheet.actions.children
            if isinstance(widget, Action) and widget is not sheet.cancel
        )
        primary.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        primary.focus = False

    def retained(_elapsed: float) -> None:
        """Verifies rejection preserves the original input and open editor.

        Args:
            _elapsed: Native failure-state delay.
        Returns:
            None
        """
        assert ActionSheet.current is sheet
        assert sheet.field.text == '300' and not sheet.field.readonly
        assert 'changed elsewhere' in sheet.feedback.text
        complete()

    def reject(_elapsed: float) -> None:
        """Supplies a correlated synthetic rejection after pending layout.

        Args:
            _elapsed: Native pending-state delay.
        Returns:
            None
        """
        assert sheet.field.readonly
        app.controller.preferences.save_state = 'rejected'
        app.controller.preferences.last_error = (
            'Settings changed elsewhere. Review current values.'
        )
        Clock.schedule_once(retained, 0.3)

    def edit(_elapsed: float) -> None:
        """Checks stable focus and the two explicit actions needed to disable lock.

        Args:
            _elapsed: Initial native layout delay.
        Returns:
            None
        """
        state = app.controller.state
        assert state.snapshot is not None
        sheet.field.text = '300'
        sheet.field.focus = True
        state.snapshot = replace(
            state.snapshot, revision=(state.snapshot.revision or 0) + 1
        )
        ActionSheet.reconcile()
        assert sheet.field.focus and sheet.field.text == '300'
        sheet.field.focus = False
        with patch.object(
            app.controller.preferences, 'save', return_value=False
        ) as save:
            sheet.field.text = '0'
            enter()
            save.assert_not_called()
            assert 'remain unlocked' in sheet.feedback.text
            enter()
            save.assert_called_once()
            assert save.call_args.args[0].idle_seconds == 0
            assert save.call_args.args[1] == current.preferences_revision
        sheet.field.text = '300'

        def admitted(_preferences: object, _revision: int) -> bool:
            """Models GUI handoff only, keeping Core and files untouched.

            Args:
                _preferences: Captured proposed value.
                _revision: Original displayed revision.
            Returns:
                bool: Synthetic admission.
            """
            app.controller.preferences.save_serial += 1
            app.controller.preferences.save_state = 'pending'
            return True

        with patch.object(app.controller.preferences, 'save', side_effect=admitted):
            enter()
        Clock.schedule_once(reject, 0.3)

    Clock.schedule_once(edit, 0.3)
