"""Native bounded peer-view reuse and synchronous privacy revocation checks."""

from collections.abc import Callable
from dataclasses import replace
from unittest.mock import Mock, patch

from kivy.clock import Clock
from kivy.core.window import Window

from metor.core.api import (
    ContactEntry,
    Delivery,
    MessageDirectionCode,
    MessageEntry,
    MessageStatusCode,
    MessagesDataEvent,
    RuntimeSnapshotEvent,
    TextContent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.message import MessageBubble


def exercise_projection_reuse(app: MetorApp, complete: Callable[[], None]) -> None:
    """Uses real native widget ownership with explicit synthetic model publication.

    Args:
        app: Running renderer fixture without a Core client or physical media.
        complete: Continuation after queued native layout callbacks are checked.
    """
    controller, state = app.controller, app.controller.state
    assert app.shell is not None
    shell = app.shell
    state.covered = False
    state.snapshot = RuntimeSnapshotEvent(
        'Simulator',
        '',
        epoch='projection-fixture',
        contacts=[ContactEntry('Projection contact', 'projection-peer')],
    )
    drop_route = Route('V08', 'projection-peer', Delivery.DROP)
    live_route = Route('V09', 'projection-peer', Delivery.LIVE)
    state.navigate(drop_route)
    controller.messages = MessagesDataEvent(
        [
            MessageEntry(
                MessageDirectionCode.IN,
                MessageStatusCode.READ,
                Delivery.DROP,
                TextContent('Private projection fixture message'),
                timestamp='',
                msg_id='projection-message',
            )
        ],
        'Projection contact',
        'projection-peer',
    )
    state.set_draft('projection-peer', Delivery.DROP, 'Private projection draft')
    shell.render()
    drop = shell._peer_panel
    assert drop is not None
    row = drop.timeline._widgets[(MessageDirectionCode.IN, 'projection-message')]
    assert isinstance(row, MessageBubble)
    entry = drop.composer.entry
    entry.focus = True
    drop.more._keyboard_armed = True
    state.navigate(live_route)
    shell.render()
    live = shell._peer_panel
    assert live is not None and live is not drop
    assert drop.parent is None and drop.disabled
    assert not entry.focus and not drop.more._keyboard_armed
    assert all(
        not widget.focus
        for widget in drop.walk(restrict=True)
        if isinstance(widget, Action)
    )
    assert len(shell._peer_projections._views) == 2
    state.navigate(drop_route)
    shell.render()
    assert shell._peer_panel is drop and not drop.disabled
    assert drop.composer.entry is entry
    assert (
        drop.timeline._widgets[
            row_key := (MessageDirectionCode.IN, 'projection-message')
        ]
        is row
    )
    assert entry.text == state.drafts[('projection-peer', Delivery.DROP)]

    state.navigate(live_route)
    shell.render()
    assert controller.messages is not None
    controller.messages = replace(controller.messages)
    shell.render()
    assert shell._peer_projections._views[Delivery.DROP] is drop
    controller.messages = replace(controller.messages, messages=[])
    shell.render()
    assert drop._revoked and entry.text == ''
    assert row._body.text == '' and not drop.timeline._widgets
    assert Delivery.DROP not in shell._peer_projections._views
    state.navigate(drop_route)
    shell.render()
    replacement = shell._peer_panel
    assert replacement is not None and replacement is not drop
    assert row_key not in replacement.timeline._widgets
    assert (
        state.drafts[('projection-peer', Delivery.DROP)] == 'Private projection draft'
    )

    # The composer owns both stages even when its editable bar is detached.
    replacement.composer.remove_widget(replacement.composer.bar)
    replacement.composer.add_widget(replacement.composer.review)
    detached_entry = replacement.composer.entry
    detached_entry.focus = True
    replacement.composer.send._keyboard_armed = True
    with patch.object(controller, 'send_text', Mock()) as send:
        state.covered = True
        assert not shell._peer_projections._views
        shell.render()
        assert shell._peer_projections._drop_page is None
        assert detached_entry.text == '' and not detached_entry.focus
        replacement.composer.send.keyboard_on_key_up(Window, (13, 'enter'))
        replacement.width += 1
        replacement.reflow(wide=False)
        replacement.update()
        replacement.composer.update()
        replacement.timeline.update(active=False)
        send.assert_not_called()
    assert live._revoked and replacement._revoked
    assert (
        state.drafts[('projection-peer', Delivery.DROP)] == 'Private projection draft'
    )

    def after_pending_layout(_elapsed: float) -> None:
        """Retained external references cannot repopulate cleared private widgets."""
        assert detached_entry.text == '' and entry.text == ''
        assert row._body.text == '' and row._metadata.text == ''
        assert live.name.text == '' and replacement.name.text == ''
        assert not replacement.timeline._layout_trigger.is_triggered
        assert controller.client is None
        print('NATIVE_GUI_BOUNDED_PEER_PROJECTIONS_PRIVACY_OK')
        complete()

    Clock.schedule_once(after_pending_layout, 0)
