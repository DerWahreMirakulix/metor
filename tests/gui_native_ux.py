"""First-draw and visible-feedback probes for the actual Core-backed GUI journey.

These observations never invoke an application action or install a request
result. Native input remains owned by the XTest driver in the main journey.
"""

from collections.abc import Callable
from contextlib import ExitStack
import json
import time
import threading
from typing import TYPE_CHECKING
from unittest.mock import patch

from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.uix.behaviors import FocusBehavior

from frontend_e2e_runtime import FIXTURE_WAIT_SECONDS
from gui_native_x11 import rectangle
from metor.core.api import Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.views.peer import PeerView

if TYPE_CHECKING:
    from gui_native_core import NativeCoreApp


GEOMETRY_TOLERANCE = 1.0


class NativeUxProbe:
    """Records the first actual draw after deliberate native communication actions."""

    def __init__(self, app: 'NativeCoreApp') -> None:
        """Retains the fixture observer and bounded timing evidence only."""
        self.app = app
        self.records: dict[str, object] = {}
        self._start: tuple[str, float] | None = None
        self._drop: float | None = None
        self._live_open: float | None = None
        self._cold_drop: float | None = None
        self._release_callbacks: list[tuple[Action, Callable[..., None]]] = []
        self.connect_entered = threading.Event()
        self._connect_release = threading.Event()
        self._connect_count = 0
        self._connect_patch: ExitStack | None = None
        self._drop_panel: PeerView | None = None
        self._live_panel: PeerView | None = None
        self._drop_editor: Widget | None = None
        self._drop_timeline: Widget | None = None
        self._first_drop: Widget | None = None
        self._draw_started = 0.0
        Window.bind(on_draw=self._drawing)

    def _drawing(self, *_args: object) -> None:
        """Samples native canvas drawing separately from widget reconciliation."""
        self._draw_started = time.monotonic()

    def hold_first_connect(self) -> None:
        """Holds real Core execution after authenticated IPC admission, before its reply."""
        network = self.app.runtime.daemon._network
        original = network.connect_to

        def held_connect(target: str) -> None:
            """Controls scheduling only, then invokes the unmodified production operation."""
            self._connect_count += 1
            self.connect_entered.set()
            assert self._connect_release.wait(FIXTURE_WAIT_SECONDS), (
                'Native first-frame barrier timed out'
            )
            original(target)

        self._connect_patch = ExitStack()
        self._connect_patch.enter_context(
            patch.object(network, 'connect_to', held_connect)
        )

    def release_connect(self) -> None:
        """Requires duplicate native activation to remain one admitted Core request."""
        assert self._connect_count == 1, ('Duplicate Core Connect', self._connect_count)
        self.records['core_connect_requests_during_duplicate_tap'] = self._connect_count
        self.app.checks['duplicate_native_start_admits_one_connect'] = True
        self._connect_release.set()
        if self._connect_patch is not None:
            self._connect_patch.close()
            self._connect_patch = None

    def arm_cold_drop(self, action: Action) -> None:
        """Observes the first opened archive before any eventual message readiness wait."""

        def released(*_args: object) -> None:
            """Starts an observation at the actual native contact selection."""
            action.unbind(on_release=released)
            self._cold_drop = time.monotonic()

        self._release_callbacks.append((action, released))
        action.bind(on_release=released)

    def arm_start(self, name: str, action: Action) -> None:
        """Starts timing at the native release that invokes the real Start action."""

        def released(*_args: object) -> None:
            """Observes native activation without changing request admission."""
            action.unbind(on_release=released)
            self._start = name, time.monotonic()

        self._release_callbacks.append((action, released))
        action.bind(on_release=released)

    def arm_drop(self, action: Action) -> None:
        """Checks the first DROP draw after selecting its master row or contact."""

        def released(*_args: object) -> None:
            """Observes explicit archive navigation without communication admission."""
            action.unbind(on_release=released)
            self._drop = time.monotonic()

        self._release_callbacks.append((action, released))
        action.bind(on_release=released)

    def arm_live_open(self, action: Action) -> None:
        """Times explicit Start Live opening its selected peer conversation."""

        def released(*_args: object) -> None:
            """Observes the deliberate Start Live activation boundary."""
            action.unbind(on_release=released)
            self._live_open = time.monotonic()

        self._release_callbacks.append((action, released))
        action.bind(on_release=released)

    def frame(self) -> None:
        """Checks the first rendered state, without the journey's polling delay."""
        app, peer = self.app, self.app.peer()
        if peer is None:
            return
        if self._start is not None:
            name, started = self._start
            self._start = None
            pending = app.controller.live.pending
            record = {
                'release_to_first_draw_ms': round(
                    (time.monotonic() - started) * 1000, 3
                ),
                'subtitle': peer.subtitle.text,
                'core_request_still_pending': bool(
                    pending and pending.kind == 'start' and pending.peer == app.target
                ),
                'start_disabled': peer.connect.disabled,
                'canvas_draw_ms': round(
                    (time.monotonic() - self._draw_started) * 1000, 3
                ),
                'title_rect': rectangle(peer.name),
                'title_attached': peer.name.get_root_window() is not None,
            }
            self.records[name] = record
            assert peer.subtitle.text in {
                'Starting Live…',
                'Connecting Live…',
                'Connecting chat…',
                'Checking connection…',
            }, ('First Start Live draw has no visible progress', record)
            assert peer.connect.disabled, ('Repeated start remains active', record)
            if name == 'live_start_1':
                assert record['core_request_still_pending'], (
                    'Progress was not shown before the held Core response',
                    record,
                )
                app.checks['live_start_progress_before_core_reply'] = True
            app.checks[name + '_first_draw_progress'] = True
            app.capture(name + '-first-draw')
        if self._cold_drop is not None and peer.route.delivery is Delivery.DROP:
            started, self._cold_drop = self._cold_drop, None
            record = {
                'release_to_first_draw_ms': round(
                    (time.monotonic() - started) * 1000, 3
                ),
                'message_count': len(peer.timeline._widgets),
                'empty_label': peer.timeline.empty.text,
                'canvas_draw_ms': round(
                    (time.monotonic() - self._draw_started) * 1000, 3
                ),
            }
            self.records['uncached_drop_first_draw'] = record
            assert (
                peer.timeline._widgets
                or peer.timeline.empty.text == 'Loading messages…'
            ), ('Unresolved archive is shown as empty instead of loading', record)
            app.checks['uncached_drop_first_draw_truthful'] = True
            self._drop_panel = peer
            self._drop_editor = peer.composer.entry
            self._drop_timeline = peer.timeline
        if self._live_open is not None and peer.route.delivery is Delivery.LIVE:
            started, self._live_open = self._live_open, None
            self.records['drop_to_live_first_draw'] = {
                'release_to_first_draw_ms': round(
                    (time.monotonic() - started) * 1000, 3
                ),
                'subtitle': peer.subtitle.text,
                'canvas_draw_ms': round(
                    (time.monotonic() - self._draw_started) * 1000, 3
                ),
            }
            app.checks['drop_to_live_first_draw_observed'] = True
            self._live_panel = peer
            assert self._drop_panel is not None
            self._hidden(self._drop_panel)
            self._first_drop = next(iter(self._drop_panel.timeline._widgets.values()))
        if self._drop is not None and peer.route.delivery is Delivery.DROP:
            started, self._drop = self._drop, None
            texts = [
                item._body.text
                for item in peer.timeline._widgets.values()
                if getattr(item, '_body', None) is not None
            ]
            record = {
                'release_to_first_draw_ms': round(
                    (time.monotonic() - started) * 1000, 3
                ),
                'message_count': len(peer.timeline._widgets),
                'known_archive_message_present': 'Existing Drop' in texts,
                'same_drop_panel_reused': peer is self._drop_panel,
                'title_matches_contact': peer.name.text
                == app.controller.contacts.alias(app.target),
                'title_rect': rectangle(peer.name),
                'title_attached': peer.name.get_root_window() is not None,
                'canvas_draw_ms': round(
                    (time.monotonic() - self._draw_started) * 1000, 3
                ),
            }
            self.records['live_to_drop_first_draw'] = record
            print('NATIVE_GUI_ROUTE_TIMING ' + json.dumps(record), flush=True)
            if app.args.width >= Geometry.BREAKPOINT:
                assert 'Existing Drop' in texts, (
                    'Cached DROP messages are absent after same-peer master selection',
                    record,
                )
                assert peer is self._drop_panel
                assert peer.composer.entry is self._drop_editor
                assert peer.timeline is self._drop_timeline
                assert next(iter(peer.timeline._widgets.values())) is self._first_drop
                app.checks['master_open_drop_reuses_native_pane'] = True
            else:
                assert texts or peer.timeline.empty.text == 'Loading messages…', (
                    'Reopened archive is blank before its read completes',
                    record,
                )
                assert self._drop_panel is not None and peer is not self._drop_panel
                assert self._drop_panel.name.text == ''
                assert not self._drop_panel.timeline._widgets
                self._drop_panel = peer
                app.checks['back_and_picker_reopen_drop_truthful_first_draw'] = True
            assert self._live_panel is not None
            self._hidden(self._live_panel)
            assert peer.name.text == app.controller.contacts.alias(app.target)
            assert peer.name.get_root_window() is not None
            self.peer_header()
            app.checks['explicit_drop_navigation_first_draw'] = True
            app.capture('drop-reopened-first-draw')

    def _hidden(self, pane: PeerView) -> None:
        """Requires a retained background pane to own no native input surface."""
        assert pane.parent is None and pane.disabled
        assert not pane.composer.ptt.held
        assert not any(
            isinstance(item, FocusBehavior) and item.focus
            for item in pane.walk(restrict=True)
        )
        self.app.checks['retained_background_pane_revokes_native_input'] = True

    def departed(self) -> None:
        """Requires retained native references to be cleared after leaving the peer."""
        assert not self.app.shell._peer_projections._views
        for pane in (self._drop_panel, self._live_panel):
            assert pane is not None
            assert pane.name.text == '' and pane.composer.entry.text == ''
            assert not pane.timeline._widgets
            assert pane.get_root_window() is None and pane.disabled
            assert not pane.composer.entry.focus and not pane.composer.ptt.held
        assert self._first_drop is not None
        assert self._first_drop._body.text == ''
        self.app.checks['departed_peer_revokes_both_retained_panes'] = True

    def peer_header(self) -> None:
        """Requires Call and More beside the title and status beside its LIVE control."""
        peer = self.app.peer()
        assert peer is not None
        back = self.app.action('Back', peer)
        assert back is not None
        self._centered('peer_title', peer.name, back)
        self._centered('peer_call', peer.name, peer.call)
        self._centered('peer_more', peer.name, peer.more)
        assert peer.name.parent is peer.call.parent is peer.more.parent
        control = peer.end if peer.end.parent is not None else peer.connect
        if control.parent is not None:
            self._centered('peer_status', peer.subtitle, control)
        left, bottom, width, height = rectangle(peer.name)
        assert left >= 0 and bottom >= 0
        assert left + width <= Window.width and bottom + height <= Window.height, (
            'Peer header is outside the native window',
            rectangle(peer.name),
        )
        self.app.checks['peer_header_vertically_centered'] = True

    def secondary_header(self, title: str) -> None:
        """Requires the actual page title to align with its adjacent Back action."""
        detail = self.app.shell._detail
        assert detail is not None
        back = self.app.action('Back', detail)
        label = next(
            item
            for item in detail.walk(restrict=True)
            if isinstance(item, Label) and item.text == title
        )
        assert back is not None
        self._centered(title.lower() + '_title', label, back)
        self.app.checks[title.lower() + '_header_vertically_centered'] = True

    def quiet_send(self) -> None:
        """Keeps durable send confirmation on its message, without a second toast."""
        app = self.app
        assert app.controller.state.feedback.visible() == '', (
            'Routine send creates redundant action feedback',
            app.controller.state.feedback.visible(),
        )
        assert app.feedback_overlay is not None
        assert app.feedback_overlay.card.parent is None
        app.checks['routine_send_has_no_toast'] = True

    def feedback_bounds(self) -> None:
        """Checks transient action feedback against the active foreground column."""
        app = self.app
        assert app.feedback_overlay is not None and app.shell._detail is not None
        card = app.feedback_overlay.card
        assert card.parent is not None
        anchor = app.shell.feedback_anchor()
        assert anchor is not None
        left, bottom, width, height = rectangle(card)
        x, y, detail_width, detail_height = rectangle(anchor)
        assert left >= x - GEOMETRY_TOLERANCE
        assert left + width <= x + detail_width + GEOMETRY_TOLERANCE
        assert bottom >= y - GEOMETRY_TOLERANCE
        assert bottom + height <= y + detail_height + GEOMETRY_TOLERANCE
        self._centered(
            'feedback_message',
            app.feedback_overlay.message,
            app.feedback_overlay.dismiss,
        )
        self.records['feedback_bounds'] = {
            'card': rectangle(card),
            'detail': rectangle(app.shell._detail),
            'content_anchor': rectangle(anchor),
        }
        app.checks['feedback_inside_foreground_column'] = True

    def _centered(self, name: str, label: Widget, action: Widget) -> None:
        """Compares drawable centers after native text wrapping and layout."""
        _, label_y, _, label_height = rectangle(label)
        _, action_y, _, action_height = rectangle(action)
        difference = abs(label_y + label_height / 2 - action_y - action_height / 2)
        self.records[name] = {'vertical_center_difference': round(difference, 3)}
        assert difference <= GEOMETRY_TOLERANCE, (
            'Text is not vertically centered beside its action',
            name,
            difference,
        )

    def close(self) -> None:
        """Releases fixture-only observers before the native window detaches."""
        for action, callback in self._release_callbacks:
            action.unbind(on_release=callback)
        self._release_callbacks.clear()
        Window.unbind(on_draw=self._drawing)
        self._connect_release.set()
        if self._connect_patch is not None:
            self._connect_patch.close()
            self._connect_patch = None
