"""Message media restriction and distinct screen-lock/system-suspend boundaries."""

import base64
import socket
import unittest
from unittest.mock import Mock

import test_gui_producers as support
from metor.client import FrontendLaunchContext, MetorRequestRejectedError
from metor.core.api import (
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    CommitVoiceCommand,
    Delivery,
    FinalizeVoiceCommand,
    GetVoiceChunkCommand,
    MessageDirectionCode,
    NotificationPrivacy,
    RestrictClientCommand,
    VoiceChunkAcceptedEvent,
    VoiceCommittedEvent,
    VoiceDataEvent,
    VoiceFinalizedEvent,
    VoiceStartedEvent,
)
from metor.ui.gui.platform.lifecycle import DesktopLifecycleEvent, LifecycleCoordinator
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice import PressSource


class MessageMediaRestrictionTests(unittest.TestCase):
    """Uses real authenticated IPC and protected staging, without physical audio."""

    def setUp(self) -> None:
        """Creates a daemon with an independently accepted LIVE transport."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.h.daemon._transport_state.add_active_connection(self.h.onion, local)

    def test_restriction_denies_message_media_in_both_modes(self) -> None:
        """An accepted LIVE chat and call policy cannot grant locked Voice operations."""
        for delivery in Delivery:
            msg_id = 'draft-' + delivery.value
            self.h.client.begin_voice(
                self.h.onion,
                delivery,
                msg_id,
                'pcm_s16le_16000_mono',
                owner_token=self.h.owner,
            )
            self.h.client.append_voice(
                msg_id,
                0,
                base64.b64encode(b'\x00\x01' * 320).decode(),
                owner_token=self.h.owner,
            )
            self.h.client.finalize_voice(msg_id, 20, owner_token=self.h.owner)
        self.h.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                accept_calls_locked=True,
                notification_privacy=NotificationPrivacy.OFF,
            ),
            ClientRestrictedEvent,
        )
        for delivery in Delivery:
            msg_id = 'draft-' + delivery.value
            for command, expected in (
                (
                    BeginVoiceCommand(
                        self.h.onion,
                        delivery,
                        'new-' + delivery.value,
                        'pcm_s16le_16000_mono',
                        self.h.owner,
                    ),
                    VoiceStartedEvent,
                ),
                (
                    AppendVoiceChunkCommand(msg_id, 640, 'AAE=', self.h.owner),
                    VoiceChunkAcceptedEvent,
                ),
                (FinalizeVoiceCommand(msg_id, 20, self.h.owner), VoiceFinalizedEvent),
                (
                    GetVoiceChunkCommand(
                        self.h.onion,
                        msg_id,
                        MessageDirectionCode.OUT,
                        0,
                        640,
                        self.h.owner,
                    ),
                    VoiceDataEvent,
                ),
                (
                    CommitVoiceCommand(self.h.onion, msg_id, self.h.owner),
                    VoiceCommittedEvent,
                ),
            ):
                with self.subTest(delivery=delivery, operation=type(command).__name__):
                    with self.assertRaises(MetorRequestRejectedError):
                        self.h.client.request(command, expected)
            self.assertIsNotNone(self.h.repository.get(msg_id))


class MessageCoverTests(unittest.TestCase):
    """Exercises the real GUI cover without a display, microphone or peer."""

    def setUp(self) -> None:
        """Constructs only presentation state and controlled public clients."""
        self.gui = GuiController(FrontendLaunchContext('test', Mock()))
        self.gui.client = Mock()
        self.gui.state.covered = False
        self.gui.calls = Mock()
        self.gui.voice.depart = Mock()
        self.gui.playback.stop = Mock()
        self.addCleanup(self.gui.close)

    def test_screen_lock_stops_message_media_and_retains_call(self) -> None:
        """An OS screen lock does not stop the separately accepted conversation."""
        self.gui.screen_lock()
        self.assertTrue(self.gui.state.covered)
        self.assertTrue(self.gui.voice.depart.called)
        self.assertTrue(self.gui.playback.stop.called)
        self.gui.calls.clear.assert_not_called()
        self.gui.calls.suspend.assert_not_called()
        self.assertFalse(self.gui.voice.down(PressSource.PHYSICAL))
        self.gui.resume()
        self.assertTrue(self.gui.state.covered)
        self.assertFalse(self.gui.voice.down(PressSource.PHYSICAL))

    def test_system_suspend_ends_call_and_never_unmutes_on_resume(self) -> None:
        """Suspend ends real-time audio, whereas resume only retains the cover."""
        self.gui.suspend()
        self.gui.calls.suspend.assert_called_once()
        self.assertTrue(self.gui.state.covered)
        self.gui.resume()
        self.gui.calls.start.assert_not_called()
        self.gui.calls.accept.assert_not_called()
        self.gui.calls.mute.assert_not_called()

    def test_native_provider_distinguishes_screen_lock_and_suspend(self) -> None:
        """Actual typed provider messages select different media lifecycles."""
        actions: list[str] = []
        coordinator = LifecycleCoordinator(
            lambda: actions.append('privacy'),
            lambda: actions.append('suspend'),
            lambda: actions.append('resume'),
            lambda: actions.append('render'),
            screen_lock=lambda: actions.append('screen-lock'),
        )
        coordinator.apply(DesktopLifecycleEvent.LOCK)
        self.assertEqual(actions, ['privacy', 'screen-lock', 'render'])
        actions.clear()
        coordinator.apply(DesktopLifecycleEvent.SUSPEND)
        self.assertEqual(actions, ['privacy', 'suspend', 'render'])
        actions.clear()
        coordinator.apply(DesktopLifecycleEvent.RESUME)
        self.assertEqual(actions, ['resume', 'render'])
