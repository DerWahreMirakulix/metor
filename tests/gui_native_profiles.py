"""Synthetic native profile forms and exact-target interaction checks without host mutations."""

from collections.abc import Callable
from dataclasses import replace
from unittest.mock import patch

from kivy.clock import Clock
from kivy.core.window import Window

from metor.client import FrontendProfileCatalog, FrontendProfileState
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.views.profiles.forms import ProfileEditor
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet


def configure_profiles(controller: GuiController) -> None:
    """Installs bounded synthetic host metadata and no profile files or runtime IO.

    Args:
        controller: Native simulator controller.
    Returns:
        None
    """
    controller.state.route = Route('V20')
    controller.profiles.page = FrontendProfileCatalog(
        (
            FrontendProfileState('Personal', True, False, True),
            FrontendProfileState('Travel', True, False, False),
            FrontendProfileState('Work', True, True, False),
        ),
        'Personal',
        'Personal',
    )


def exercise_profile_editor(app: MetorApp, complete: Callable[[], None]) -> None:
    """Checks captured target, safe initial focus and rejected name retention on native controls.

    Args:
        app: Running native fixture with synthetic catalog metadata.
        complete: Continuation after rejected-form geometry settles.
    Returns:
        None
    """
    sheet = ProfileEditor(app.controller, 'rename', 'Travel')
    sheet.show()

    def edit(_elapsed: float) -> None:
        """Retains original target despite a newer displayed catalog and snapshot.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        assert sheet.cancel.focus
        sheet.name.text = 'Travel_2026'
        sheet.name.focus = True
        state = app.controller.state
        state.snapshot = replace(state.snapshot, revision=4)
        ActionSheet.reconcile()
        assert sheet.name.focus and sheet.name.text == 'Travel_2026'
        page = app.controller.profiles.page
        app.controller.profiles.page = replace(page, selected_profile='Work')
        sheet.name.focus = False
        primary = next(
            widget
            for widget in sheet.actions.children
            if isinstance(widget, Action) and widget is not sheet.cancel
        )

        def admitted(change: object) -> bool:
            """Records the original host context without performing a profile mutation.

            Args:
                change: Captured public change DTO.
            Returns:
                bool: Synthetic UI admission.
            """
            assert change.profile == 'Travel'
            assert change.selected_profile == 'Personal'
            assert change.new_name == 'Travel_2026'
            app.controller.profiles.serial += 1
            app.controller.profiles.outcome = 'pending'
            return True

        with patch.object(
            app.controller.profiles, 'change', side_effect=admitted
        ) as change:
            primary.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            change.assert_called_once()
        Clock.schedule_once(reject, 0.3)

    def reject(_elapsed: float) -> None:
        """Applies a synthetic stale-context refusal while preserving edited name text.

        Args:
            _elapsed: Native pending-frame interval.
        Returns:
            None
        """
        assert sheet.name.readonly
        app.controller.profiles.outcome = 'rejected'
        app.controller.profiles.error = (
            'The selected profile changed. Reload the catalog.'
        )
        Clock.schedule_once(verify, 0.3)

    def verify(_elapsed: float) -> None:
        """Verifies rejection remains visible with reachable fixed actions.

        Args:
            _elapsed: Native error-frame interval.
        Returns:
            None
        """
        assert ActionSheet.current is sheet
        assert sheet.name.text == 'Travel_2026' and not sheet.name.readonly
        assert 'selected profile changed' in sheet.feedback.text
        assert sheet.cancel.y >= sheet.y
        complete()

    Clock.schedule_once(edit, 0.3)
