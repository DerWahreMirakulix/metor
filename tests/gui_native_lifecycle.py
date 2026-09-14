"""Native call-control identity probes with synthetic input and no transport or audio IO."""

from dataclasses import replace
from unittest.mock import Mock, patch

from kivy.core.window import Window

from metor.core.api import Delivery
from metor.ui.gui.app import MetorApp
from metor.ui.gui.views.peer import PeerView


def exercise_live_controls(app: MetorApp) -> None:
    """Checks held End targets, calling Cancel, and composer preservation in native widgets.

    Args:
        app: Running isolated native fixture at either supported composition width.
    Returns:
        None
    """
    assert app.shell is not None
    peer = next(
        (widget for widget in app.shell.walk() if isinstance(widget, PeerView)), None
    )
    if peer is None or peer.route.delivery is not Delivery.LIVE:
        return
    controller, state = app.controller, app.controller.state
    snapshot = state.snapshot
    assert snapshot is not None
    original = snapshot.live_contexts
    capabilities = state.capabilities
    entry = next(row for row in original if row.onion == peer.route.peer)
    text_entry = peer.composer.entry
    with (
        patch.object(controller, 'client', Mock()),
        patch.object(controller.live, 'end') as end,
    ):
        try:
            state.capabilities = capabilities | {'qualified_live_control'}
            snapshot.live_contexts = [replace(entry, context_generation=1)]
            peer.update()
            first = peer.end
            assert not first.disabled and first.parent is not None
            first.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            snapshot.live_contexts = [replace(entry, context_generation=2)]
            peer.update()
            assert peer.end is not first
            Window.dispatch('on_key_up', 13, 40)
            assert all(
                call.args == (peer.route.peer, 1, None) for call in end.call_args_list
            )
            first.focus = False
            end.reset_mock()
            peer.end.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            end.assert_called_once_with(peer.route.peer, 2, None)
            peer.end.focus = False
            assert peer.composer.entry is text_entry
            snapshot.live_contexts = [
                replace(
                    entry,
                    session_state='connecting',
                    recovery_eligible=False,
                    context_generation=None,
                    outbound_attempt_id='ab' * 16,
                )
            ]
            peer.update()
            assert peer.end.label.text == 'Cancel'
            assert peer.end.parent is not None
            assert peer.connect.parent is None and peer.composer.parent is None
            end.reset_mock()
            peer.end.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            end.assert_called_once_with(peer.route.peer, None, 'ab' * 16)
            peer.end.focus = False
        finally:
            state.capabilities = capabilities
            snapshot.live_contexts = original
            peer.update()
