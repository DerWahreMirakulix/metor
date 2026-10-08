"""Native X11 GUI acceptance through actual encrypted Core and paired peer IPC.

The actual MetorApp, event loop, public host, SDK, handlers and persistence run
unchanged. Tor process/SOCKS routing uses explicit loopback peers. A bounded
scheduling barrier delays one real Core operation until the first native draw;
the original operation then resumes. XTest supplies synthetic OS input and a
real Terminal child exchanges DROP text. No physical audio stream is opened.
"""

# ruff: noqa: E402

import argparse
import base64
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from frontend_e2e_runtime import EncryptedFrontendRuntime
from frontend_gui_terminal import GuiTerminalPeer
from gui_native_audio_scan import NativeAudioProbe
from gui_native_route import verify_gui_module_origin
from gui_native_secondary import NativeSecondaryProbe
from gui_native_live_stop import NativeLiveStopProbe
from gui_native_ux import GEOMETRY_TOLERANCE, NativeUxProbe
from gui_native_x11 import NativeX11Input, rectangle
from metor.client import FrontendLaunchContext, MetorClient
from metor.core.api import (
    AcceptCommand,
    AddContactCommand,
    ConnectedEvent,
    ConnectionRejectedEvent,
    ConfigUpdatedEvent,
    ContactAddedEvent,
    Delivery,
    DropQueuedEvent,
    GetMessagesCommand,
    IpcEvent,
    MessageReceivedEvent,
    MessageDirectionCode,
    MessageStatusCode,
    MessagesDataEvent,
    RuntimeSnapshotEvent,
    RejectCommand,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
    VoiceContent,
    SendMessageCommand,
    SetConfigCommand,
    TextContent,
    TextAcceptedEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry, GuiLimits
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.time import display_timestamp
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.views.contacts.list import ContactListView
from metor.ui.gui.views.peer.timeline import projection
from metor.ui.gui.widgets import Action, SecretInput, TextField
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.voice import VoiceCard


POLL_SECONDS = 0.05
INPUT_SETTLE_SECONDS = 0.15
PHASE_DEADLINE_SECONDS = 20.0
RUN_DEADLINE_SECONDS = 180.0
INITIAL_ALIAS = 'MiXeD Initial Contact'
BACKGROUND_ALIAS = 'Updated Elsewhere'
FINAL_ALIAS = 'MiXeD Renamed Contact'
DROP_TEXTS = (
    'First native Enter',
    'Second native click',
    'Third native click',
    'First line\nSecond line',
)
LIVE_TEXT = 'Native Live text'
LIVE_REPLY = 'Remote Live reply'
VOICE_ID = 'native-incoming-voice'
TERMINAL_DROP = 'Actual Terminal peer to native GUI'
GUI_TERMINAL_DROP = 'Native GUI to actual Terminal peer'
REJECTED_DROP = 'Preserved after Core rejection'


@dataclass
class Step:
    """One named bounded GUI observation followed by deliberate native input."""

    name: str
    ready: Callable[[], bool]
    act: Callable[[], None]


def distribution(values: list[float]) -> dict[str, float]:
    """Summarizes observed timings without claiming a hardware latency threshold."""
    ordered = sorted(values)
    return {
        'p50_ms': round(statistics.median(ordered) * 1000, 3),
        'p95_ms': round(
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 3
        ),
        'max_ms': round(max(ordered) * 1000, 3),
    }


class NativeCoreApp(MetorApp):
    """Drives unchanged Metor UI with OS events and observes public Core outcomes."""

    def __init__(
        self,
        runtime: EncryptedFrontendRuntime,
        observer: MetorClient,
        peer: MetorClient,
        args: argparse.Namespace,
    ) -> None:
        """Retains only fixture clients and non-secret acceptance metadata."""
        super().__init__(
            FrontendLaunchContext(
                runtime.profile_name, runtime.frontend_host(), debug=True
            ),
            DeviceConfiguration(width_px=args.width, height_px=args.height),
        )
        self.runtime, self.observer, self.remote, self.args = (
            runtime,
            observer,
            peer,
            args,
        )
        assert runtime.peer is not None
        self.target = runtime.peer.onion
        self.native = NativeX11Input()
        self.ux = NativeUxProbe(self)
        self.live_stop_probe = NativeLiveStopProbe(self)
        self.audio_probe = NativeAudioProbe(self)
        self.terminal = GuiTerminalPeer(runtime)
        self.steps: deque[Step] = deque()
        self.checks: dict[str, object] = {}
        self.images: dict[str, str] = {}
        self.timings: list[float] = []
        self.confirmation_timings: dict[str, float] = {}
        self.frames: list[float] = []
        self.scheduler_samples: list[tuple[str, float]] = []
        self.fixture_costs: dict[str, float] = {}
        self.last_tick = 0.0
        self.last_frame = 0.0
        self.started = self.phase_started = time.monotonic()
        self.not_before = self.started
        self.exit_selected = False
        self.failure: BaseException | None = None
        self.first_geometry: tuple[float, float, float, float] | None = None
        self.first_draw_at = 0.0
        self.focus_owner: TextField | None = None
        self.cli_worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix='native-gui-cli'
        )
        self.cli_future: Future[subprocess.CompletedProcess[str]] | None = None
        self.voice_future: Future[None] | None = None
        self.core_checks: dict[str, Future[None]] = {}
        self.pending_snapshot: Future[RuntimeSnapshotEvent | None] | None = None
        self.live_start_count = 0

    def on_start(self) -> None:
        """Starts the bounded observer after the actual app attaches to SDL Window."""
        super().on_start()
        Window.bind(on_flip=self._frame)
        Clock.schedule_interval(self._heartbeat, 0)
        Clock.schedule_once(self._arm, 0.6)

    def _heartbeat(self, _elapsed: float) -> None:
        """Measures continuous UI scheduler ticks even when the idle canvas needs no redraw."""
        now = time.monotonic()
        phase = self.steps[0].name if self.steps else 'startup_or_exit'
        if self.last_tick:
            self.scheduler_samples.append((phase, now - self.last_tick))
        self.last_tick = now

    def _arm(self, _elapsed: float) -> None:
        """Waits for the first native draw to flush SDL's initial X11 window requests."""
        self.native.activate()
        self._scenario()
        Clock.schedule_interval(self._step, POLL_SECONDS)

    def _frame(self, *_args: object) -> None:
        """Records real draw intervals and first displayed actual archive geometry."""
        now = time.monotonic()
        if self.last_frame:
            self.frames.append(now - self.last_frame)
        self.last_frame = now
        try:
            self.ux.frame()
            self.live_stop_probe.frame()
            self.audio_probe.frame()
        except BaseException as error:
            self.failure = error
            self.capture('first-frame-failure')
            self.ux.close()
            self.live_stop_probe.close()
            self.audio_probe.close()
            self.stop()
            return
        peer = self.peer()
        if self.first_geometry is None and peer and peer.timeline._widgets:
            self.first_geometry = rectangle(next(iter(peer.timeline._widgets.values())))
            self.first_draw_at = now

    def _step(self, _elapsed: float) -> bool:
        """Keeps native input asynchronous and requires each observed phase to finish."""
        try:
            now = time.monotonic()
            assert now - self.started < RUN_DEADLINE_SECONDS, (
                'Native Core GUI deadline exceeded'
            )
            if not self.steps:
                return True
            step = self.steps[0]
            assert now - self.phase_started < PHASE_DEADLINE_SECONDS, (
                'Native GUI phase did not settle',
                step.name,
            )
            for name, future in tuple(self.core_checks.items()):
                if not future.done():
                    return True
                future.result()
                self.checks[name] = True
                del self.core_checks[name]
            if now < self.not_before or not step.ready():
                return True
            self.timings.append(now - self.phase_started)
            if step.name.endswith('_visible_without_reentry') or step.name in {
                'background_event_retains_editor',
                'live_text_visible',
                'contact_confirmed_immediate_projection',
            }:
                self.confirmation_timings[step.name] = round(
                    (now - self.phase_started) * 1000, 3
                )
            self.checks[step.name] = True
            print('NATIVE_GUI_PHASE ' + step.name, flush=True)
            self.steps.popleft()
            step.act()
            self.phase_started = time.monotonic()
            self.not_before = self.phase_started + INPUT_SETTLE_SECONDS
        except BaseException as error:
            self.failure = error
            self.ux.close()
            self.live_stop_probe.close()
            self.audio_probe.close()
            peer = self.peer()
            if peer is not None:
                print(
                    'NATIVE_GUI_FAILURE_STATE '
                    + json.dumps(
                        {
                            'route': self.controller.state.route.view,
                            'busy': self.controller.state.busy,
                            'live_state': next(
                                (
                                    item.session_state
                                    for item in self.controller.state.snapshot.live_contexts
                                    if item.onion == self.target
                                ),
                                None,
                            )
                            if self.controller.state.snapshot is not None
                            else None,
                            'live_starting': self.controller.live.starting(self.target),
                            'live_stopping': self.controller.live.stop_status(
                                self.target
                            ),
                            'live_failure': self.controller.live.failure(self.target),
                            'live_context_facts': [
                                {
                                    'state': item.session_state,
                                    'recovery_eligible': item.recovery_eligible,
                                    'outbound_attempt_present': bool(
                                        item.outbound_attempt_id
                                    ),
                                    'generation': item.context_generation,
                                }
                                for item in self.controller.state.snapshot.live_contexts
                                if item.onion == self.target
                            ]
                            if self.controller.state.snapshot is not None
                            else [],
                            'live_subtitle': peer.subtitle.text,
                            'live_connect_attached': peer.connect.get_root_window()
                            is not None,
                            'live_connect_disabled': peer.connect.disabled,
                            'live_connect_in_slot': peer.connect.parent
                            is peer.live_slot,
                            'live_slot_actions': [
                                item.accessible_name for item in peer.live_slot.children
                            ],
                            'archive_count': len(self.controller.messages.messages)
                            if self.controller.messages
                            else 0,
                            'archive_has_voice': bool(
                                self.controller.messages
                                and any(
                                    row.msg_id == VOICE_ID
                                    for row in self.controller.messages.messages
                                )
                            ),
                            'voice_metadata': [
                                item.metadata.text
                                for item in peer.timeline._widgets.values()
                                if isinstance(item, VoiceCard)
                            ],
                            'archive_needed': self.controller.archive.needed,
                            'messages_needed': self.controller._messages_needed,
                        }
                    ),
                    flush=True,
                )
            self.capture('failure')
            self.stop()
            return False
        return True

    def add(
        self,
        name: str,
        ready: Callable[[], bool],
        act: Callable[[], None] = lambda: None,
    ) -> None:
        """Adds an explicitly named predicate without blocking the native loop."""
        self.steps.append(Step(name, ready, act))

    def scope(self) -> Widget:
        """Selects the attached modal or normal app root for concrete control lookup."""
        assert self.root is not None
        return ActionSheet.current if ActionSheet.current is not None else self.root

    def action(self, name: str, scope: Widget | None = None) -> Action | None:
        """Finds a currently attached native action by its end-user label."""
        return next(
            (
                item
                for item in (scope or self.scope()).walk(restrict=True)
                if isinstance(item, Action)
                and (
                    item.accessible_name == name
                    or item.accessible_name.startswith(name + ', ')
                    or item.label.text == name
                )
                and item.get_root_window() is not None
            ),
            None,
        )

    def click(self, name: str, scope: Widget | None = None) -> None:
        """Sends a native pointer click to the actual currently displayed action."""
        action = self.action(name, scope)
        assert action is not None, ('Missing native action', name)
        self.native.click(action)

    def peer(self) -> PeerView | None:
        """Returns only the currently attached peer panel."""
        if self.shell is None:
            return None
        return next(
            (item for item in self.shell.walk() if isinstance(item, PeerView)), None
        )

    def contact_list(self) -> ContactListView | None:
        """Scopes saved-contact choices away from desktop sidebar conversation rows."""
        return next(
            (item for item in self.scope().walk() if isinstance(item, ContactListView)),
            None,
        )

    def entry(self) -> TextField:
        """Returns the actual stable editor of the displayed conversation."""
        peer = self.peer()
        assert peer is not None and peer.composer.parent is not None
        return peer.composer.entry

    def route(self, view: str) -> bool:
        """Waits for both controller navigation and its concrete repaint."""
        return (
            self.controller.state.route.view == view
            and not self.controller.state.busy
            and self.modal_closed()
            and self.action('Back') is not None
        )

    def modal_closed(self) -> bool:
        """Requires the dismissed native modal to have released its input surface."""
        return ActionSheet.current is None and not any(
            isinstance(item, ActionSheet) for item in Window.children
        )

    def text_visible(self, text: str) -> bool:
        """Observes actual timeline message widgets, independent of archive timing."""
        peer = self.peer()
        return bool(
            peer
            and any(
                getattr(item, '_body', None) is not None and item._body.text == text
                for item in peer.timeline._widgets.values()
            )
        )

    def archive(self, client: MetorClient, target: str) -> MessagesDataEvent:
        """Reads confirmed durable rows using a separate public SDK connection."""
        result = client.request(GetMessagesCommand(target), MessagesDataEvent)
        assert result is not None
        return result

    def capture(self, name: str) -> None:
        """Keeps only synthetic fixture UI screenshots, never password-entry frames."""
        path = self.args.images / f'{self.args.width}x{self.args.height}-{name}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        saved = Window.screenshot(name=str(path))
        self.fixture_costs[f'screenshot_{name}'] = round(
            (time.monotonic() - started) * 1000, 3
        )
        assert saved is not None
        Path(saved).replace(path)
        self.images[name] = str(path.resolve())

    def _verify_drop(self, index: int) -> None:
        """Requires one exact durable identity for every deliberate native send."""
        text = DROP_TEXTS[index]

        def verify() -> None:
            """Reads independent actual persistence outside the native GUI thread."""
            rows = self.archive(self.observer, self.target).messages
            assert (
                sum(
                    isinstance(row.content, TextContent) and row.content.text == text
                    for row in rows
                )
                == 1
            )

        assert self.entry().text == ''
        assert not self.controller.text.pending(self.target, Delivery.DROP)
        self.ux.quiet_send()
        self.core_checks[f'drop_{index + 1}_durable_once'] = self.cli_worker.submit(
            verify
        )

    def _scenario(self) -> None:
        """Exercises actual startup, repeated sends, background events, navigation and audio help."""
        gui = self.controller
        self.add(
            'native_open',
            lambda: (
                Window.width == self.args.width
                and Window.height == self.args.height
                and self.native.size() == tuple(Window.system_size)
                and not gui.state.busy
                and self.action('Open profile') is not None
                and not self.action('Open profile').disabled
            ),
            lambda: self.click('Open profile'),
        )
        self.add(
            'native_password_focus',
            lambda: bool(
                gui.interactions.prompt
                and any(isinstance(item, SecretInput) for item in self.scope().walk())
            ),
            lambda: self.native.click(
                next(
                    item
                    for item in self.scope().walk()
                    if isinstance(item, SecretInput)
                )
            ),
        )
        self.add(
            'native_password_type',
            lambda: any(
                isinstance(item, SecretInput) and item.focus
                for item in self.scope().walk()
            ),
            lambda: self.native.type(self.runtime.password),
        )
        self.add(
            'native_password_submit',
            lambda: any(
                isinstance(item, SecretInput) and item.text == self.runtime.password
                for item in self.scope().walk()
            ),
            lambda: self.click('Open profile'),
        )
        self.add(
            'native_secure_profile_setup',
            lambda: self.action('Use profile password') is not None,
            lambda: self.click('Use profile password'),
        )
        self.add(
            'authenticated_root',
            lambda: (
                not gui.state.covered
                and gui.state.snapshot is not None
                and self.action('New Drop') is not None
            ),
            lambda: self.click('New Drop'),
        )
        self.add(
            'new_drop_picker',
            lambda: (
                self.route('V11')
                and self.contact_list() is not None
                and self.action(INITIAL_ALIAS, self.contact_list()) is not None
            ),
            self._open_initial_drop,
        )
        self.add(
            'real_archive_first_frame',
            lambda: (
                self.route('V08')
                and self.first_geometry is not None
                and time.monotonic() - self.first_draw_at > 0.4
            ),
            self._check_geometry,
        )
        self.add(
            'drop_rejection_disable_at_core',
            lambda: not gui.state.busy,
            lambda: self._configure_drops(False),
        )
        self.add(
            'drop_rejection_focus',
            lambda: not gui.state.busy,
            lambda: self.native.click(self.entry()),
        )
        self.add(
            'drop_rejection_type',
            lambda: self.entry().focus,
            lambda: self.native.type(REJECTED_DROP),
        )
        self.add(
            'drop_rejection_send',
            lambda: self.entry().text == REJECTED_DROP,
            lambda: self.native.key('Return'),
        )
        self.add(
            'drop_rejection_visible_at_draft',
            lambda: (
                self.peer().composer.note.text
                == 'Drops are disabled. Your draft is still here.'
            ),
            self._verify_rejected_drop,
        )
        self.add(
            'drop_rejection_restore_core',
            lambda: not gui.state.busy,
            lambda: self._configure_drops(True),
        )
        self.add(
            'drop_rejection_explicit_retry',
            lambda: self.entry().text == REJECTED_DROP,
            lambda: self.native.key('Return'),
        )
        self.add(
            'drop_rejection_retry_accepted_once',
            lambda: self.entry().text == '' and self.text_visible(REJECTED_DROP),
            self._verify_retried_drop,
        )
        for index, text in enumerate(DROP_TEXTS):
            self.add(
                f'drop_{index + 1}_focus',
                lambda: self.peer() is not None and not gui.state.busy,
                lambda: self.native.click(self.entry()),
            )
            self.add(
                f'drop_{index + 1}_type',
                lambda: self.entry().focus,
                lambda value=text: self.native.type(value),
            )
            self.add(
                f'drop_{index + 1}_input',
                lambda value=text: self.entry().text == value,
                lambda use_enter=index in (0, 3): (
                    self.native.key('Return')
                    if use_enter
                    else self.native.click(self.peer().composer.send)
                ),
            )
            self.add(
                f'drop_{index + 1}_visible_without_reentry',
                lambda value=text: self.entry().text == '' and self.text_visible(value),
                lambda current=index: self._verify_drop(current),
            )
        self.add(
            'actual_terminal_peer_start',
            lambda: not gui.state.busy,
            self._start_terminal_peer,
        )
        self.add(
            'actual_terminal_drop_visible_in_gui',
            lambda: self.text_visible(TERMINAL_DROP),
            lambda: self.native.click(self.entry()),
        )
        self.add(
            'gui_to_terminal_drop_type',
            lambda: self.entry().focus,
            lambda: self.native.type(GUI_TERMINAL_DROP),
        )
        self.add(
            'gui_to_terminal_drop_send',
            lambda: self.entry().text == GUI_TERMINAL_DROP,
            lambda: self.native.key('Return'),
        )
        self.add(
            'gui_to_terminal_drop_visible',
            lambda: self.entry().text == '' and self.text_visible(GUI_TERMINAL_DROP),
            self._finish_terminal_peer,
        )
        self.add(
            'incoming_voice_publish', lambda: not gui.state.busy, self._publish_voice
        )
        self.add('incoming_voice_native_card', self._voice_ready, self._verify_voice)
        self.add(
            'incoming_voice_native_play',
            lambda: self._voice_ready() and not self.voice_card().play.disabled,
            lambda: self.native.click(self.voice_card().play),
        )
        self.add(
            'incoming_voice_closed_audio_help',
            lambda: (
                ActionSheet.current is not None
                and ActionSheet.current.heading == 'Playback unavailable'
            ),
            self._check_voice_unread,
        )
        self.add(
            'incoming_voice_close_help',
            lambda: self.action('Close') is not None,
            self._close_then_focus,
        )
        self.add(
            'background_typing_focus',
            lambda: self.modal_closed() and not gui.state.busy and self.entry().focus,
        )
        self.add(
            'background_typing_start',
            lambda: self.entry().focus,
            lambda: self.native.type('Keep typing'),
        )
        self.add(
            'real_background_alias_event',
            lambda: self.entry().text == 'Keep typing',
            self._background_rename,
        )
        self.add(
            'background_event_retains_editor',
            lambda: (
                gui.contacts.alias(self.target) == BACKGROUND_ALIAS
                and self.peer().name.text == BACKGROUND_ALIAS
                and self.cli_future is not None
                and self.cli_future.done()
            ),
            self._verify_focus,
        )
        self.add(
            'background_typed_text_retained',
            lambda: self.entry().text == 'Keep typing smoothly',
            lambda: self.native.key('a', modifiers=('Control_L',)),
        )
        self.add(
            'background_clear_draft',
            lambda: self.entry().focus,
            lambda: self.native.key('BackSpace'),
        )
        self.add(
            'drop_to_live_projection',
            lambda: self.entry().text == '',
            self._switch_live,
        )
        self.add(
            'live_projection_no_implicit_connect',
            lambda: (
                self.route('V09')
                and self.peer().subtitle.text == 'No Live connection'
                and not self.peer().connect.disabled
            ),
            self._start_live,
        )
        self.add(
            'live_pending_before_core_response',
            lambda: (
                'live_start_1' in self.ux.records and self.ux.connect_entered.is_set()
            ),
            self._duplicate_live_start,
        )
        self.add('live_counterpart_decline', self._peer_pending, self._reject_live)
        self.add(
            'live_decline_actionable_without_toast',
            self._live_failure_visible,
            self._verify_declined_live,
        )
        self.add(
            'live_retry_native',
            lambda: self.action('Retry Live', self.peer()) is not None,
            self._start_live,
        )
        self.add(
            'live_cancel_counterpart_pending',
            self._peer_pending,
            self.live_stop_probe.cancel,
        )
        self.add(
            'live_cancel_progress_before_core_reply',
            self.live_stop_probe.pending_visible,
            self.live_stop_probe.duplicate,
        )
        self.add('live_cancel_confirmed', self.live_stop_probe.ended, self._start_live)
        self.add('live_counterpart_pending', self._peer_pending, self._accept_live)
        self.add(
            'live_connected',
            lambda: (
                self.route('V09')
                and self.peer().subtitle.text == 'Connected · Live'
                and self.peer().composer.parent is not None
            ),
            lambda: self.native.click(self.entry()),
        )
        self.add(
            'live_type', lambda: self.entry().focus, lambda: self.native.type(LIVE_TEXT)
        )
        self.add(
            'live_send_enter',
            lambda: self.entry().text == LIVE_TEXT,
            lambda: self.native.key('Return'),
        )
        self.add(
            'live_text_visible',
            lambda: (
                self.entry().text == ''
                and self.text_visible(LIVE_TEXT)
                and len(self.args.peer_events) == 1
            ),
            self._verify_live,
        )
        self.add(
            'live_peer_reply', lambda: not gui.state.busy, self._publish_live_reply
        )
        self.add(
            'incoming_live_timestamp_rendered',
            lambda: self.text_visible(LIVE_REPLY),
            self._verify_live_timestamp,
        )
        self.add(
            'live_end_before_transport_failure',
            lambda: self.action('End Live', self.peer()) is not None,
            lambda: self.click('End Live', self.peer()),
        )
        self.add(
            'live_ended_native',
            lambda: (
                self.peer().subtitle.text == 'No Live connection'
                and not self.peer().connect.disabled
            ),
            self._disable_peer_route,
        )
        self.add(
            'live_start_unreachable_route',
            lambda: not self.peer().connect.disabled,
            self._start_live,
        )
        self.add(
            'live_failed_actionable_without_toast',
            self._live_failure_visible,
            self._verify_failed_live,
        )
        self.add(
            'live_to_drop_projection',
            lambda: not self.peer().connect.disabled,
            self._switch_drop,
        )
        self.add(
            'missing_audio_call_action',
            lambda: self.route('V08') and not self.peer().call.disabled,
            lambda: self.native.click(self.peer().call),
        )
        self.add(
            'missing_audio_modal',
            lambda: (
                ActionSheet.current is not None
                and ActionSheet.current.heading == 'Calls unavailable'
            ),
            lambda: self.capture('calls-unavailable'),
        )
        self.add(
            'missing_audio_go_settings',
            lambda: self.action('Go to audio settings') is not None,
            self._open_audio_settings,
        )
        self.add(
            'audio_closed_settings_modal',
            lambda: (
                ActionSheet.current is not None
                and ActionSheet.current.heading == 'Audio settings'
            ),
            self._check_audio,
        )
        self.add(
            'audio_close_native',
            lambda: self.action('Close') is not None,
            lambda: self.audio_probe.press_close(self.action('Close')),
        )
        self.add(
            'audio_close_restores_peer',
            lambda: ActionSheet.current is None and self.route('V08'),
            lambda: self.click('Back', self.peer()),
        )
        self.add(
            'peer_back_leaves_conversation',
            lambda: (
                self.route('V11')
                and self.peer() is None
                and self.contact_list() is not None
            ),
            self._leave_peer_picker,
        )
        self.add(
            'picker_back_root',
            lambda: (
                gui.state.route.view == 'V06' and self.action('Contacts') is not None
            ),
            lambda: (
                self.click(BACKGROUND_ALIAS, self.shell._master)
                if self.args.width >= Geometry.BREAKPOINT
                else self.click('Contacts')
            ),
        )
        if self.args.width >= Geometry.BREAKPOINT:
            self.add(
                'wide_master_selection_native',
                lambda: self.route('V08'),
                lambda: self.click('Back', self.peer()),
            )
            self.add(
                'wide_master_back_neutral_detail',
                lambda: (
                    gui.state.route.view == 'V06'
                    and self.peer() is None
                    and self.modal_closed()
                ),
                lambda: self.click('Contacts'),
            )
        self.add(
            'contact_actions',
            lambda: (
                self.route('V12')
                and self.contact_list() is not None
                and self.action(BACKGROUND_ALIAS, self.contact_list()) is not None
            ),
            lambda: self.click(BACKGROUND_ALIAS, self.contact_list()),
        )
        self.add(
            'contact_rename_menu',
            lambda: self.action('Rename') is not None,
            lambda: self.click('Rename'),
        )
        self.add(
            'contact_rename_focus',
            lambda: self._rename_alias() is not None,
            self._focus_alias,
        )
        self.add(
            'contact_select_alias',
            lambda: bool((alias := self._rename_alias()) is not None and alias.focus),
            lambda: self.native.key('a', modifiers=('Control_L',)),
        )
        self.add(
            'contact_type_mixed_case',
            lambda: self.route('V13'),
            lambda: self.native.type(FINAL_ALIAS),
        )
        self.add(
            'contact_save_native',
            lambda: (
                gui.contacts.form is not None and gui.contacts.form.alias == FINAL_ALIAS
            ),
            lambda: self.click('Rename'),
        )
        self.add(
            'contact_confirmed_immediate_projection',
            lambda: (
                self.route('V12')
                and gui.contacts.alias(self.target) == FINAL_ALIAS
                and self.action(FINAL_ALIAS) is not None
            ),
            self._verify_alias,
        )
        self.add(
            'feedback_visible_once',
            lambda: (
                self.feedback_overlay is not None
                and self.feedback_overlay.message.text == 'Contact renamed'
            ),
            self._verify_feedback,
        )
        self.add(
            'feedback_expires_without_navigation',
            lambda: (
                self.feedback_overlay is not None
                and self.feedback_overlay.message.text == ''
                and not gui.state.feedback.visible()
            ),
            lambda: self.click('Back'),
        )
        self.add(
            'notifications_open',
            lambda: (
                gui.state.route.view == 'V06'
                and self.action('Notifications') is not None
            ),
            lambda: self.click('Notifications'),
        )
        self.add(
            'notifications_title_centered',
            lambda: self.route('V16'),
            self._verify_notifications,
        )
        self.add(
            'settings_open',
            lambda: (
                gui.state.route.view == 'V06' and self.action('Settings') is not None
            ),
            lambda: self.click('Settings'),
        )
        self.add('settings_heading', lambda: self.route('V17'), self._verify_settings)
        NativeSecondaryProbe(self).add_steps()
        self.add(
            'settings_exit_scroll', lambda: self.route('V17'), self._scroll_settings
        )
        self.add('settings_exit_reachable', self._exit_reachable, self._exit)

    def _check_geometry(self) -> None:
        """Rejects a delayed short-message jump on the actual archive draw path."""
        peer = self.peer()
        assert peer is not None and self.first_geometry is not None
        self.ux.peer_header()
        final = rectangle(next(iter(peer.timeline._widgets.values())))
        assert all(
            abs(before - after) <= 1
            for before, after in zip(self.first_geometry, final, strict=True)
        ), ('First archive geometry changed', self.first_geometry, final)
        self.checks['first_geometry'] = self.first_geometry
        self.checks['settled_geometry'] = final
        seed = next(
            item
            for item in self.controller.messages.messages
            if item.msg_id == 'native-seed'
        )
        assert next(iter(peer.timeline._widgets.values()))._metadata.text.startswith(
            display_timestamp(seed.timestamp) + ' · '
        )
        self.capture('drop-initial')

    def _background_rename(self) -> None:
        """Runs the actual CLI in a separate worker while native input continues."""
        self.focus_owner = self.entry()

        def rename() -> subprocess.CompletedProcess[str]:
            """Uses the actual CLI and protected Core authentication outside the GUI thread."""
            return subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'metor',
                    '-p',
                    self.runtime.endpoint_profile_name,
                    'contacts',
                    'rename',
                    INITIAL_ALIAS,
                    BACKGROUND_ALIAS,
                ],
                cwd=self.runtime.data_parent,
                env=self.runtime.environment(),
                input=self.runtime.password + '\n',
                text=True,
                capture_output=True,
                timeout=PHASE_DEADLINE_SECONDS,
                check=False,
            )

        self.cli_future = self.cli_worker.submit(rename)
        self.native.type(' smoothly')

    def voice_card(self) -> VoiceCard:
        """Finds the concrete incoming card for one actual remote Voice identity."""
        peer = self.peer()
        assert peer is not None
        return next(
            item
            for item in peer.timeline._widgets.values()
            if isinstance(item, VoiceCard) and item.target.msg_id == VOICE_ID
        )

    def _publish_voice(self) -> None:
        """Publishes synthetic PCM through the actual remote producer and peer transport."""

        def publish() -> None:
            """Runs bounded encrypted persistence off the native UI thread."""
            assert (
                self.remote.begin_voice(
                    self.runtime.onion, Delivery.DROP, VOICE_ID, PcmVoice.CODEC
                )
                is not None
            )
            frames = 50
            for frame in range(frames):
                assert isinstance(
                    self.remote.append_voice(
                        VOICE_ID,
                        frame * PcmVoice.FRAME_BYTES,
                        base64.b64encode(bytes(PcmVoice.FRAME_BYTES)).decode('ascii'),
                    ),
                    VoiceChunkAcceptedEvent,
                )
            finalized = self.remote.finalize_voice(
                VOICE_ID, PcmVoice.duration_ms(PcmVoice.FRAME_BYTES * frames)
            )
            assert isinstance(finalized, VoiceFinalizedEvent)
            assert finalized.size_bytes == PcmVoice.FRAME_BYTES * frames
            assert self.remote.commit_voice(self.runtime.onion, VOICE_ID) is not None

        self.voice_future = self.cli_worker.submit(publish)

    def _voice_ready(self) -> bool:
        """Waits for actual remote commit and native projection without replaying audio."""
        if self.voice_future is None or not self.voice_future.done():
            return False
        self.voice_future.result()
        peer = self.peer()
        archive = self.controller.messages
        if archive is None or not any(
            item.msg_id == VOICE_ID
            and isinstance(item.content, VoiceContent)
            and item.content.size_bytes == PcmVoice.FRAME_BYTES * 50
            for item in archive.messages
        ):
            return False
        expected = (
            display_timestamp(
                next(
                    item.timestamp
                    for item in archive.messages
                    if item.msg_id == VOICE_ID
                )
            )
            + ' · '
        )
        return bool(
            peer
            and any(
                isinstance(item, VoiceCard)
                and item.target.msg_id == VOICE_ID
                and item._available == PcmVoice.FRAME_BYTES * 50
                and expected in item.metadata.text
                for item in peer.timeline._widgets.values()
            )
        )

    def _verify_voice(self) -> None:
        """Requires unread metadata, readable time and a nonfocusable progress track."""
        card = self.voice_card()
        assert not card.seek.is_focusable and not card.seek.focus
        voice = next(
            row for row in self.controller.messages.messages if row.msg_id == VOICE_ID
        )
        assert display_timestamp(voice.timestamp) + ' · ' in card.metadata.text
        self.core_checks['voice_initial_persisted_unread'] = self.cli_worker.submit(
            self._verify_core_voice_unread
        )
        self.capture('incoming-voice')

    def _check_voice_unread(self) -> None:
        """Missing playback hardware neither starts a stream nor consumes protected Voice content."""
        assert not self.controller.playback.running
        self.core_checks['missing_playback_keeps_voice_unread'] = (
            self.cli_worker.submit(self._verify_core_voice_unread)
        )
        self.capture('playback-unavailable')

    def _verify_core_voice_unread(self) -> None:
        """Reads the protected receipt independently without blocking the GUI scheduler."""
        voice = next(
            row
            for row in self.archive(self.observer, self.target).messages
            if row.msg_id == VOICE_ID and row.direction is MessageDirectionCode.IN
        )
        assert voice.status is MessageStatusCode.UNREAD

    def _close_then_focus(self) -> None:
        """Requires the first native frame after Close to accept a subsequent click."""
        sheet = ActionSheet.current
        assert sheet is not None
        started = [0.0]

        def dismissing(*_args: object) -> None:
            """Observes actual native dismissal without changing its behavior."""
            started[0] = time.monotonic()
            Clock.schedule_once(next_action, 0)

        def next_action(_elapsed: float) -> None:
            """Clicks the editor immediately after the closed modal releases its surface."""
            try:
                assert sheet not in Window.children and ActionSheet.current is None, (
                    'Closed modal still consumes the next native action'
                )
                self.confirmation_timings['modal_close_to_next_frame_ms'] = round(
                    (time.monotonic() - started[0]) * 1000, 3
                )
                self.checks['modal_close_releases_next_native_action'] = True
                self.native.click(self.entry())
            except BaseException as error:
                self.failure = error
                self.stop()

        sheet.bind(on_pre_dismiss=dismissing)
        self.click('Close')

    def _verify_focus(self) -> None:
        """Requires background projection to preserve the actual editor object and cursor."""
        assert self.entry() is self.focus_owner and self.entry().focus
        assert (
            self.entry().text == 'Keep typing smoothly'
            and self.entry().cursor_index() == len('Keep typing smoothly')
        )
        assert self.cli_future is not None
        assert self.cli_future.result().returncode == 0, (
            'The background CLI rename failed'
        )
        self.checks['cli_core_gui_cross_surface'] = True

    def _start_terminal_peer(self) -> None:
        """Starts a real Terminal child and sends its DROP outside the GUI thread."""

        def start() -> None:
            """Uses only the child terminal's native PTY commands and public Core."""
            self.terminal.start()
            self.terminal.send_drop(TERMINAL_DROP)

        self.core_checks['terminal_peer_drop_sent'] = self.cli_worker.submit(start)

    def _configure_drops(self, allowed: bool) -> None:
        """Uses authenticated public configuration to exercise a genuine Core refusal."""

        def configure() -> None:
            """Changes only the disposable sender's profile policy on the worker SDK."""
            result = self.observer.request(
                SetConfigCommand('daemon.allow_drops', allowed), ConfigUpdatedEvent
            )
            assert result is not None

        self.core_checks[f'core_drop_policy_{allowed}'] = self.cli_worker.submit(
            configure
        )

    def _verify_rejected_drop(self) -> None:
        """Requires persistent draft-local error text and a retained, editable draft."""
        peer = self.peer()
        assert peer is not None
        assert self.entry().text == REJECTED_DROP and self.entry().focus
        assert peer.composer.note.parent is peer.composer
        assert not self.controller.text.pending(self.target, Delivery.DROP)
        assert not self.controller.state.feedback.visible()
        assert not self.text_visible(REJECTED_DROP)
        self.capture('drop-rejected-draft')

    def _verify_retried_drop(self) -> None:
        """Requires the deliberate retry to create one durable message and clear its error."""

        def verify() -> None:
            """Reads persistence independently after native user confirmation."""
            rows = self.archive(self.observer, self.target).messages
            assert (
                sum(
                    isinstance(row.content, TextContent)
                    and row.content.text == REJECTED_DROP
                    for row in rows
                )
                == 1
            )

        self.ux.quiet_send()
        assert not self.peer().composer.note.text
        self.core_checks['rejected_draft_retried_exactly_once'] = (
            self.cli_worker.submit(verify)
        )

    def _open_initial_drop(self) -> None:
        """Measures initial loading from the native contact selection through first draw."""
        action = self.action(INITIAL_ALIAS, self.contact_list())
        assert action is not None
        self.ux.arm_cold_drop(action)
        self.native.click(action)

    def _finish_terminal_peer(self) -> None:
        """Requires the reverse GUI DROP to appear in the actual running Terminal."""

        def finish() -> None:
            """Checks rendered peer receipt before orderly child/terminal cleanup."""
            self.terminal.wait_text(GUI_TERMINAL_DROP)
            self.terminal.close()

        self.ux.quiet_send()
        self.core_checks['gui_terminal_actual_process_roundtrip'] = (
            self.cli_worker.submit(finish)
        )

    def _start_live(self) -> None:
        """Observes the first actual draw after an OS-level Start or Retry click."""
        peer = self.peer()
        assert peer is not None
        self.live_start_count += 1
        if self.live_start_count == 1:
            self.ux.hold_first_connect()
        self.ux.arm_start(f'live_start_{self.live_start_count}', peer.connect)
        self.native.click(peer.connect)

    def _duplicate_live_start(self) -> None:
        """Clicks the disabled Start control again before allowing Core to reply."""
        peer = self.peer()
        assert peer is not None
        self.native.click(peer.connect, allow_disabled=True)

        def release(_elapsed: float) -> None:
            """Releases a bounded real server scheduling barrier after native input settles."""
            try:
                self.ux.release_connect()
            except BaseException as error:
                self.failure = error
                self.ux.close()
                self.stop()

        Clock.schedule_once(release, INPUT_SETTLE_SECONDS)

    def _reject_live(self) -> None:
        """Declines the real remote invitation through its recipient-owned handle."""

        def reject() -> None:
            """Reads and declines only the current invitation on the worker SDK."""
            snapshot = self.remote.runtime_snapshot()
            assert snapshot is not None
            invitation = next(
                item for item in snapshot.pending if item.onion == self.runtime.onion
            )
            assert invitation.action_handle is not None
            result = self.remote.request(
                RejectCommand(self.runtime.onion, invitation.action_handle), IpcEvent
            )
            assert isinstance(result, ConnectionRejectedEvent)

        self.core_checks['live_counterpart_declined'] = self.cli_worker.submit(reject)

    def _verify_declined_live(self) -> None:
        """Requires useful recovery in the same connection area after real refusal."""
        self._verify_live_failure('Live was declined. Try again or send a Drop.')
        self.capture('live-declined')

    def _disable_peer_route(self) -> None:
        """Makes only the explicitly controlled fixture route unreachable."""
        assert self.runtime.peer is not None
        self.runtime.peer.tor._fixture_running = False

    def _verify_failed_live(self) -> None:
        """Requires explicit recovery after actual loopback connection refusal."""
        try:
            self._verify_live_failure(
                'Live could not connect. Try again or send a Drop.'
            )
            self.capture('live-unreachable')
        finally:
            assert self.runtime.peer is not None
            self.runtime.peer.tor._fixture_running = True

    def _verify_live_failure(self, message: str) -> None:
        """Checks visible failure, enabled retry and usable DROP without duplicate toast."""
        peer = self.peer()
        assert peer is not None
        assert self.controller.live.failure(self.target) == message
        assert peer.subtitle.text == message
        retry = self.action('Retry Live', peer)
        assert retry is not None and not retry.disabled
        drop = self.action('DROP', peer)
        assert drop is not None and not drop.disabled
        assert not self.controller.state.feedback.visible()
        self.ux.peer_header()
        self.checks['live_failure_has_visible_recovery'] = True

    def _live_failure_visible(self) -> bool:
        """Waits for actual recovery controls after failure and authoritative reconciliation."""
        peer = self.peer()
        if peer is None:
            return False
        failure = self.controller.live.failure(self.target)
        retry = self.action('Retry Live', peer)
        return bool(
            failure
            and peer.subtitle.text == failure
            and retry is not None
            and not retry.disabled
        )

    def _switch_drop(self) -> None:
        """Arms a first-draw observation before actual native mode selection."""
        action = self.action('DROP', self.peer())
        assert action is not None
        self.ux.arm_drop(action)
        self.native.click(action)

    def _switch_live(self) -> None:
        """Observes the first opposite-mode draw after the real native tab activation."""
        action = self.action('LIVE', self.peer())
        assert action is not None
        self.ux.arm_live_tab(action)
        self.native.click(action)

    def _verify_feedback(self) -> None:
        """Observes the intentional rename confirmation within its content column."""
        self.ux.feedback_bounds()
        self.capture('contact-renamed')

    def _leave_peer_picker(self) -> None:
        """Checks private native-view revocation before returning to the root list."""
        self.ux.departed()
        self.click('Back')

    def _verify_notifications(self) -> None:
        """Checks native enlarged heading layout before leaving the notification page."""
        self.ux.secondary_header('Notifications')
        self.capture('notifications')
        self.click('Back')

    def _verify_settings(self) -> None:
        """Checks native enlarged heading layout before secondary navigation."""
        self.ux.secondary_header('Settings')
        self.capture('settings-heading')

    def _peer_pending(self) -> bool:
        """Observes the real counterpart request before explicit fixture acceptance."""
        if self.pending_snapshot is None:
            self.pending_snapshot = self.cli_worker.submit(self.remote.runtime_snapshot)
            return False
        if not self.pending_snapshot.done():
            return False
        snapshot = self.pending_snapshot.result()
        self.pending_snapshot = None
        return bool(
            snapshot
            and any(
                item.onion == self.runtime.onion and item.session_state == 'pending'
                for item in snapshot.live_contexts
            )
        )

    def _accept_live(self) -> None:
        """Acts as the explicitly consenting remote user through actual public IPC."""

        def accept() -> None:
            """Publishes explicit counterpart consent without running SDK on the GUI thread."""
            assert (
                self.remote.request(AcceptCommand(self.runtime.onion), ConnectedEvent)
                is not None
            )

        self.core_checks['live_counterpart_accepted'] = self.cli_worker.submit(accept)

    def _verify_live(self) -> None:
        """Checks peer receipt identity and unchanged explicit chat state."""
        events: list[MessageReceivedEvent] = self.args.peer_events
        assert len(events) == 1
        received = events[0]
        assert (
            isinstance(received.content, TextContent)
            and received.content.text == LIVE_TEXT
        )
        assert received.onion == self.runtime.onion and received.msg_id
        row = next(
            row
            for row in projection(self.controller, self.controller.state.route)
            if row.direction is MessageDirectionCode.OUT and row.text == LIVE_TEXT
        )
        assert row.msg_id == received.msg_id
        if row.timestamp:
            assert row.metadata.startswith(display_timestamp(row.timestamp) + ' · ')
        self.checks['live_same_gui_peer_message_identity'] = True
        self.checks['live_peer_received_once'] = True

    def _publish_live_reply(self) -> None:
        """Produces actual incoming LIVE content with Core's canonical timestamp."""

        def publish() -> None:
            """Sends through the consenting real counterpart SDK outside the UI thread."""
            assert (
                self.remote.request(
                    SendMessageCommand(
                        self.runtime.onion,
                        Delivery.LIVE,
                        TextContent(LIVE_REPLY),
                        'native-live-reply',
                        local_acceptance=True,
                    ),
                    TextAcceptedEvent,
                )
                is not None
            )

        self.core_checks['live_peer_reply_accepted'] = self.cli_worker.submit(publish)

    def _verify_live_timestamp(self) -> None:
        """Requires the received canonical time to appear once in the native LIVE card."""
        self.ux.peer_header()
        row = next(
            row
            for row in projection(self.controller, self.controller.state.route)
            if row.direction is MessageDirectionCode.IN and row.text == LIVE_REPLY
        )
        assert row.msg_id == 'native-live-reply' and row.timestamp
        assert row.metadata.startswith(display_timestamp(row.timestamp) + ' · ')
        widget = self.peer().timeline._widgets[row.key]
        assert widget._metadata.text == row.metadata
        self.checks['incoming_live_timestamp_visible_once'] = True
        self.capture('live-connected')

    def _open_audio_settings(self) -> None:
        """Keeps real enumeration pending until native Close input is actually pressed."""
        self.audio_probe.hold_scan()
        self.click('Go to audio settings')

    def _check_audio(self) -> None:
        """Verifies the closed dialog is inert and exposes deliberate configuration controls."""
        assert (
            self.controller.calls.current is None and not self.controller.calls.active
        )
        assert (
            not self.controller.voice.running and not self.controller.playback.running
        )
        assert self.action('Choose microphone') is not None
        assert self.action('Choose headphone output') is not None
        self.capture('audio-settings')

    def _rename_alias(self) -> TextField | None:
        """Resolves the actually laid-out form rather than an earlier route's search."""
        form = self.controller.contacts.form
        if not self.route('V13') or form is None or self.contact_list() is not None:
            return None
        fields = [
            item
            for item in self.scope().walk()
            if isinstance(item, TextField) and item.get_root_window() is not None
        ]
        address = next(
            (item for item in fields if item.readonly and item.text == form.raw), None
        )
        if address is None:
            return None
        raw_left, raw_bottom, raw_width, raw_height = rectangle(address)
        if not (
            raw_left >= 0
            and raw_bottom >= 0
            and raw_left + raw_width <= Window.width
            and raw_bottom + raw_height <= Window.height
        ):
            return None
        for item in fields:
            if item.readonly or item.text != form.alias:
                continue
            left, bottom, width, height = rectangle(item)
            if (
                left >= 0
                and bottom >= 0
                and left + width <= Window.width
                and bottom + height <= Window.height
                and bottom + height <= raw_bottom
                and width > 0
                and height > 0
            ):
                return item
        return None

    def _focus_alias(self) -> None:
        """Clicks the rendered form's exact alias without assigning native text."""
        alias = self._rename_alias()
        assert alias is not None
        self.native.click(alias)

    def _verify_alias(self) -> None:
        """Requires native and independent SDK views to agree on exact capitalization."""

        def verify() -> None:
            """Requires exact durable capitalization through an independent worker SDK."""
            snapshot = self.observer.runtime_snapshot()
            assert snapshot is not None
            assert (
                next(
                    item.alias
                    for item in snapshot.contacts
                    if item.onion == self.target
                )
                == FINAL_ALIAS
            )

        self.core_checks['contact_alias_durable_case'] = self.cli_worker.submit(verify)

    def _scroll_settings(self) -> None:
        """Uses native wheel input to reach the actual settings footer."""
        self.last_settings_scroll = time.monotonic()
        scroll = next(
            item
            for item in self.scope().walk()
            if isinstance(item, ScrollView)
            and self.action('Exit Metor', item) is not None
        )
        self.native.scroll(scroll, downward=True, steps=12)

    def _exit_reachable(self) -> bool:
        """Waits until the native scroll has made the actual Exit control visible."""
        action = self.action('Exit Metor')
        if action is None:
            return False
        current = rectangle(action)
        _left, bottom, _width, height = current
        scroll = next(
            item
            for item in self.scope().walk()
            if isinstance(item, ScrollView)
            and self.action('Exit Metor', item) is not None
        )
        _, lower, _, viewport_height = rectangle(scroll)
        visible = (
            bottom >= lower - GEOMETRY_TOLERANCE
            and bottom + height <= lower + viewport_height + GEOMETRY_TOLERANCE
        )
        if (
            not visible
            and not self.native._wheel
            and time.monotonic() - self.last_settings_scroll > 0.4
        ):
            self._scroll_settings()
        previous = getattr(self, 'exit_geometry', None)
        if previous is None or any(
            abs(before - after) > GEOMETRY_TOLERANCE
            for before, after in zip(previous, current, strict=True)
        ):
            self.exit_geometry = current
            self.exit_geometry_since = time.monotonic()
            return False
        ready = (
            visible
            and not self.native._wheel
            and time.monotonic() - self.exit_geometry_since > INPUT_SETTLE_SECONDS
        )
        if ready:
            self.ux.records['settings_exit_geometry'] = {
                'action': current,
                'viewport': rectangle(scroll),
                'native_wheel_queue_empty': True,
                'stability_tolerance_pixels': GEOMETRY_TOLERANCE,
            }
        return ready

    def _exit(self) -> None:
        """Closes through the actual user action and production lifecycle transaction."""
        self.capture('settings')
        self.exit_selected = True
        self.click('Exit Metor')

    def evidence(self) -> dict[str, object]:
        """Returns bounded synthetic-fixture evidence with explicit capability limits."""
        return {
            'kind': 'native_gui_core_e2e',
            'mode': self.args.mode,
            'revision_or_tree': self.args.revision,
            'platform': platform.platform(),
            'python': platform.python_version(),
            'gui_module': str(
                Path(sys.modules[MetorApp.__module__].__file__).resolve()
            ),
            'window_provider': Window.__class__.__module__,
            'native_os_input': 'X11 XTest through SDL2',
            'actual_core_ipc': True,
            'actual_sqlcipher': True,
            'actual_peer_framing': True,
            'controlled_core_start_scheduling': 'First actual Connect handler waits for a native draw and duplicate tap; original operation then resumes unchanged',
            'controlled_transport': 'Tor process and SOCKS replaced by bounded loopback TCP',
            'physical_input': False,
            'physical_audio': False,
            'native_os_lifecycle': False,
            'lifecycle_fixture': 'No logind provider on virtual acceptance display',
            'public_tor': False,
            'viewport': [self.args.width, self.args.height],
            'font_scale': self.args.font_scale,
            'native_input_events': self.native.events,
            'checks': self.checks,
            'first_draw_and_layout': self.ux.records,
            'native_audio_dismissal': self.audio_probe.records,
            'controlled_audio_scan_scheduling': 'The actual native endpoint value or exception is held until XTest presses Close; release follows the first reconciled scan draw',
            'first_draw_timing_method': 'Native OS-dispatched action release to first Window.on_flip; canvas_draw_ms spans on_draw to on_flip. No polling or settlement delay is added; these virtual-display observations are not a hardware latency guarantee.',
            'step_latency': distribution(self.timings),
            'action_confirmation_ms': self.confirmation_timings,
            'timing_method': 'Monotonic action-to-observation; 50 ms polling and 150 ms native input settlement; no hardware latency claim',
            'redraw_intervals': distribution(self.frames),
            'redraw_method': 'Window on_flip dispatches only when canvas.needs_redraw; long idle gaps are not scheduler stalls',
            'scheduler_ticks': distribution([dt for _, dt in self.scheduler_samples]),
            'interactive_scheduler_ticks': distribution(
                [
                    dt
                    for phase, dt in self.scheduler_samples
                    if phase.startswith(('drop_', 'background_', 'live_'))
                ]
            ),
            'slowest_scheduler_ticks': [
                {'phase': phase, 'ms': round(dt * 1000, 3)}
                for phase, dt in sorted(
                    self.scheduler_samples, key=lambda sample: sample[1], reverse=True
                )[:8]
            ],
            'fixture_screenshot_ms': self.fixture_costs,
            'feedback_duration_seconds': GuiLimits.FEEDBACK_SECONDS,
            'images': self.images,
        }


def main() -> None:
    """Runs one isolated real GUI/Core acceptance and requires bounded full cleanup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('source', 'installed'), default='source')
    parser.add_argument('--width', type=int, default=360)
    parser.add_argument('--height', type=int, default=640)
    parser.add_argument('--font-scale', type=float, default=1.5)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    args = parser.parse_args()
    module_file = sys.modules[MetorApp.__module__].__file__
    assert module_file is not None
    verify_gui_module_origin(
        module_file,
        mode=args.mode,
        checkout=Path(__file__).resolve().parents[1],
        environment_root=Path(sys.prefix),
    )
    assert Window.__class__.__module__.endswith('window_sdl2'), 'SDL2 is required'
    assert os.environ.get('SDL_VIDEODRIVER') == 'x11', 'Native X11 is required'
    Metrics.fontscale = args.font_scale
    evidence: dict[str, object]
    with (
        EncryptedFrontendRuntime() as runtime,
        patch(
            'metor.ui.gui.app.create_desktop_lifecycle_source',
            return_value=None,
        ),
    ):
        assert runtime.peer is not None
        args.peer_events = []

        def received(event: IpcEvent) -> None:
            """Observes only the expected ephemeral LIVE text from the actual remote SDK."""
            if (
                isinstance(event, MessageReceivedEvent)
                and event.delivery is Delivery.LIVE
            ):
                args.peer_events.append(event)

        observer, peer = (
            runtime.client(),
            runtime.peer.client(live_consumer=True, on_event=received),
        )
        assert (
            observer.request(
                AddContactCommand(INITIAL_ALIAS, runtime.peer.onion), ContactAddedEvent
            )
            is not None
        )
        assert (
            observer.request(
                SendMessageCommand(
                    runtime.peer.onion,
                    Delivery.DROP,
                    TextContent('Existing Drop'),
                    'native-seed',
                ),
                DropQueuedEvent,
            )
            is not None
        )
        app = NativeCoreApp(runtime, observer, peer, args)
        try:
            app.run()
            if app.failure is not None:
                raise app.failure
            assert (
                app.exit_selected
                and not app.steps
                and app.controller.lifecycle.exit_ready
            ), 'The actual GUI did not detach cleanly'
            evidence = app.evidence()
            for text in DROP_TEXTS:
                rows = app.archive(peer, runtime.onion).messages
                assert (
                    sum(
                        isinstance(row.content, TextContent)
                        and row.content.text == text
                        for row in rows
                    )
                    == 1
                ), 'Remote DROP persistence differs from native sends'
            assert observer.is_connected and observer.runtime_snapshot() is not None, (
                'Closing GUI affected the independent client'
            )
            evidence['cleanup'] = {
                'gui_detached': True,
                'independent_client_usable': True,
            }
        finally:
            Window.unbind(on_flip=app._frame)
            Clock.unschedule(app._heartbeat)
            app.on_stop()
            app.ux.close()
            app.live_stop_probe.close()
            app.audio_probe.close()
            app.native.close()
            app.cli_worker.shutdown(wait=True, cancel_futures=True)
            app.terminal.close()
    evidence['temporary_core_cleanup'] = True
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(
        json.dumps(
            {
                'result': str(args.result.resolve()),
                'checks': len(app.checks),
                'native_input_events': app.native.events,
                'cleanup': True,
            }
        )
    )


if __name__ == '__main__':
    main()
