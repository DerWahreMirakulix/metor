"""Captures synthetic native Kivy fixtures without any real profile or device IO.

Run explicitly with the installed GUI interpreter outside the source tree.
This is native renderer evidence, not physical input/audio or Core acceptance.
"""

import argparse
import json
import os
import platform
import string
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

import psutil

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

# SDL's offscreen drawable must be sized before its first native window exists.
geometry_parser = argparse.ArgumentParser(add_help=False)
geometry_parser.add_argument('--width', type=int, default=480)
geometry_parser.add_argument('--height', type=int, default=800)
initial_geometry, _remaining_arguments = geometry_parser.parse_known_args()
Config.set('graphics', 'width', str(initial_geometry.width))
Config.set('graphics', 'height', str(initial_geometry.height + 24))

from gui_native_contacts import configure_contact_pages, exercise_contact_pages
from gui_native_history import configure_history, exercise_history
from gui_native_live_controls import exercise_live_controls
from gui_native_load import exercise_native_load
from gui_native_profiles import (
    configure_profiles,
    exercise_profile_address,
    exercise_profile_editor,
)
from gui_native_purge import configure_purge
from gui_native_render import capture_viewport
from gui_native_responsive import exercise_responsive
from gui_native_root import exercise_root_navigation, exercise_root_refresh
from gui_native_settings import exercise_setting_editor, exercise_setting_keyboard
from gui_native_timeout import exercise_timeout
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.clipboard.clipboard_dummy import ClipboardDummy
from kivy.core.window import Window
from kivy.graphics import Rectangle
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import Metrics, dp
from kivy.uix.scrollview import ScrollView

from metor.client import FrontendHost, FrontendLaunchContext
from metor.core.api import (
    ClientRestrictedEvent,
    ClientUnlockMethod,
    ConnectionOrigin,
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    GuiPreferencesEvent,
    IncomingConnectionEvent,
    LiveContextEntry,
    MessageDirectionCode,
    MessageEntry,
    MessagesDataEvent,
    MessageStatusCode,
    NotificationPrivacy,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    RuntimeSnapshotEvent,
    TextContent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime.device import DevicePhase
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.runtime.voice.controller import VoiceReview
from metor.ui.gui.runtime.voice.press import CaptureBinding
from metor.ui.gui.state import Route
from metor.ui.gui.views.contacts.panel import contact_sheet
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField
from metor.ui.gui.widgets.keyboard import KeyboardKey
from metor.ui.gui.widgets.qr import ContactQr
from metor.ui.gui.widgets.sheet import ActionSheet, confirm


def assert_qr_visible(app: MetorApp) -> None:
    """Checks the QR, centered address, copy action, and native viewport fit.

    Args:
        app: Running isolated native fixture application.
    Returns:
        None
    """
    assert app.shell is not None
    qr = next(widget for widget in app.shell.walk() if isinstance(widget, ContactQr))
    scroll = qr.parent.parent
    assert isinstance(scroll, ScrollView)
    canvas = qr.canvas
    assert canvas is not None
    rectangles = [item for item in canvas.children if isinstance(item, Rectangle)]
    square = max(rectangles, key=lambda item: item.size[0] * item.size[1])
    count = len(qr.modules)
    assert square.size[0] == square.size[1] and square.size[0] >= count
    assert all(not any(row[:4]) and not any(row[-4:]) for row in qr.modules)
    assert all(not any(row) for row in qr.modules[:4] + qr.modules[-4:])
    left, bottom = qr.to_window(*square.pos)
    right, top = left + square.size[0], bottom + square.size[1]
    viewport_left, viewport_bottom = scroll.to_window(*scroll.pos)
    viewport_right = viewport_left + scroll.width
    viewport_top = viewport_bottom + scroll.height
    assert (
        viewport_left <= left < right <= viewport_right
        and viewport_bottom <= bottom < top <= viewport_top
    ), (
        f'Contact QR clipped: square={(left, bottom, right, top)}, '
        f'viewport={(viewport_left, viewport_bottom, viewport_right, viewport_top)}, '
        f'widget={qr.pos + qr.size}'
    )
    snapshot = app.controller.state.snapshot
    assert snapshot is not None
    address = next(
        widget
        for widget in qr.parent.children
        if isinstance(widget, Label) and widget.text == snapshot.onion
    )
    assert address.halign == 'center'
    assert abs(address.center_x - (square.pos[0] + square.size[0] / 2)) <= dp(1)
    assert square.pos[1] - address.top >= dp(20), (
        f'Contact address too close to QR: square_bottom={square.pos[1]}, '
        f'address_top={address.top}'
    )
    copy_action = next(
        widget
        for widget in app.shell.walk()
        if isinstance(widget, Action)
        and widget.accessible_name in {'Copy address', 'Copy unavailable'}
    )
    assert copy_action.disabled == isinstance(Clipboard, ClipboardDummy)
    assert copy_action.accessible_name == (
        'Copy unavailable' if copy_action.disabled else 'Copy address'
    )
    assert copy_action.opacity > 0
    assert copy_action.get_root_window() is not None
    assert copy_action.height >= dp(48)


def assert_qr_copy_action(app: MetorApp) -> None:
    """Exercises the explicit copy and refuses a stale native action after departure."""
    assert app.shell is not None
    snapshot = app.controller.state.snapshot
    assert snapshot is not None
    action = next(
        widget
        for widget in app.shell.walk()
        if isinstance(widget, Action)
        and widget.accessible_name in {'Copy address', 'Copy unavailable'}
    )
    if action.disabled:
        return
    with patch('metor.ui.gui.views.contacts.panel.Clipboard') as clipboard:
        clipboard.paste.return_value = snapshot.onion
        action.dispatch('on_release')
        clipboard.copy.assert_called_once_with(snapshot.onion)
        clipboard.paste.assert_called_once_with()
        assert action.accessible_name == 'Address copied'
        clipboard.copy.reset_mock()
        clipboard.copy.side_effect = RuntimeError('provider failure')
        action.dispatch('on_release')
        assert action.accessible_name == 'Copy unavailable'
        clipboard.copy.reset_mock(side_effect=True)
        clipboard.paste.return_value = ''
        action.dispatch('on_release')
        assert action.accessible_name == 'Copy unavailable'
        clipboard.copy.reset_mock()
        app.controller.state.covered = True
        action.dispatch('on_release')
        app.controller.state.covered = False
        app.controller.state.route = Route('V12')
        action.dispatch('on_release')
        app.controller.state.route = Route('V15')
        app.controller.state.generation += 1
        action.dispatch('on_release')
        clipboard.copy.assert_not_called()


def assert_qr_resize(onion: str) -> None:
    """Checks drawing during a size callback, when cached centers may lag.

    Args:
        onion: Valid fixture contact address.
    Returns:
        None
    """
    qr = ContactQr(onion)
    qr.pos = (dp(17), dp(23))
    qr.width = dp(500)
    canvas = qr.canvas
    assert canvas is not None
    square = max(
        (item for item in canvas.children if isinstance(item, Rectangle)),
        key=lambda item: item.size[0] * item.size[1],
    )
    assert square.pos[0] == round(qr.x + (qr.width - square.size[0]) / 2)
    assert square.pos[1] == round(qr.y + (qr.height - square.size[1]) / 2)


def exercise_keyboard(app: MetorApp) -> None:
    """Checks real native widgets using synthetic key and focus events.

    Args:
        app: Running isolated native fixture application.
    Returns:
        None
    """
    activations: list[bool] = []
    action = Action('Input probe', lambda: activations.append(True))
    assert app.shell is not None
    app.shell.add_widget(action)
    action.focus = True
    action.keyboard_on_key_down(Window, (13, 'enter'), '', [])
    action.keyboard_on_key_down(Window, (13, 'enter'), '', [])
    action.keyboard_on_key_up(Window, (13, 'enter'))
    action.keyboard_on_key_up(Window, (13, 'enter'))
    assert activations == [True], 'Repeated key input activated more than once'
    action.keyboard_on_key_down(Window, (13, 'enter'), '', [])
    action.focus = False
    action.keyboard_on_key_up(Window, (13, 'enter'))
    assert activations == [True], 'Lost focus retained an armed activation'
    app.shell.remove_widget(action)


def exercise_local_keyboard(app: MetorApp, complete: Callable[[], None]) -> None:
    """Edits masked fields through native key widgets across actual layout frames.

    Args:
        app: Running native synthetic application with an open keyboard.
        complete: Called after editing checks and original-field restoration.
    Returns:
        None
    """
    dock = app.input_dock
    assert dock is not None and dock.keyboard is not None and app.shell is not None
    original = dock.target
    secret = SecretInput()
    app.shell.add_widget(secret)
    dock.show(secret)
    keyboard = dock.keyboard
    assert keyboard is not None
    observed: set[str] = set()

    def check(condition: bool) -> None:
        assert condition, 'Native keyboard editing contract failed'

    def press(label: str) -> None:
        key = next(
            widget
            for widget in keyboard.walk()
            if isinstance(widget, KeyboardKey) and widget.label.text == label
        )
        key.dispatch('on_release')

    def labels() -> None:
        observed.update(
            key.label.text for key in keyboard.walk() if isinstance(key, KeyboardKey)
        )

    def qwertz() -> None:
        keyboard.configure(layout='qwertz', pin=False)
        rows = [
            [key.label.text for key in reversed(row.children)]
            for row in reversed(keyboard.rows.children)
        ]
        assert 'z' in rows[0] and 'y' not in rows[0] and 'y' in rows[2]

    def pin() -> None:
        secret.input_purpose = 'pin'
        dock.show(secret)
        assert keyboard.pin

    def finish() -> None:
        secret.text = ''
        dock.hide()
        assert dock.target is None and dock.keyboard is None
        assert app.shell is not None
        app.shell.remove_widget(secret)
        assert original is not None
        dock.show(original)
        complete()

    steps = iter(
        [
            lambda: press('q'),
            lambda: press('⇧'),
            lambda: press('W'),
            lambda: check(secret.text == 'qW' and not keyboard.shift),
            lambda: press('⇧'),
            lambda: press('⇧'),
            lambda: check(keyboard.caps),
            lambda: press('E'),
            lambda: check(keyboard.caps and secret.text == 'qWE'),
            lambda: press('⇧'),
            qwertz,
            lambda: press('123'),
            labels,
            lambda: press('#+='),
            labels,
            lambda: check(set(string.digits + string.punctuation) <= observed),
            pin,
            lambda: press('1'),
            lambda: press('2'),
            lambda: check(secret.password and secret.text.endswith('12')),
            lambda: press('⌫'),
            lambda: check(secret.text.endswith('1') and secret.focus),
            finish,
        ]
    )

    def advance(_elapsed: float) -> None:
        action = next(steps, None)
        if action is not None:
            action()
            Clock.schedule_once(advance, 0.05)

    Clock.schedule_once(advance, 0.1)


def exercise_peer_input(app: MetorApp) -> None:
    """Exercises native key dispatch and repaint stability without opening a microphone.

    Args:
        app: Running synthetic peer fixture.
    Returns:
        None
    """
    assert app.shell is not None
    peer = next(
        (widget for widget in app.shell.walk() if isinstance(widget, PeerView)), None
    )
    if peer is None:
        return
    entry, ptt = peer.composer.entry, peer.composer.ptt
    if peer.composer._mode == 'review':
        return
    original_status = app.controller.state.status
    with (
        patch.object(app.controller.voice, 'available', return_value=True),
        patch.object(app.controller.voice, 'headset_confirmed', True),
        patch.object(app.controller.voice, 'down', return_value=False) as down,
    ):
        app.shell.render()
        peer.composer.bar.do_layout()
        ptt.disabled = False
        ptt.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert down.call_count == 0, 'Enter incorrectly initiated PTT capture'
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        assert down.call_count == 1, 'Native repeated key press changed PTT ownership'
        for number in range(5):
            app.controller.state.status = f'Fixture update {number}'
            app.shell.render()
            current = next(
                widget for widget in app.shell.walk() if isinstance(widget, PeerView)
            )
            assert (
                current is peer
                and current.composer.entry is entry
                and current.composer.ptt is ptt
            )
            assert ptt.focus, 'Background repaint stole PTT keyboard focus'
        ptt.focus = False
        Window.dispatch('on_key_up', 32, 44)
        assert not app.controller.inputs._held, (
            'Key release did not reach original input owner'
        )
        entry.focus = True
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        entry.focus = False
        ptt.focus = True
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        assert down.call_count == 1, 'A held key was adopted after focus moved to PTT'
        Window.dispatch('on_key_up', 32, 44)
        ptt.focus = False
        touch = MouseMotionEvent(
            'mouse',
            'fixture-one',
            (ptt.center_x / Window.width, ptt.center_y / Window.height, 'left'),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        Window.dispatch('on_touch_down', touch)
        assert down.call_count == 2, 'Pointer down did not reach the PTT target'
        second = MouseMotionEvent(
            'mouse', 'fixture-two', (touch.sx, touch.sy, 'left'), is_touch=True
        )
        second.scale_for_screen(Window.width, Window.height)
        Window.dispatch('on_touch_down', second)
        Window.dispatch('on_touch_up', second)
        assert down.call_count == 2 and app.controller.inputs._held, (
            'A second pointer stole or released PTT ownership'
        )
        touch.move((-0.1, -0.1, 'left'))
        touch.scale_for_screen(Window.width, Window.height)
        Window.dispatch('on_touch_up', touch)
        assert not app.controller.inputs._held, 'Release outside the target was lost'
    app.controller.state.status = original_status
    app.controller.state.drafts.clear()
    app.shell.render()


def exercise_timeline(app: MetorApp) -> None:
    """Checks page bounds and preservation of an older reading anchor on arrival.

    Args:
        app: Native fixture with bounded synthetic history.
    Returns:
        None
    """
    assert app.shell is not None
    peer = next(
        (widget for widget in app.shell.walk() if isinstance(widget, PeerView)), None
    )
    if peer is None or len(app.controller.transcript.items) < 128:
        return
    timeline = peer.timeline
    assert len(timeline._widgets) == 64
    timeline._older()
    app.shell.render()
    anchor = timeline._visible[-1]
    app.controller.transcript.admit(
        TranscriptItem(
            'rhea',
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'late-item',
            text='A new item while reading older messages.',
        )
    )
    app.shell.render()
    assert timeline._visible[-1] == anchor, 'Arrival moved the older reading page'
    assert timeline._new_count == 1 and len(timeline._widgets) == 64
    timeline._jump()
    app.shell.render()
    assert timeline._visible[-1][1] == 'late-item' and len(timeline._widgets) == 64


def exercise_root_pages(app: MetorApp) -> None:
    """Checks that native pagination bounds widgets and keeps canonical row navigation.

    Args:
        app: Running isolated root fixture with 130 canonical summaries.
    Returns:
        None
    """
    from metor.ui.gui.widgets.context import ContextAction

    assert app.shell is not None
    controller = app.controller
    snapshot = controller.state.snapshot
    if (
        controller.state.route.view != 'V06'
        or snapshot is None
        or len(snapshot.conversations) != 130
    ):
        return
    selector = next(
        widget
        for widget in app.shell.walk()
        if isinstance(widget, Action) and widget.focus_key == ('selector', 'DROP')
    )
    selector.focus = True
    Window.dispatch('on_key_down', 275, 79, '', [])
    Window.dispatch('on_key_up', 275, 79)
    assert selector.focus_group[1].focus
    assert controller.state.root_delivery is Delivery.DROP
    assert controller.state.route.view == 'V06'
    for page, expected in ((0, 64), (1, 64), (2, 2)):
        controller.state.root_pages[Delivery.DROP] = page
        app.shell.render()
        rows = [
            widget
            for widget in app.shell.walk()
            if isinstance(widget, ContextAction) and widget.context is not None
        ]
        assert len(rows) == expected, 'Root instantiated an unbounded or missing page'
        assert controller.state.route.view == 'V06'
        first = rows[0].focus_group[0]
        second = rows[0].focus_group[1]
        first.focus = True
        Window.dispatch('on_key_down', 274, 81, '', [])
        Window.dispatch('on_key_up', 274, 81)
        assert second.focus and controller.state.route.view == 'V06'
        Window.dispatch('on_key_down', 273, 82, '', [])
        Window.dispatch('on_key_up', 273, 82)
        assert first.focus
    last = next(
        widget
        for widget in app.shell.walk()
        if isinstance(widget, ContextAction) and widget.context is not None
    )
    last.dispatch('on_release')
    assert controller.state.route.view == 'V08'
    assert controller.state.route.peer in {'peer-128', 'peer-129'}
    controller.back()
    app.shell.render()
    assert controller.state.root_pages[Delivery.DROP] == 2


def main() -> None:
    """Renders one native fixture and records the actual process environment.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--window-output', type=str)
    parser.add_argument('--width', type=int, default=480)
    parser.add_argument('--height', type=int, default=800)
    parser.add_argument('--font-scale', type=float, default=1.0)
    parser.add_argument(
        '--view',
        choices=(
            'root',
            'root_page',
            'root_refresh',
            'root_navigation',
            'root_load',
            'drop',
            'live',
            'entry',
            'entry_loading',
            'failure',
            'setup',
            'lock',
            'settings',
            'setting_editor',
            'setting_keyboard',
            'timeout_editor',
            'profiles',
            'profile_editor',
            'profile_address',
            'history',
            'voice',
            'review',
            'review_live',
            'large',
            'responsive',
            'keyboard',
            'contacts',
            'contact_pages',
            'contact_form',
            'contact_sheet',
            'confirmation',
            'incoming',
            'locked_notice',
            'qr',
            'notifications',
            'notification_selection',
            'context_menu',
            'device_power',
            'device_purge',
            'purge',
            'purge_key',
            'purge_safe',
            'purge_complete',
            'purge_failed',
            'purge_unknown',
        ),
        default='root',
    )
    args = parser.parse_args()
    Metrics.fontscale = args.font_scale
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = DeviceConfiguration(
        mode='simulator',
        width_px=args.width,
        height_px=args.height,
        touch=args.view == 'setting_keyboard',
        clipboard_own_address=True,
    )
    host = cast(FrontendHost, object())
    app = MetorApp(FrontendLaunchContext('Simulator', host), config)
    controller = app.controller
    controller.open_profile()
    controller.state.snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        profile_instance_id='synthetic-instance',
        contacts=[ContactEntry('Rhea', 'rhea'), ContactEntry('Orion', 'orion')],
        conversations=[
            DropConversationSummaryEntry('Rhea', 'rhea', 2),
            DropConversationSummaryEntry('Orion', 'orion'),
        ],
        live_contexts=[LiveContextEntry('Rhea', 'rhea', True, 'connected')],
    )
    if args.view in {'root_page', 'root_refresh', 'root_load'}:
        controller.state.snapshot.conversations = [
            DropConversationSummaryEntry(
                f'Peer {index:03d}', f'peer-{index}', index % 5, index % 3
            )
            for index in range(130)
        ]
    if args.view in {'notifications', 'notification_selection', 'context_menu'}:
        controller.state.snapshot.live_contexts = [
            LiveContextEntry('Rhea', 'rhea', True, 'connected', unseen_count=3),
            LiveContextEntry(
                'Orion', 'orion', True, 'disconnected', pending_outbound_count=2
            ),
        ]
        controller.state.snapshot.pending = [
            PendingConnectionEntry(
                'Lyra',
                'lyra',
                ConnectionOrigin.INCOMING,
                PendingConnectionReasonCode.USER_ACCEPT,
            )
        ]
        controller.state.route = Route('V16')
        controller.notifications.poll()
        if args.view == 'notification_selection':
            controller.notifications.store.selecting = True
            controller.notifications.store.selected.add(
                next(iter(controller.notifications.store.items))
            )
        if args.view == 'context_menu':

            def open_context(_elapsed: float) -> None:
                """Opens the real focused row's More menu through native Shift+F10.

                Args:
                    _elapsed: Native scheduling delay.
                Returns:
                    None
                """
                from metor.ui.gui.widgets.context import ContextAction

                assert app.shell is not None
                row = next(
                    (
                        widget
                        for widget in app.shell.walk()
                        if isinstance(widget, ContextAction)
                        and widget.context is not None
                    ),
                    None,
                )
                if row is None:
                    assert time.monotonic() - started < 30, (
                        'Context row did not become ready'
                    )
                    Clock.schedule_once(open_context, 0.1)
                    return
                row.focus = True
                Window.dispatch('on_key_down', 291, 67, '', ['shift'])
                Window.dispatch('on_key_up', 291, 67)
                assert ActionSheet.current is not None
                assert ActionSheet.current.width <= dp(320)
                assert controller.state.route.view == 'V16'

            Clock.schedule_once(open_context, 0.5)
    confirmed_actions: list[bool] = []
    if args.view.startswith('purge'):
        configure_purge(controller, args.view)
    if args.view == 'device_power':
        controller.device.phase = DevicePhase.POWER_MENU
        controller.device.title = 'Power off'
        controller.device.detail = (
            'Prepare local state before powering off this device?'
        )
        controller.state.covered = True
        controller.state.route = Route('V21')
    elif args.view == 'device_purge':
        controller.device.phase = DevicePhase.PURGE_ARMING
        controller.device.title = 'Hold both buttons'
        controller.device.detail = 'Keep holding Power and PTT'
        controller.device.progress = 0.6
        controller.state.covered = True
        controller.state.route = Route('V22')

    def show_confirmation(_elapsed: float = 0) -> None:
        confirm(
            controller,
            'Remove contact',
            'Remove this saved contact. Retained conversations and active communication may remain.',
            lambda: confirmed_actions.append(True),
        )

    if args.view == 'confirmation':
        controller.state.route = Route('V12')
        Clock.schedule_once(show_confirmation, 0.5)
    if args.view == 'contact_pages':
        configure_contact_pages(controller)
    if args.view in {'contacts', 'contact_form', 'contact_sheet', 'qr'}:
        controller.state.route = Route('V12' if args.view != 'qr' else 'V15')
        if args.view == 'contact_form':
            controller.contacts.begin('live')
            form = controller.contacts.form
            assert form is not None
            form.raw = 'gqncaw2sjprzovtdquir4etnswg2eyvomid4bsbdld2p5roay5vmvtyd.onion'
            form.alias = 'Rhea'
        if args.view == 'qr':
            controller.state.snapshot.onion = (
                'gqncaw2sjprzovtdquir4etnswg2eyvomid4bsbdld2p5roay5vmvtyd.onion'
            )
        if args.view == 'contact_sheet':
            Clock.schedule_once(
                lambda _elapsed: contact_sheet(controller, 'rhea', app.refresh), 0.5
            )
    if args.view in (
        'drop',
        'live',
        'voice',
        'review',
        'review_live',
        'large',
        'keyboard',
        'responsive',
    ):
        delivery = Delivery.DROP if args.view in ('drop', 'review') else Delivery.LIVE
        controller.state.route = Route(
            'V08' if delivery is Delivery.DROP else 'V09', 'rhea', delivery
        )
        controller.messages = MessagesDataEvent(
            [
                MessageEntry(
                    MessageDirectionCode.IN,
                    MessageStatusCode.READ,
                    delivery,
                    TextContent('I can hear you.'),
                    '18:42',
                    'one',
                ),
                MessageEntry(
                    MessageDirectionCode.OUT,
                    MessageStatusCode.DELIVERED,
                    delivery,
                    TextContent('Ready. Let me know when you reach the meeting point.'),
                    '18:42',
                    'two',
                ),
            ],
            'Rhea',
            'rhea',
        )
        if args.view == 'voice':
            controller.transcript.admit(
                TranscriptItem(
                    'rhea',
                    Delivery.LIVE,
                    MessageDirectionCode.IN,
                    'incoming-voice',
                    codec=PcmVoice.CODEC,
                    size_bytes=64000,
                )
            )
        if args.view in {'large', 'responsive'}:
            for number in range(160):
                controller.transcript.admit(
                    TranscriptItem(
                        'rhea',
                        Delivery.LIVE,
                        MessageDirectionCode.IN,
                        f'large-{number}',
                        text=f'Fixture message {number}',
                    )
                )
        if args.view in {'review', 'review_live'}:
            controller.state.snapshot.live_contexts[0].context_generation = 7
            binding = CaptureBinding(
                'synthetic-instance',
                'simulator',
                controller.state.generation,
                'rhea',
                delivery,
                'review',
                7 if delivery is Delivery.LIVE else None,
            )
            controller.voice.reviews['rhea'] = VoiceReview(binding, 32000, 1000)
    elif args.view in {'profiles', 'profile_editor', 'profile_address'}:
        configure_profiles(controller)
    elif args.view == 'history':
        configure_history(controller)
    elif args.view in (
        'setup',
        'lock',
        'settings',
        'setting_editor',
        'setting_keyboard',
        'timeout_editor',
    ):
        controller.state.preferences = GuiPreferencesEvent('synthetic-instance')
        controller.state.route = Route(
            {
                'setup': 'V04',
                'lock': 'V05',
                'settings': 'V17',
                'setting_editor': 'V17',
                'setting_keyboard': 'V17',
                'timeout_editor': 'V17',
            }[args.view]
        )
        if args.view == 'lock':
            controller.state.covered = True
            controller.state.snapshot = None
            controller.state.preferences = None
            controller.security.restriction = ClientRestrictedEvent(
                ClientUnlockMethod.PIN, '11' * 32, '22' * 16
            )
    elif args.view in {'entry', 'entry_loading'}:
        controller.state.covered = True
        controller.state.route = Route('V01')
        if args.view == 'entry_loading':
            controller.state.busy = True
            controller.state.status = 'Opening profile…'
    elif args.view == 'failure':
        controller.state.covered = True
        controller.state.status = 'Could not open profile. Retry or choose a profile.'

    call_focus: list[TextField] = []
    if args.view in {
        'locked_notice',
    }:
        controller.state.covered = True
        controller.state.route = Route('V05')
        controller.state.snapshot = None
        controller.state.preferences = None
        controller.security.restriction = ClientRestrictedEvent(
            ClientUnlockMethod.PIN
            if args.view == 'locked_notice'
            else ClientUnlockMethod.NONE,
            '11' * 32,
            '22' * 16,
        )
        controller.security._policy = replace(
            controller.security._policy,
            notifications_locked=NotificationPrivacy.ANONYMIZE
            if args.view == 'locked_notice'
            else NotificationPrivacy.OFF,
        )

        def receive_notice(_elapsed: float) -> None:
            """Receives anonymous metadata while a real masked PIN field retains focus.

            Args:
                _elapsed: Native scheduler delay.
            Returns:
                None
            """
            from metor.core.api import InboxNotificationEvent

            assert app.shell is not None
            field = next(
                (
                    widget
                    for widget in app.shell.walk()
                    if isinstance(widget, SecretInput)
                ),
                None,
            )
            if field is None:
                assert time.monotonic() - started < 30, (
                    'Locked PIN field did not become ready'
                )
                Clock.schedule_once(receive_notice, 0.1)
                return
            field.focus = True
            call_focus.append(field)
            controller.notifications.observe(
                InboxNotificationEvent('unknown', delivery=Delivery.DROP)
            )
            app.refresh()

        Clock.schedule_once(receive_notice, 0.5)
    if args.view in {'incoming'}:
        controller.state.route = Route('V08', 'rhea', Delivery.DROP)
        controller.state.covered = False

        def show_calls(_elapsed: float) -> None:
            """Publishes no-preview call metadata after the underlying view has focus."""
            assert app.shell is not None
            fields = [
                field for field in app.shell.walk() if isinstance(field, TextField)
            ]
            if fields:
                fields[0].text = 'Draft stays here'
                fields[0].focus = True
                call_focus.append(fields[0])
            assert controller.state.snapshot is not None
            controller.state.snapshot.pending = [
                PendingConnectionEntry(
                    name,
                    peer,
                    ConnectionOrigin.INCOMING,
                    PendingConnectionReasonCode.USER_ACCEPT,
                    action_handle=handle,
                )
                for name, peer, handle in [
                    ('Orion', 'orion', 'first'),
                    ('Lyra', 'lyra', 'second'),
                ]
            ]
            with patch.object(controller.voice, 'depart') as depart:
                controller.live_invitations.observe(
                    IncomingConnectionEvent('Orion', 'orion', 'first')
                )
                controller.live_invitations.observe(
                    IncomingConnectionEvent('Lyra', 'lyra', 'second')
                )
                assert depart.call_count == 0
            app.refresh()

        Clock.schedule_once(show_calls, 0.5)

    started = time.monotonic()
    local_keyboard_checked = 0
    settled_frames = 0
    confirmation_checked = False
    native_probes_done = False

    def open_keyboard(_elapsed: float) -> None:
        """Shows the explicit dock in a native minimum-size fixture.

        Args:
            _elapsed: Native layout scheduler interval.
        Returns:
            None
        """
        assert app.shell is not None and app.input_dock is not None
        peer = next(
            (widget for widget in app.shell.walk() if isinstance(widget, PeerView)),
            None,
        )
        if peer is None:
            Clock.schedule_once(open_keyboard, 0.1)
            return
        app.input_dock.show(peer.composer.entry)

    def capture(_elapsed: float) -> None:
        """Exports only the inner viewport and safe process statistics.

        Args:
            _elapsed: Native scheduler interval.
        Returns:
            None
        """
        nonlocal \
            local_keyboard_checked, \
            settled_frames, \
            confirmation_checked, \
            native_probes_done
        assert app.shell is not None
        expected = (dp(args.width), dp(args.height))
        assert app.viewport is not None
        unsettled = tuple(app.viewport.size) != expected or (
            args.view == 'keyboard' and app.shell.height != dp(args.height - 264)
        )
        if unsettled:
            if time.monotonic() - started > 30:
                raise AssertionError(
                    f'Native viewport did not settle: {app.shell.size}, expected {expected}'
                )
            Clock.schedule_once(capture, 0.1)
            return
        if settled_frames < 3:
            settled_frames += 1
            Clock.schedule_once(capture, 0.1)
            return
        if args.view in {
            'incoming',
            'locked_notice',
            'context_menu',
            'device_power',
            'device_purge',
        }:
            pass
        elif args.view != 'keyboard':
            if not native_probes_done:
                if args.view not in {'contact_sheet', 'confirmation'}:
                    exercise_keyboard(app)
                exercise_peer_input(app)
                exercise_live_controls(app)
                exercise_timeline(app)
                exercise_root_pages(app)
                native_probes_done = True
                if args.view == 'root_load':
                    exercise_native_load(
                        app,
                        lambda: Clock.schedule_once(capture, 0.3),
                        args.output.with_suffix('.latency.json'),
                    )
                    return
                if args.view == 'root_refresh':
                    exercise_root_refresh(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'root_navigation':
                    exercise_root_navigation(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'responsive':
                    exercise_responsive(app, lambda: Clock.schedule_once(capture, 0.3))
                    return
                if args.view == 'setting_editor':
                    exercise_setting_editor(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'setting_keyboard':
                    exercise_setting_keyboard(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'history':
                    exercise_history(app, lambda: Clock.schedule_once(capture, 0.3))
                    return
                if args.view == 'profile_editor':
                    exercise_profile_editor(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'profile_address':
                    exercise_profile_address(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'contact_pages':
                    exercise_contact_pages(
                        app, lambda: Clock.schedule_once(capture, 0.3)
                    )
                    return
                if args.view == 'timeout_editor':
                    exercise_timeout(app, lambda: Clock.schedule_once(capture, 0.3))
                    return
                Clock.schedule_once(capture, 0.3)
                return
        else:
            if (
                app.input_dock is not None
                and app.input_dock.keyboard is None
                and time.monotonic() - started < 30
            ):
                Clock.schedule_once(capture, 0.1)
                return
            assert app.input_dock is not None and app.input_dock.keyboard is not None
            assert app.input_dock.keyboard.height == dp(264)
            assert app.shell.height == dp(args.height - 264)
            peer = next(
                widget for widget in app.shell.walk() if isinstance(widget, PeerView)
            )
            if (
                peer.timeline.height < dp(48) or peer.composer.height != dp(64)
            ) and time.monotonic() - started < 30:
                Clock.schedule_once(capture, 0.1)
                return
            if peer.timeline.height < dp(48):
                app.viewport.export_to_png(
                    str(args.output.with_name('keyboard-geometry-failure.png'))
                )
            assert peer.timeline.height >= dp(48), (
                peer.size,
                [(type(child).__name__, child.height) for child in peer.children],
                peer.parent.padding,
            )
            assert abs(peer.composer.y - (app.input_dock.keyboard.top + dp(8))) < dp(1)
            if local_keyboard_checked != 2:
                if local_keyboard_checked == 0:
                    local_keyboard_checked = 1

                    def complete() -> None:
                        nonlocal local_keyboard_checked
                        local_keyboard_checked = 2

                    exercise_local_keyboard(app, complete)
                Clock.schedule_once(capture, 0.2)
                return
        if any(
            trigger is not None and trigger.is_triggered
            for widget in app.shell.walk()
            if (trigger := getattr(widget, '_trigger_layout', None)) is not None
        ):
            assert time.monotonic() - started < 30, (
                'Native descendant layout did not settle'
            )
            Clock.schedule_once(capture, 0.1)
            return
        if args.view in {'entry', 'entry_loading', 'setup', 'lock'}:
            covers = [
                widget for widget in app.shell.walk() if isinstance(widget, ScrollView)
            ]
            assert len(covers) == 1 and not covers[0].do_scroll_y
        if args.view == 'entry_loading':
            assert any(
                getattr(widget, 'text', '') == 'Opening profile'
                for widget in app.shell.walk()
            )
            assert not any(
                isinstance(widget, Action)
                and widget.accessible_name
                in {'Open profile', 'Switch profile', 'New profile'}
                for widget in app.shell.walk()
            )
        if args.view == 'profiles' and args.height >= 800:
            assert not any(
                widget.do_scroll_y
                for widget in app.shell.walk()
                if isinstance(widget, ScrollView)
            )
        if args.view == 'qr':
            assert controller.state.snapshot is not None
            assert_qr_resize(controller.state.snapshot.onion)
            assert_qr_visible(app)
        if args.window_output:
            Window.screenshot(name=args.window_output)
            args.window_output = None
        if args.view == 'confirmation' and not confirmation_checked:
            sheet = ActionSheet.current
            assert sheet is not None and sheet.cancel.focus
            assert abs(sheet.center_y - Window.center[1]) < dp(1)
            assert sheet.height <= Window.height - dp(48)
            if args.font_scale >= 1.5:
                assert sheet.actions.orientation == 'vertical'
                assert sheet.actions.children[0] is sheet.cancel
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            assert ActionSheet.current is None and not confirmed_actions
            show_confirmation()
            previous = ActionSheet.current
            controller.state.covered = True
            ActionSheet.reconcile()
            assert previous is not None and not previous.body.children
            assert ActionSheet.current is None and not confirmed_actions
            controller.state.covered = False
            show_confirmation()
            sheet = ActionSheet.current
            assert sheet is not None
            sheet.cancel.focus = True
            controller.live_invitations.observe(
                IncomingConnectionEvent('Orion', 'orion', 'modal-call')
            )
            ActionSheet.reconcile()
            assert ActionSheet.current is sheet and sheet.cancel.focus
            assert sheet.invitation_indicator.parent is sheet.header
            sheet.invitation_indicator.dispatch('on_release')
            assert ActionSheet.current is None and not confirmed_actions
            assert (
                controller.live_invitations.visible
                and controller.live_invitations.selected == 'modal-call'
            )
            assert not sheet.body.children
            controller.live_invitations.clear()
            show_confirmation()
            confirmation_checked = True
            Clock.schedule_once(capture, 0.2)
            return
        if args.view == 'locked_notice':
            from metor.ui.gui.views.security import LockedActivity

            cue = next(
                widget
                for widget in app.shell.walk()
                if isinstance(widget, LockedActivity)
            )
            cue_height = cue.height
            assert isinstance(cue_height, (int, float))
            assert cue.opacity == 1 and cue_height >= dp(48)
            assert cue.label.text == 'New Drop · Unlock to view'
            assert call_focus and all(field.focus for field in call_focus)
            capture_viewport(app.viewport.parent, args.output)
        elif args.view in {'incoming'}:
            assert (
                app.invitation_overlay is not None and app.invitation_overlay.children
            )
            assert controller.live_invitations.selected == 'first'
            for field in call_focus:
                assert field.focus and field.text == 'Draft stays here'
            capture_viewport(app.viewport.parent, args.output)
        elif args.view in {'contact_sheet', 'confirmation', 'context_menu'}:
            assert ActionSheet.current is not None
            capture_viewport(ActionSheet.current.body, args.output)
        else:
            capture_viewport(app.viewport, args.output)
        evidence = {
            'kind': 'native SDL renderer, synthetic SDK DTOs',
            'sdl_video_driver': os.environ.get('SDL_VIDEODRIVER', 'native default'),
            'python': platform.python_version(),
            'system': platform.system(),
            'machine': platform.machine(),
            'viewport': list(app.viewport.size),
            'window': list(Window.size),
            'rss_bytes': psutil.Process().memory_info().rss,
            'view': args.view,
            'lock_geometry': [
                {
                    'text': widget.text,
                    'opacity': widget.opacity,
                    'color': list(widget.color) if hasattr(widget, 'color') else [],
                    'canvas': [
                        (
                            type(item).__name__,
                            list(getattr(item, 'pos', ())),
                            list(getattr(item, 'size', ())),
                        )
                        for item in canvas.children
                    ],
                    'bounds': list(widget.pos) + list(widget.size),
                    'window': list(widget.to_window(*widget.pos)),
                }
                for widget in app.shell.walk()
                if args.view == 'locked_notice'
                and getattr(widget, 'text', '')
                in {'Metor', 'Locked', 'PIN', 'Forgot PIN?'}
                and (canvas := widget.canvas) is not None
            ],
            'lock_scroll_geometry': [
                {
                    'bounds': list(widget.pos) + list(widget.size),
                    'canvas': [
                        (
                            type(item).__name__,
                            list(getattr(item, 'pos', ())),
                            list(getattr(item, 'size', ())),
                        )
                        for item in before_canvas.children
                    ],
                }
                for widget in app.shell.walk()
                if args.view == 'lock'
                and type(widget).__name__ == 'ScrollView'
                and (canvas := widget.canvas) is not None
                and (before_canvas := canvas.before) is not None
            ],
            'notification_summary_geometry': [
                {
                    'label': widget.text,
                    'row': list(widget.parent.pos) + list(widget.parent.size),
                    'label_bounds': list(widget.pos) + list(widget.size),
                    'symbol_bounds': list(widget.parent.children[0].pos)
                    + list(widget.parent.children[0].size),
                    'translate': [
                        widget.parent.children[0]._translate.x,
                        widget.parent.children[0]._translate.y,
                    ],
                }
                for widget in app.shell.walk()
                if args.view == 'notifications'
                and getattr(widget, 'text', '')
                in {'Lyra', 'Orion · 2', 'Rhea · 3', 'Rhea · 2'}
            ],
            'peer_control_geometry': [
                {
                    'label': widget.accessible_name,
                    'bounds': list(widget.pos) + list(widget.size),
                    'label_bounds': list(widget.label.pos) + list(widget.label.size),
                }
                for widget in app.shell.walk()
                if isinstance(widget, Action)
                and widget.accessible_name in {'DROP', 'LIVE'}
            ],
            'core_integration': False,
            'physical_input': False,
            'native_widget_synthetic_keyboard': True,
            'audio': False,
            'font_scale': args.font_scale,
            'text_field_geometry': [
                {
                    'size': list(field.size),
                    'padding': list(field.padding),
                    'line_lengths': [len(line) for line in field._lines],
                }
                for field in app.shell.walk()
                if isinstance(field, TextField)
            ],
            'qr_geometry': [
                {
                    'widget_pos': list(widget.pos),
                    'widget_size': list(widget.size),
                    'widget_window': list(widget.to_window(*widget.pos)),
                    'scroll_size': list(widget.parent.parent.size),
                    'scroll_window': list(
                        widget.parent.parent.to_window(*widget.parent.parent.pos)
                    ),
                    'square': [
                        list(item.pos) + list(item.size)
                        for item in canvas.children
                        if isinstance(item, Rectangle)
                        and item.size[0] > dp(Geometry.TARGET)
                    ],
                }
                for widget in app.shell.walk()
                if args.view == 'qr'
                and isinstance(widget, ContactQr)
                and (canvas := widget.canvas) is not None
            ],
        }
        args.output.with_suffix('.json').write_text(
            json.dumps(evidence, indent=2) + '\n'
        )
        if args.view == 'qr':
            assert_qr_copy_action(app)
        app.stop()

    if args.view == 'keyboard':
        Clock.schedule_once(open_keyboard, 0.5)
    Clock.schedule_once(capture, 1)
    with patch('metor.ui.gui.app.create_desktop_lifecycle_source', return_value=None):
        app.run()


if __name__ == '__main__':
    main()
