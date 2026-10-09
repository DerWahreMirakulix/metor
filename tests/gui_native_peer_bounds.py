"""Native peer/header bounds with a Call, pending Live and local typing keyboard."""

# ruff: noqa: E402

import argparse
import os
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

# Size SDL's drawable before importing the first native Window.
geometry_parser = argparse.ArgumentParser(add_help=False)
geometry_parser.add_argument('--width', type=int, default=360)
geometry_parser.add_argument('--height', type=int, default=640)
initial_geometry, _remaining_arguments = geometry_parser.parse_known_args()
Config.set('graphics', 'width', str(initial_geometry.width))
Config.set('graphics', 'height', str(initial_geometry.height + 24))

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.widget import Widget

from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallInfo,
    CallState,
    CallStateEvent,
    ConnectionOrigin,
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    IncomingConnectionEvent,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.state import Route
from metor.ui.gui.views.peer import PeerView

from gui_native_render import capture_viewport

LAYOUT_FRAMES = 12
FIXTURE_DEADLINE_SECONDS = 30.0
GEOMETRY_TOLERANCE = 1.0
PEER = 'bounds-fixture-peer'
ALIAS = 'MiXeD Case Contact'
LONG_ALIAS = 'A contact name with several readable words'


def bounds(widget: Widget) -> tuple[float, float, float, float]:
    """Returns window bounds including the native scrolling viewport transform."""
    x, y = widget.to_window(widget.x, widget.y)
    return x, y, x + widget.width, y + widget.height


class PeerBoundsHarness:
    """Keeps the full application layout live while testing synthetic state only."""

    def __init__(self, output: Path, width: int, height: int) -> None:
        """Sets up the actual application strips and input dock without Core or audio."""
        Metrics.fontscale = 1.5
        Window.size = (width, height + 24)
        self.output, self.completed = output, False
        self.app = MetorApp(
            FrontendLaunchContext('Simulator', Mock()),
            DeviceConfiguration(
                mode='simulator', width_px=width, height_px=height, touch=True
            ),
        )
        controller = self.app.controller
        controller.open_profile()
        controller.poll = Mock(return_value=False)
        state = controller.state
        state.covered = False
        state.route = Route('V08', PEER, Delivery.DROP)
        state.snapshot = RuntimeSnapshotEvent(
            'Simulator',
            '',
            epoch='simulator',
            profile_instance_id='synthetic',
            contacts=[ContactEntry(ALIAS, PEER)],
            conversations=[DropConversationSummaryEntry(ALIAS, PEER)],
            pending=[
                PendingConnectionEntry(
                    'Orion',
                    'orion',
                    ConnectionOrigin.INCOMING,
                    PendingConnectionReasonCode.USER_ACCEPT,
                    action_handle='invite-handle',
                )
            ],
        )
        controller.live_invitations.observe(
            IncomingConnectionEvent('Orion', 'orion', action_handle='invite-handle')
        )
        controller.calls.observe(
            CallStateEvent(
                CallInfo(
                    'call',
                    PEER,
                    ALIAS,
                    CallState.ACTIVE,
                    started_at=time.time() - 83,
                    owned=True,
                )
            )
        )
        controller.calls.visible = False

    def settled(
        self, callback: Callable[[], None], frames: int = LAYOUT_FRAMES
    ) -> None:
        """Waits for actual font and nested application layout to settle."""
        if frames:
            Clock.schedule_once(lambda _elapsed: self.settled(callback, frames - 1), 0)
        else:
            callback()

    def peer(self) -> PeerView:
        """Returns the foreground pane retained by the application shell."""
        assert self.app.shell is not None and self.app.shell._peer_panel is not None
        return self.app.shell._peer_panel

    def verify(self) -> None:
        """Requires clipped identity content and the anchored composer inside their pane."""
        app, peer = self.app, self.peer()
        assert app.call_bar is not None and app.invitation_slot is not None
        assert app.shell is not None
        assert app.call_bar.height > 0 and app.invitation_slot.height > 0
        assert app.invitation_slot.y >= app.shell.top - GEOMETRY_TOLERANCE
        assert app.call_bar.y >= app.invitation_slot.top - GEOMETRY_TOLERANCE
        _left, bottom, _right, top = bounds(peer)
        for region in (peer.header_viewport, peer.timeline, peer.composer):
            _x, y, _end, edge = bounds(region)
            assert y >= bottom - GEOMETRY_TOLERANCE
            assert edge <= top + GEOMETRY_TOLERANCE
        _x, bar_bottom, _end, bar_top = bounds(peer.composer.bar)
        for action in (peer.composer.ptt, peer.composer.send):
            if action.parent is peer.composer.bar:
                _left, y, _right, edge = bounds(action)
                assert y >= bar_bottom - GEOMETRY_TOLERANCE
                assert edge <= bar_top + GEOMETRY_TOLERANCE
        assert peer.timeline.height >= dp(24)
        assert not peer.name.shorten
        assert peer.call.label.text == 'In call'
        assert peer.name.text == self.alias

    def capture(self, suffix: str) -> None:
        """Captures native presentation without replaying a subtree in another GL context."""
        assert self.app.viewport is not None
        capture_viewport(
            self.app.viewport, self.output.with_stem(self.output.stem + suffix)
        )

    def verify_identity_row(self) -> None:
        """Requires complete initial Back, Call and More targets without manual scrolling."""
        peer = self.peer()
        _x, bottom, _edge, top = bounds(peer.header_viewport)
        actions = (peer.call, peer.more) + tuple(
            widget
            for widget in peer.header.title_row.children
            if getattr(widget, 'accessible_name', '') == 'Back'
        )
        for action in actions:
            _left, y, _right, end = bounds(action)
            assert y >= bottom - GEOMETRY_TOLERANCE
            assert end <= top + GEOMETRY_TOLERANCE

    def initial(self) -> None:
        """Checks the ordinary alias keeps Call and More beside the name."""
        self.alias = ALIAS
        self.verify()
        self.verify_identity_row()
        peer = self.peer()
        assert not peer.header.expanded_title
        assert peer.name.parent is peer.call.parent is peer.more.parent
        self.capture('-normal')
        assert self.app.input_dock is not None
        self.app.input_dock.show(peer.composer.entry)
        self.settled(self.keyboard)

    def keyboard(self) -> None:
        """Checks the exact Callbar/pending/keyboard combination that previously overlapped."""
        self.verify()
        self.verify_identity_row()
        self.capture('-keyboard')
        peer = self.peer()
        assert peer.timeline.height >= dp(48) - GEOMETRY_TOLERANCE
        self.original_entry = peer.composer.entry
        self.original_call = peer.call
        state = self.app.controller.state
        assert state.snapshot is not None
        self.alias = LONG_ALIAS
        state.snapshot = replace(
            state.snapshot,
            contacts=[ContactEntry(LONG_ALIAS, PEER)],
            conversations=[DropConversationSummaryEntry(LONG_ALIAS, PEER)],
        )
        self.app.refresh()
        self.settled(self.long_alias)

    def long_alias(self) -> None:
        """Requires full-width long identity and continuity through constrained reflow."""
        self.verify()
        self.verify_identity_row()
        peer = self.peer()
        assert peer.composer.entry is self.original_entry
        assert peer.call is self.original_call
        if peer.width < dp(640):
            assert peer.header.expanded_title
            assert peer.name.parent is peer.header
            assert peer.header.height < dp(220)
        self.capture('-long-keyboard')
        peer.header_viewport.scroll_to(peer.call, animate=False)
        self.settled(self.call_controls_reachable)

    def call_controls_reachable(self) -> None:
        """Keeps the current Call and adjacent More controls fully reachable after reflow."""
        peer = self.peer()
        _x, bottom, _edge, top = bounds(peer.header_viewport)
        for action in (peer.call, peer.more):
            _left, y, _right, end = bounds(action)
            assert y >= bottom - GEOMETRY_TOLERANCE
            assert end <= top + GEOMETRY_TOLERANCE
        self.capture('-call-controls')
        peer.header_viewport.scroll_to(peer.connect, animate=False)
        self.settled(self.controls_reachable)

    def controls_reachable(self) -> None:
        """Requires explicit Start/Open Live to remain reachable inside the clipped header."""
        peer = self.peer()
        _x, bottom, _edge, top = bounds(peer.header_viewport)
        _left, y, _right, end = bounds(peer.connect)
        assert y >= bottom - GEOMETRY_TOLERANCE
        assert end <= top + GEOMETRY_TOLERANCE
        self.capture('-live-control')
        self.app.refresh()
        self.settled(self.refresh_preserves_scroll)

    def refresh_preserves_scroll(self) -> None:
        """Keeps deliberate header scrolling through an ordinary application refresh."""
        peer = self.peer()
        _x, bottom, _edge, top = bounds(peer.header_viewport)
        _left, y, _right, end = bounds(peer.connect)
        assert y >= bottom - GEOMETRY_TOLERANCE
        assert end <= top + GEOMETRY_TOLERANCE
        assert self.app.input_dock is not None
        self.app.input_dock.hide()
        self.settled(self.restored)

    def restored(self) -> None:
        """Restores fully visible headers after the keyboard departs without replacing inputs."""
        self.verify()
        peer = self.peer()
        assert not peer.header_viewport.do_scroll_y
        assert peer.composer.entry is self.original_entry
        self.capture('-long-restored')
        self.completed = True
        self.app.stop()

    def deadline(self, _elapsed: float) -> None:
        """Fails an incomplete native fixture within its explicit acceptance bound."""
        assert self.completed, 'Peer bounds fixture did not complete'

    def run(self) -> None:
        """Runs synthetic projection checks through the real native application event loop."""
        self.settled(self.initial)
        Clock.schedule_once(self.deadline, FIXTURE_DEADLINE_SECONDS)
        with patch(
            'metor.ui.gui.app.create_desktop_lifecycle_source', return_value=None
        ):
            self.app.run()
        assert self.completed


def main() -> None:
    """Runs compact or desktop bounds and writes explicitly software-only captures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width', type=int, default=360)
    parser.add_argument('--height', type=int, default=640)
    args = parser.parse_args()
    PeerBoundsHarness(args.output, args.width, args.height).run()
    print('NATIVE_PEER_BOUNDS_OK')


if __name__ == '__main__':
    main()
