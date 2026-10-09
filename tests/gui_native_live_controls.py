"""Native LIVE chat-control identity probes with synthetic input and no transport IO."""

from dataclasses import replace
from unittest.mock import Mock, patch

from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import (
    Delivery,
    ConnectionConnectingEvent,
    LiveControlCompletedEvent,
    MessageDirectionCode,
    MessageStatusCode,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime.live import LiveActions
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.actions import live_context_actions
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet


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
                    assert not actions['Remove Live conversation'].disabled
                    assert ('Send pending as Drop' in actions) == bool(pending)
                    if pending:
                        with patch.object(
                            controller.live, 'remove_context', return_value=True
                        ) as remove:
                            state.capabilities |= {'live_pending_cancellation'}
                            for choice in (None, True, False):
                                peer._menu()
                                menu = ActionSheet.current
                                assert menu is not None
                                removal = next(
                                    widget
                                    for widget in menu.column.walk(restrict=True)
                                    if isinstance(widget, Action)
                                    and widget.accessible_name
                                    == 'Remove Live conversation'
                                )
                                removal.dispatch('on_release')
                                sheet = ActionSheet.current
                                assert sheet is not None
                                assert sheet.heading == 'Remove Live conversation'
                                choices = {
                                    widget.accessible_name: widget
                                    for widget in sheet.column.walk(restrict=True)
                                    if isinstance(widget, Action)
                                }
                                assert set(choices) == {
                                    'Send as Drops',
                                    'Discard pending',
                                }
                                assert sheet.cancel.accessible_name == 'Cancel'
                                assert sheet.wrap_title
                                assert all(
                                    not action.disabled for action in choices.values()
                                )
                                if choice is None:
                                    sheet.cancel.dispatch('on_release')
                                    remove.assert_not_called()
                                else:
                                    choices[
                                        'Send as Drops' if choice else 'Discard pending'
                                    ].dispatch('on_release')
                                    remove.assert_called_once_with(
                                        peer.route.peer, send_pending_as_drops=choice
                                    )
                                    remove.reset_mock()
                                assert ActionSheet.current is None

            review = controller.voice.reviews.pop(peer.route.peer or '', None)
            try:
                snapshot.live_contexts = [
                    replace(
                        entry,
                        session_state='disconnected',
                        recovery_eligible=False,
                        context_generation=7,
                        outbound_attempt_id=None,
                        pending_outbound_count=2,
                    )
                ]
                peer.update()
                assert peer.composer.parent is peer
                assert peer.composer._mode == 'pending'
                assert peer.composer.entry is text_entry
                assert peer.composer.bar.parent is None
                assert not peer.composer.entry.focus
                footer = peer.composer.pending_footer
                assert footer.parent is peer.composer
                assert footer.summary.text == 'Live ended · 2 pending messages'
                assert footer.send.accessible_name == 'Send all pending as Drops'
                assert not footer.send.disabled
                snapshot.live_contexts = [
                    replace(
                        snapshot.live_contexts[0],
                        session_state='reconnecting',
                        recovery_eligible=True,
                    )
                ]
                peer.update()
                assert peer.composer.parent is peer
                assert peer.composer._mode == 'composer'
                assert peer.composer.bar.parent is peer.composer
                assert footer.parent is None
                assert peer.composer.entry is text_entry
                snapshot.live_contexts = [
                    replace(
                        snapshot.live_contexts[0],
                        session_state='disconnected',
                        recovery_eligible=False,
                        pending_outbound_count=0,
                    )
                ]
                peer.update()
                assert peer.composer.parent is None
                assert peer.composer.entry is text_entry
            finally:
                if review is not None:
                    controller.voice.reviews[peer.route.peer or ''] = review

            context_items = (
                (
                    MessageDirectionCode.IN,
                    'read-in',
                    MessageStatusCode.READ,
                    True,
                    False,
                ),
                (
                    MessageDirectionCode.OUT,
                    'pending-out',
                    MessageStatusCode.PENDING,
                    True,
                    True,
                ),
                (
                    MessageDirectionCode.OUT,
                    'delivered-out',
                    MessageStatusCode.DELIVERED,
                    True,
                    True,
                ),
                (
                    MessageDirectionCode.OUT,
                    'unfinalized-out',
                    MessageStatusCode.PENDING,
                    False,
                    False,
                ),
            )
            try:
                for direction, identity, status, finalized, _eligible in context_items:
                    assert controller.transcript.admit(
                        TranscriptItem(
                            peer.route.peer or '',
                            Delivery.LIVE,
                            direction,
                            'menu-' + identity,
                            text='Message context fixture',
                            status=status,
                            finalized=finalized,
                        )
                    )
                peer.timeline.update(active=False)
                for direction, identity, _status, _finalized, eligible in context_items:
                    key = direction, 'menu-' + identity
                    assert key in peer.timeline._widgets
                    assert (key in peer.timeline._context_keys) is eligible
            finally:
                for (
                    direction,
                    identity,
                    _status,
                    _finalized,
                    _eligible,
                ) in context_items:
                    controller.transcript.discard(
                        peer.route.peer, Delivery.LIVE, 'menu-' + identity, direction
                    )
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
            assert len(body.children) == 1 and isinstance(body.children[0], Label)
            assert (
                body.children[0].text == 'Live controls are in the conversation header.'
            )
        finally:
            state.capabilities = capabilities
            state.feedback = feedback
            state.snapshot = snapshot
            snapshot.live_contexts = original
            peer.update()
