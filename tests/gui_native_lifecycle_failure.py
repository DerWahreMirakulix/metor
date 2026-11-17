"""Native terminal privacy cover after a simulated desktop monitor failure."""

from collections.abc import Callable
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

from gui_native_render import capture_viewport
from gui_native_purge import configure_purge
from metor.core.api import ContactEntry, Delivery, RuntimeSnapshotEvent
from metor.ui.gui.app import MetorApp
from metor.ui.gui.platform.lifecycle import DesktopLifecycleEvent
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField


def exercise_lifecycle_failure(
    app: MetorApp,
    output: Path,
    complete: Callable[[], None],
    *,
    purging: bool = False,
) -> None:
    """Keep failed monitoring visible after resume and close through the real key route.

    The source transition and late SDK DTO are synthetic; widgets, native text
    layout, lifecycle handoff, privacy revocation and exit dispatch are real.
    """
    controller = app.controller
    private_name = 'Private contact before monitor failure'
    snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        contacts=[ContactEntry(private_name, 'private-peer')],
    )
    controller.state.snapshot = snapshot
    controller.state.covered = False
    controller.state.route = Route('V08', 'private-peer', Delivery.DROP)
    generation = controller.state.generation
    app.refresh()

    def settled(callback: Callable[[], None], frames: int = 8) -> None:
        """Allow real nested layout and queued lifecycle delivery to finish."""
        Clock.schedule_once(
            lambda _elapsed: (
                callback() if frames == 0 else settled(callback, frames - 1)
            ),
            0,
        )

    def lose_source() -> None:
        """Fail a visible private conversation through the production handoff."""
        assert app.shell is not None and app.shell._peer_panel is not None
        assert any(
            isinstance(widget, Label) and widget.text == private_name
            for widget in app.shell.walk()
        )
        entry = app.shell._peer_panel.composer.entry
        entry.text = 'Private unsent text'
        entry.focus = True
        if purging:
            configure_purge(controller, 'purge_unknown')
        app._queue_lifecycle(DesktopLifecycleEvent.SOURCE_LOST)
        settled(resume_and_deliver_late_update)

    def resume_and_deliver_late_update() -> None:
        """Try normal resume and an already queued snapshot after permanent loss."""
        assert controller.native_lifecycle_failed
        assert controller.state.covered and app.exit_status == 1
        assert not controller.open_profile()
        controller.mailbox.put(Update(generation, 'snapshot', snapshot))
        app._queue_lifecycle(DesktopLifecycleEvent.RESUME)
        app.refresh()
        settled(inspect_and_close)

    def inspect_and_close() -> None:
        """Require readable recovery instructions and one complete keyboard action."""
        assert app.shell is not None and app.viewport is not None
        assert controller.native_lifecycle_failed and controller.state.covered
        assert controller.state.snapshot is None and controller.client is None
        assert not any(
            isinstance(widget, (TextField, SecretInput)) for widget in app.shell.walk()
        )
        labels = [widget for widget in app.shell.walk() if isinstance(widget, Label)]
        assert all(private_name not in widget.text for widget in labels)
        assert all('Private unsent text' not in widget.text for widget in labels)
        assert any(widget.text == 'Restart Metor' for widget in labels)
        assert any(
            widget.text
            == 'Desktop security monitoring stopped. Close and restart Metor to continue safely.'
            for widget in labels
        )
        if purging:
            assert controller.purge.active
            assert any(widget.text == 'Destruction not confirmed' for widget in labels)
            assert any(
                widget.text
                == 'Keep the device powered. Profile access destruction could not be confirmed.'
                for widget in labels
            )
        actions = [widget for widget in app.shell.walk() if isinstance(widget, Action)]
        assert len(actions) == 1 and actions[0].accessible_name == 'Close Metor'
        action = actions[0]
        assert not action.disabled and action.height >= dp(48)
        left, bottom = app.viewport.to_window(*app.viewport.pos)
        for widget in [*labels, action]:
            x, y = widget.to_window(*widget.pos)
            assert left - 1 <= x and x + widget.width <= left + app.viewport.width + 1
            assert (
                bottom - 1 <= y
                and y + widget.height <= bottom + app.viewport.height + 1
            )
        assert app.input_dock is not None and app.input_dock.keyboard is None
        capture_viewport(app.viewport, output.with_stem(output.stem + '-source-lost'))
        action.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert controller.lifecycle.exit_ready
        print(
            'NATIVE_GUI_MONITOR_FAILURE_PURGE_COVER_AND_EXIT_OK'
            if purging
            else 'NATIVE_GUI_MONITOR_FAILURE_COVER_AND_EXIT_OK'
        )
        complete()

    settled(lose_source)
