"""Native packaged-font, pointer-tooltip and privacy-revocation checks without Core IO."""

# ruff: noqa: E402

import argparse
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.boxlayout import BoxLayout
from gui_native_notifications import exercise_notification_actions
from gui_native_projections import exercise_projection_reuse

from metor.client import FrontendHost, FrontendLaunchContext
from metor.core.api import (
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet


def exercise_feedback_layout(
    app: MetorApp, output: Path, complete: Callable[[], None]
) -> None:
    """Checks long feedback against actual touch-keyboard and title geometry.

    Args:
        app: Running isolated native presentation fixture, without a Core client.
        output: Existing capture path whose directory also receives these frames.
        complete: Continuation after synchronous private-reference revocation.
    """
    controller, state = app.controller, app.controller.state
    state.covered = False
    state.snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        contacts=[ContactEntry('Feedback', 'feedback-peer')],
    )
    state.navigate(Route('V08', 'feedback-peer', Delivery.DROP))
    state.status = (
        'This action could not be completed. Review the connection and try again. '
        'Your current message remains available in the conversation input.'
    )
    app.refresh()

    def settled(callback: Callable[[], None], frames: int = 8) -> None:
        """Waits for nested toolkit layout before inspecting final native bounds."""
        if frames:
            Clock.schedule_once(lambda _elapsed: settled(callback, frames - 1), 0)
        else:
            callback()

    def open_keyboard() -> None:
        """Opens the actual local keyboard for the visible editable composer."""
        assert app.shell is not None and app.shell._peer_panel is not None
        assert app.input_dock is not None
        peer = app.shell._peer_panel
        app.input_dock.show(peer.composer.entry)
        settled(inspect_keyboard)

    def inspect_keyboard() -> None:
        """Keeps long text scrollable and the dismiss target within a small viewport."""
        assert app.shell is not None and app.feedback_overlay is not None
        assert app.input_dock is not None and app.input_dock.keyboard is not None
        overlay, anchor = app.feedback_overlay, app.shell.feedback_anchor()
        assert anchor is not None and overlay.card.parent is not None
        assert anchor.height >= dp(Geometry.TARGET)
        assert overlay.card.x >= anchor.x and overlay.card.right <= anchor.right
        assert overlay.card.y >= anchor.y and overlay.card.top <= anchor.top
        assert overlay.dismiss.height == dp(Geometry.TARGET)
        assert overlay.dismiss.y - overlay.card.y >= dp(12) - dp(1)
        assert overlay.card.top - overlay.dismiss.top >= dp(12) - dp(1)
        assert overlay.card.right - overlay.dismiss.right >= dp(12) - dp(1)
        assert overlay.message.height > overlay.message_viewport.height
        assert overlay.card.y >= app.input_dock.keyboard.top
        assert app.root is not None
        app.root.export_to_png(
            str(output.with_stem(output.stem + '-keyboard-feedback'))
        )
        assert state.snapshot is not None
        state.snapshot = replace(
            state.snapshot,
            contacts=[
                ContactEntry(
                    'A deliberately long contact name spanning several visible lines',
                    'feedback-peer',
                )
            ],
        )
        app.refresh()
        settled(inspect_small_viewport)

    def inspect_small_viewport() -> None:
        """Suppresses only transient feedback when no complete action target fits."""
        assert app.shell is not None and app.feedback_overlay is not None
        assert app.input_dock is not None
        overlay, anchor = app.feedback_overlay, app.shell.feedback_anchor()
        assert anchor is not None and anchor.height < dp(Geometry.TARGET + 24)
        assert overlay.card.parent is None
        assert ActionSheet.current is None
        assert state.feedback.visible()
        app.input_dock.hide()
        settled(inspect_restored)

    def inspect_restored() -> None:
        """Restores unexpired feedback without stealing focus, then clears its owner."""
        assert app.shell is not None and app.feedback_overlay is not None
        assert app.shell._peer_panel is not None
        overlay, anchor = app.feedback_overlay, app.shell.feedback_anchor()
        assert anchor is not None and overlay.card.parent is not None
        assert overlay.card.y >= anchor.y and overlay.card.top <= anchor.top
        assert app.shell._peer_panel.composer.entry.focus
        assert not overlay.dismiss.focus
        overlay.dismiss.focus = True
        state.covered = True
        assert overlay._anchor is None
        assert overlay.message.text == '' and overlay.card.parent is None
        assert not overlay.dismiss.focus
        assert controller.client is None
        print('NATIVE_GUI_BOUNDED_KEYBOARD_FEEDBACK_OK')
        complete()

    settled(open_keyboard)


def exercise_sheet_refresh(app: MetorApp, complete: Callable[[], None]) -> None:
    """Checks async modal content, dismissal ownership and revoked confirmations.

    Args:
        app: Native widget fixture; no Core or physical audio is involved.
        complete: Continuation after queued layouts and held inputs are checked.
    """
    controller = app.controller
    controller.state.covered = False
    original_size = Window.size
    revision = [0]
    dismissed = Mock(return_value=None)
    committed = Mock()
    sheet = cast(ActionSheet, None)
    target = cast(Action, None)
    target_bounds: tuple[float, ...] = ()
    private_label = cast(Label, None)

    def settled(callback: Callable[[], None], frames: int = 8) -> None:
        """Waits for native layout callbacks without substituting rendered geometry."""
        Clock.schedule_once(
            lambda _elapsed: (
                callback() if frames == 0 else settled(callback, frames - 1)
            ),
            0,
        )

    def build(body: BoxLayout) -> None:
        """Models asynchronously expanded device results in the actual scrolling body."""
        nonlocal private_label
        private_label = Label(
            'Private device description. ' * (120 if revision[0] % 2 else 1)
        )
        body.add_widget(private_label)

    def bounds(action: Action) -> tuple[float, ...]:
        """Reads the native target rectangle, including modal layout transforms."""
        return (*action.to_window(action.x, action.y), *action.size)

    def open_close() -> None:
        """Opens the wide stable frame before a device result becomes available."""
        nonlocal sheet
        sheet = ActionSheet(
            controller,
            build,
            title='Audio settings',
            stable_frame=True,
            snapshot_updates=False,
            revision=lambda: revision[0],
            wrap_title=True,
        )
        sheet.bind(on_dismiss=dismissed)
        sheet.show()
        settled(arm_close)

    def arm_close() -> None:
        """Retains the actual Close key press while publication refreshes the body."""
        nonlocal target, target_bounds
        target = sheet.close_action
        target_bounds = bounds(target)
        target.focus = True
        target.keyboard_on_key_down(Window, (13, 'enter'), '', [])
        previous = private_label
        revision[0] += 1
        ActionSheet.reconcile()
        assert previous.text == ''
        settled(release_close)

    def release_close() -> None:
        """Releases the same reachable target once after expanded content settles."""
        assert sheet.close_action is target and bounds(target) == target_bounds
        assert target.focus and target._keyboard_armed
        assert sheet.scroll.do_scroll_y
        target.keyboard_on_key_up(Window, (13, 'enter'))
        assert ActionSheet.current is None and dismissed.call_count == 1
        assert target.disabled and not target.focus
        assert private_label.text == '' and sheet.title_label.text == ''
        Window.size = (360, 640)
        settled(open_back)

    def open_back() -> None:
        """Exercises the compact Back target with the same native frame policy."""
        nonlocal sheet
        previous = sheet
        sheet = ActionSheet(
            controller,
            build,
            title='Choose headphone output',
            stable_frame=True,
            revision=lambda: revision[0],
            snapshot_updates=False,
            wrap_title=True,
        )
        sheet.show()
        previous.show()
        previous._build()
        assert ActionSheet.current is sheet and previous.title_label.text == ''
        settled(arm_back)

    def arm_back() -> None:
        """Holds safe dismissal while content shrinks after another device revision."""
        nonlocal target, target_bounds
        target = sheet.cancel
        target_bounds = bounds(target)
        target.focus = True
        target.keyboard_on_key_down(Window, (13, 'enter'), '', [])
        revision[0] += 1
        ActionSheet.reconcile()
        settled(release_back)

    def release_back() -> None:
        """Confirms Back remains armed and stationary across compact content refresh."""
        assert sheet.cancel is target and bounds(target) == target_bounds
        assert target.focus and target._keyboard_armed
        target.keyboard_on_key_up(Window, (13, 'enter'))
        assert ActionSheet.current is None
        open_confirmation()

    def open_confirmation() -> None:
        """Creates a captured destructive action and a measured keyboard inset."""
        nonlocal sheet
        sheet = ActionSheet(
            controller,
            build,
            title='Delete private fixture',
            primary=('Delete', committed),
            revision=lambda: revision[0],
            stable_frame=True,
            wrap_title=True,
        )
        sheet.show()
        sheet.set_keyboard_top(200)
        settled(arm_primary)

    def arm_primary() -> None:
        """A changed eligibility revision cancels an already held destructive input."""
        nonlocal target
        assert sheet.primary_action is not None
        target = sheet.primary_action
        assert sheet.y >= sheet._bottom()
        assert sheet.top <= Window.height - dp(Geometry.EDGE)
        target.focus = True
        target.keyboard_on_key_down(Window, (13, 'enter'), '', [])
        revision[0] += 1
        ActionSheet.reconcile()
        target.keyboard_on_key_up(Window, (13, 'enter'))
        assert committed.call_count == 0 and not target._keyboard_armed
        assert sheet.cancel.focus and ActionSheet.current is sheet
        settled(revoke_confirmation)

    def revoke_confirmation() -> None:
        """An explicit fresh confirmation works; cover then revokes all retained input."""
        target.focus = True
        target.keyboard_on_key_down(Window, (13, 'enter'), '', [])
        target.keyboard_on_key_up(Window, (13, 'enter'))
        assert committed.call_count == 1
        target.keyboard_on_key_down(Window, (13, 'enter'), '', [])
        controller.state.covered = True
        ActionSheet.reconcile()
        target.keyboard_on_key_up(Window, (13, 'enter'))
        assert committed.call_count == 1 and ActionSheet.current is None
        assert target.disabled and not target.focus
        assert private_label.text == '' and sheet.title_label.text == ''
        sheet._resize()
        assert sheet.title_label.text == ''
        Window.size = original_size
        print('NATIVE_GUI_STABLE_SHEET_REFRESH_PRIVACY_OK')
        complete()

    Window.size = (1180, 760)
    settled(open_close)


def main() -> None:
    """Checks real native text textures and cancels a pending/visible hint on cover.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    Metrics.fontscale = 1.5
    app = MetorApp(
        FrontendLaunchContext('Simulator', cast(FrontendHost, object())),
        DeviceConfiguration(mode='simulator', width_px=360, height_px=640),
    )
    controller = app.controller
    controller.open_profile()
    alias = 'שלום · العربية · 漢字'
    controller.state.snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        contacts=[ContactEntry(alias, 'unicode-peer')],
        conversations=[DropConversationSummaryEntry(alias, 'unicode-peer', 1)],
    )
    controller.state.covered = False
    controller.state.route = Route('V06')

    def inspect(_elapsed: float) -> None:
        """Validates real widgets before capturing the visible pointer hint.

        Args:
            _elapsed: Native layout settlement delay.
        Returns:
            None
        """
        assert app.shell is not None and app.viewport is not None
        labels = [widget for widget in app.shell.walk() if isinstance(widget, Label)]
        name = next((widget for widget in labels if widget.text == alias), None)
        assert name is not None, (
            controller.state.route,
            controller.state.covered,
            [widget.text for widget in labels],
            app.shell.children,
            app.shell._foreground_key,
        )
        assert Path(name.font_name).name == 'DejaVuSans-Bold.ttf'
        assert name.texture is not None and name.texture.width > 0
        field = TextField(text=alias)
        assert field.text == alias
        assert Path(field.font_name).name == 'DejaVuSans.ttf'
        secret = SecretInput(text=alias)
        assert secret.text == alias and secret.password
        assert Path(secret.font_name).name == 'InterTight-400.ttf'
        icon = next(
            widget
            for widget in app.shell.walk()
            if isinstance(widget, IconAction)
            and widget.accessible_name.startswith('Notifications')
        )
        Window.mouse_pos = icon.to_window(*icon.center)
        icon._pointer(Window, Window.mouse_pos)
        assert icon._hovered
        icon.tooltip.cancel()
        icon.tooltip._show(0)
        assert icon.tooltip.visible and icon.tooltip.label is not None
        assert icon.tooltip.label.text == icon.accessible_name
        assert not icon.focus and controller.state.route.view == 'V06'

        def capture_and_cover(_delta: float) -> None:
            """Captures after native text layout and then verifies synchronous revocation.

            Args:
                _delta: One native frame delay.
            Returns:
                None
            """
            assert app.root is not None and app.shell is not None
            Window.mouse_pos = icon.to_window(*icon.center)
            icon._pointer(Window, Window.mouse_pos)
            icon.tooltip.cancel()
            icon.tooltip._show(0)
            assert icon.tooltip.visible
            args.output.parent.mkdir(parents=True, exist_ok=True)
            app.root.export_to_png(str(args.output))
            controller.state.covered = True
            controller.state.snapshot = None
            controller.state.route = Route('V05')
            app.shell.render()
            assert not icon.tooltip.visible and icon.tooltip.label is None
            assert all(
                getattr(widget, 'text', '') != alias for widget in app.shell.walk()
            )
            assert controller.client is None
            print('NATIVE_GUI_FALLBACK_TOOLTIP_PRIVACY_OK')
            exercise_feedback_layout(
                app,
                args.output,
                lambda: exercise_projection_reuse(
                    app,
                    lambda: exercise_notification_actions(
                        app,
                        args.output,
                        lambda: exercise_sheet_refresh(app, app.stop),
                    ),
                ),
            )

        Clock.schedule_once(capture_and_cover, 0)

    Clock.schedule_once(lambda _elapsed: Clock.schedule_once(inspect, 0), 1.0)
    with patch('metor.ui.gui.app.create_desktop_lifecycle_source', return_value=None):
        app.run()


if __name__ == '__main__':
    main()
