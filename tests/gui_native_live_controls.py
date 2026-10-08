"""Native LIVE chat-control identity probes with synthetic input and no transport IO."""

from dataclasses import replace
from unittest.mock import Mock, patch

from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import (
    Delivery,
    ConnectionConnectingEvent,
    LiveControlCompletedEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime.live import LiveActions
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.actions import live_context_actions
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.widgets import Action


def exercise_live_controls(app: MetorApp) -> None:
    """Checks held End targets, chat invitation Cancel, and preserved native composers.

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
    feedback = replace(state.feedback)
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
            assert peer.end.accessible_name == 'Cancel Live'
            assert peer.end.parent is not None
            assert peer.connect.parent is None
            review = controller.voice.reviews.get(peer.route.peer or '')
            if review is not None and review.binding.delivery is Delivery.LIVE:
                assert peer.composer.parent is peer
                assert peer.composer.commit.disabled
                assert peer.composer.entry is text_entry
                assert not controller.voice.review_actions.live_ready(review)
            else:
                assert peer.composer.parent is None
            end.reset_mock()
            peer.end.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            end.assert_called_once_with(peer.route.peer, None, 'ab' * 16)
            peer.end.focus = False
            with (
                patch.object(controller, 'live', LiveActions(controller)),
                patch.object(controller, 'submit', return_value=True) as submit,
                patch.object(controller, 'refresh_state'),
            ):
                state.snapshot = replace(snapshot, live_contexts=[])
                assert controller.live.start(peer.route.peer or '')
                start = controller.live.pending
                assert start is not None
                controller.live.install(
                    Update(
                        state.generation,
                        start.operation,
                        ConnectionConnectingEvent('', peer.route.peer),
                    )
                )
                state.snapshot = snapshot
                controller.live.poll()
                peer.update()
                peer.end.focus = True
                Window.dispatch('on_key_down', 13, 40, '\r', [])
                Window.dispatch('on_key_up', 13, 40)
                assert peer.end.disabled
                assert peer.end.accessible_name == 'Cancelling Live…'
                assert peer.subtitle.text == 'Cancelling Live…'
                assert peer.end.label.text == 'Cancelling Live…'
                mutation = controller.live.pending
                assert mutation is not None
                state.snapshot = replace(snapshot, live_contexts=[])
                controller.live.poll()
                peer.update()
                assert peer.end.parent is not None and peer.end.disabled
                assert peer.end.accessible_name == 'Cancelling Live…'
                assert peer.subtitle.text == 'Cancelling Live…'
                assert controller.live.failure(peer.route.peer or '') == ''
                assert peer.connect.parent is None
                controller.live.install(
                    Update(
                        state.generation,
                        mutation.operation,
                        LiveControlCompletedEvent(peer.route.peer or ''),
                    )
                )
                peer.update()
                assert peer.end.disabled
                assert peer.end.accessible_name == 'Cancelling Live…'
                Window.dispatch('on_key_down', 13, 40, '\r', [])
                Window.dispatch('on_key_up', 13, 40)
                assert submit.call_count == 2
                peer.end.focus = False
                state.snapshot = replace(
                    snapshot,
                    live_contexts=[
                        replace(
                            entry,
                            session_state='reconnect_scheduled',
                            recovery_eligible=False,
                            outbound_attempt_id=None,
                            context_generation=None,
                        )
                    ],
                )
                controller.live.poll()
                peer.update()
                assert peer.connect.parent is not None and not peer.connect.disabled
                assert peer.connect.accessible_name == 'Reconnect Live'
                assert controller.live.idle(peer.route.peer or '')
                assert controller.live.retry_ready(peer.route.peer or '')
                state.snapshot = snapshot
            for session, pending in (
                ('connected', 0),
                ('disconnected', 0),
                ('disconnected', 2),
            ):
                snapshot.live_contexts = [
                    replace(
                        entry,
                        session_state=session,
                        recovery_eligible=False,
                        context_generation=7,
                        outbound_attempt_id=None,
                        pending_outbound_count=pending,
                    )
                ]
                body = BoxLayout(orientation='vertical')
                live_context_actions(
                    controller,
                    peer.route.peer or '',
                    body,
                    lambda: None,
                    lambda: None,
                    primary_controls=False,
                )
                actions = {
                    widget.label.text: widget
                    for widget in body.children
                    if isinstance(widget, Action)
                }
                assert not actions.keys() & {
                    'End Live',
                    'Cancel Live',
                    'Reconnect',
                    'Reconnect Live',
                    'Close Live',
                }
                if session == 'connected':
                    assert 'Change route' in actions
                    assert 'Remove Live conversation' not in actions
                else:
                    assert 'Remove Live conversation' in actions
                    assert actions['Remove Live conversation'].disabled == bool(pending)
                    assert ('Send pending as Drop' in actions) == bool(pending)
            snapshot.live_contexts = []
            body = BoxLayout(orientation='vertical')
            live_context_actions(
                controller,
                'no-retained-context',
                body,
                lambda: None,
                lambda: None,
                primary_controls=False,
            )
            assert not body.children
        finally:
            state.capabilities = capabilities
            state.feedback = feedback
            state.snapshot = snapshot
            snapshot.live_contexts = original
            peer.update()
