"""Synthetic native profile forms and exact-target interaction checks without host mutations."""

from collections.abc import Callable
from dataclasses import replace
from unittest.mock import patch

from kivy.clock import Clock
from kivy.core.window import Window

from metor.client import (
    FrontendProfileCatalog,
    FrontendProfileState,
    FrontendProfileOperationResult,
)
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
        assert not sheet.scroll.do_scroll_y
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


def exercise_profile_address(app: MetorApp, complete: Callable[[], None]) -> None:
    """Checks native offline-address credentials, repeat barrier and exact readback after uncertainty.

    Args:
        app: Native simulator with a synthetic profile catalog and no host mutations.
        complete: Continuation after the confirmed public-address layout settles.
    Returns:
        None
    """
    sheet = ProfileEditor(app.controller, 'address', 'Travel')
    sheet.show()
    identity = app.controller.identity

    def enter(_elapsed: float) -> None:
        """Admits one synthetic generation through the actual focused native primary control.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        assert sheet.cancel.focus
        sheet.current_password.text = 'synthetic-full-password'
        primary = next(
            item
            for item in sheet.actions.children
            if isinstance(item, Action) and item is not sheet.cancel
        )

        def admit(
            profile: str, selected: str, password: str, *, generate: bool = True
        ) -> bool:
            """Records exact original ownership and supplies only synthetic admission.

            Args:
                profile: Immutable original catalog target.
                selected: Host selection captured by the opened form.
                password: Synthetic one-use input.
                generate: Explicit generation intent.
            Returns:
                bool: Accepted fixture operation.
            """
            assert (profile, selected, password, generate) == (
                'Travel',
                'Personal',
                'synthetic-full-password',
                True,
            )
            identity.serial += 1
            identity.outcome = 'pending'
            return True

        with patch.object(identity, 'offline_address', side_effect=admit) as request:
            primary.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            request.assert_called_once()
        assert sheet.current_password.text == ''
        identity.outcome, identity.unknown = 'unknown', True
        identity.error = (
            'The address operation is unconfirmed. Check the same profile address.'
        )
        Clock.schedule_once(readback, 0.3)

    def readback(_elapsed: float) -> None:
        """Keeps fresh generation disabled while an exact read-only check remains accessible.

        Args:
            _elapsed: Native unknown-state interval.
        Returns:
            None
        """
        assert sheet._serial is None and not sheet.recheck.disabled
        assert not sheet.current_password.readonly
        assert all(
            item.disabled
            for item in sheet.actions.children
            if isinstance(item, Action) and item is not sheet.cancel
        )
        sheet.current_password.text = 'synthetic-recheck-password'
        with patch.object(identity, 'offline_address', return_value=True) as request:
            sheet.recheck.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            request.assert_called_once_with(
                'Travel', 'Personal', 'synthetic-recheck-password', generate=False
            )
        assert sheet.current_password.text == ''
        identity.outcome, identity.unknown = 'saved', False
        identity.address_result = FrontendProfileOperationResult(
            True, 'address_generated', 'Travel', onion='a' * 56 + '.onion'
        )
        Clock.schedule_once(verify, 0.3)

    def verify(_elapsed: float) -> None:
        """Checks truthful result and reachable actions at native minimum geometry.

        Args:
            _elapsed: Native result layout interval.
        Returns:
            None
        """
        assert sheet.current_password.readonly and sheet.recheck.disabled
        assert sheet.feedback.text == 'Contact address: ' + 'a' * 56 + '.onion'
        assert sheet.cancel.y >= sheet.y and sheet.cancel.height >= 48
        assert app.controller.client is None
        complete()

    Clock.schedule_once(enter, 0.3)
