"""Destructive privacy observation with bounded typed facts, real IPC and isolated test profiles."""

import threading
import time
import unittest
from unittest.mock import Mock, patch

from metor.client import (
    FrontendLaunchContext,
    FrontendProfileState,
    MetorClient,
    build_session_auth_proof,
)
from metor.client.platform import ButtonSample, PlatformActionResult, PlatformBindings
from metor.core.api import (
    Delivery,
    IpcEvent,
    RuntimeSnapshotEvent,
    SelfDestructInitiatedEvent,
    SelfDestructKeyDestroyedEvent,
    SelfDestructRuntimeReleasedEvent,
    SelfDestructSafeEvent,
    SelfDestructCompletedEvent,
    SelfDestructCleanupFailedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

import test_gui_producers as support


class PurgeObservationTests(unittest.TestCase):
    """Checks unknown outcomes, exact identity, early producer fencing and privacy teardown."""

    def setUp(self) -> None:
        """Creates only synthetic public metadata and no destructive-capable host adapter.

        Args:
            None
        Returns:
            None
        """
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', '', epoch='epoch')
        self.gui.state.route = Route('V08', 'private-peer', Delivery.DROP)
        self.gui.state.set_draft('private-peer', Delivery.DROP, 'private draft')
        self.client = self.gui.client = Mock()
        self.monitor = self.gui.purge
        self.generation = self.gui.state.generation
        self.operation = 'a' * 32
        self.addCleanup(self.gui.close)

    def begin(self) -> None:
        """Admits an actual event type with a deterministic start clock.

        Args:
            None
        Returns:
            None
        """
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=100.0):
            self.assertTrue(
                self.monitor.observe(
                    self.generation,
                    SelfDestructInitiatedEvent('fixture', self.operation),
                )
            )

    def test_initiated_and_eof_clear_private_state_without_claiming_safety(
        self,
    ) -> None:
        """EOF after acceptance cannot return to profile entry or report successful destruction.

        Args:
            None
        Returns:
            None
        """
        self.begin()
        self.assertFalse(self.gui.submit('A11', lambda: None))
        self.monitor.poll(now=101)
        self.assertTrue(self.gui.state.covered)
        self.assertEqual(self.gui.state.route, Route('V22'))
        self.assertIsNone(self.gui.state.snapshot)
        self.assertFalse(self.gui.state.drafts)
        self.assertIsNone(self.gui.client)
        self.assertIs(self.gui.purge, self.monitor)
        self.assertEqual(self.monitor.title, 'Purging profile')
        self.assertTrue(self.monitor.lost(self.generation))
        self.monitor.poll(now=102)
        self.assertEqual(self.monitor.title, 'Destruction not confirmed')
        self.client.request.assert_not_called()
        self.client.prepare_profile_exit.assert_not_called()
        self.assertFalse(self.gui.open_profile())
        self.assertFalse(self.gui.create_profile('recreated', 'password'))

    def test_combined_safe_is_required_even_after_two_individual_milestones(
        self,
    ) -> None:
        """Two milestones and a completion event do not substitute for Core's combined guarantee.

        Args:
            None
        Returns:
            None
        """
        self.begin()
        for event in (
            SelfDestructKeyDestroyedEvent('fixture', self.operation),
            SelfDestructRuntimeReleasedEvent('fixture', self.operation),
            SelfDestructCompletedEvent('fixture', self.operation),
        ):
            self.monitor.observe(self.generation, event)
        self.monitor.poll(now=101)
        self.assertEqual(self.monitor.title, 'Destruction not confirmed')

    def test_safe_cleanup_failure_and_lost_terminal_keep_their_distinct_truth(
        self,
    ) -> None:
        """Safe remains irreversible while incomplete and unknown file cleanup stay distinguishable.

        Args:
            None
        Returns:
            None
        """
        self.begin()
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=101.0):
            self.monitor.observe(
                self.generation, SelfDestructSafeEvent('fixture', self.operation)
            )
        self.monitor.poll(now=102)
        self.assertEqual(self.monitor.title, 'Profile access destroyed')
        self.monitor.poll(now=101 + GuiLimits.PURGE_CLEANUP_SECONDS)
        self.assertIn('could not be confirmed', self.monitor.detail)
        self.monitor.observe(
            self.generation,
            SelfDestructCleanupFailedEvent('fixture', operation_id=self.operation),
        )
        self.monitor.poll(now=108)
        self.assertEqual(self.monitor.detail, 'File cleanup is incomplete.')
        self.assertEqual(self.monitor.title, 'Profile access destroyed')

    def test_wrong_identity_and_legacy_initiation_never_establish_safe(self) -> None:
        """Another activation, operation or profile cannot contribute safety to this outcome.

        Args:
            None
        Returns:
            None
        """
        self.begin()
        for generation, profile, operation in (
            (self.generation + 1, 'fixture', self.operation),
            (self.generation, 'other', self.operation),
            (self.generation, 'fixture', 'b' * 32),
        ):
            self.monitor.observe(generation, SelfDestructSafeEvent(profile, operation))
        self.monitor.poll(now=100 + GuiLimits.PURGE_OBSERVE_SECONDS)
        self.assertEqual(self.monitor.title, 'Destruction not confirmed')
        self.gui.close()
        self.monitor = self.gui.purge
        self.generation = self.gui.state.generation
        self.monitor.observe(self.generation, SelfDestructInitiatedEvent())
        self.monitor.observe(
            self.generation, SelfDestructSafeEvent('fixture', self.operation)
        )
        self.monitor.lost(self.generation)
        self.gui.poll()
        self.assertEqual(self.monitor.title, 'Destruction not confirmed')

    def test_async_milestones_can_precede_correlated_initiated_ui_result(self) -> None:
        """Status facts survive queue clearing even when the SDK response worker runs late.

        Args:
            None
        Returns:
            None
        """
        self.monitor.observe(
            self.generation, SelfDestructSafeEvent('fixture', self.operation)
        )
        self.monitor.observe(
            self.generation, SelfDestructCompletedEvent('fixture', self.operation)
        )
        self.gui.mailbox.put(
            Update(
                self.generation,
                'A25',
                SelfDestructInitiatedEvent('fixture', self.operation),
            )
        )
        self.gui.poll()
        self.assertEqual(self.monitor.title, 'Profile access destroyed')
        self.assertEqual(self.monitor.detail, 'File cleanup completed.')
        self.assertIsNone(self.gui.mailbox.take())

    def test_accepted_event_stops_producers_before_next_native_tick(self) -> None:
        """Only worker stop flags change on the SDK callback; no finalization is requested.

        Args:
            None
        Returns:
            None
        """
        capture = self.gui.voice.worker = Mock()
        playback = self.gui.playback.worker = Mock()
        resend = self.gui.resend.current = Mock()
        self.begin()
        capture.request_stop.assert_called_once_with(purge=True)
        playback.stop.assert_called_once_with()
        resend.cancelled.set.assert_called_once_with()
        self.assertFalse(self.gui.state.covered)
        self.client.request.assert_not_called()


class PurgeObservationCoreTests(unittest.TestCase):
    """Checks GUI observation against one actual, explicitly isolated encrypted Core destruction."""

    def test_exact_gui_operation_observes_actual_safe_completion(self) -> None:
        """The physical chord reaches exact Core safety before one shutdown-port request.

        Args:
            None
        Returns:
            None
        """
        fixture = support.GuiProducerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        host = Mock()
        host.profile_state.return_value = FrontendProfileState(
            'voice-owned', True, False, True
        )
        shutdown = Mock()
        shutdown.request_shutdown.return_value = PlatformActionResult.ACCEPTED
        bindings = PlatformBindings('fixture', Mock(), shutdown)
        gui = GuiController(
            FrontendLaunchContext('voice-owned', host, platform=bindings)
        )
        self.addCleanup(gui.close)
        generation = gui.state.generation
        terminal = threading.Event()

        def event_received(event: IpcEvent) -> None:
            """Feeds the production observer from the real SDK callback and signals terminal facts.

            Args:
                event: Actual Core event.
            Returns:
                None
            """
            if not gui.purge.observe(generation, event):
                gui.mailbox.put(Update(generation, 'event', event))
            if isinstance(
                event, (SelfDestructCompletedEvent, SelfDestructCleanupFailedEvent)
            ):
                terminal.set()

        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        client = MetorClient(
            fixture.daemon._ipc.port,
            auth_provider=provider,
            on_event=event_received,
            on_disconnect=lambda: gui.purge.lost(generation),
        )
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        gui.client = client
        gui.state.snapshot = client.runtime_snapshot()
        gui.state.covered = False
        keyslot = fixture.pm.paths.get_keyslot_file()
        self.assertTrue(keyslot.exists())
        now = time.monotonic()
        for sample in (
            ButtonSample(0, now, False, False),
            ButtonSample(1, now + 1, True, True),
            ButtonSample(2, now + 1 + GuiLimits.PURGE_SECONDS, True, True),
        ):
            gui.device.receive(sample)
            gui.device.poll()
        deadline = time.monotonic() + 20
        while (
            not terminal.is_set() or not shutdown.request_shutdown.called
        ) and time.monotonic() < deadline:
            gui.poll()
            terminal.wait(0.01)
        self.assertTrue(terminal.is_set())
        self.assertTrue(shutdown.request_shutdown.called)
        shutdown_worker = gui.device._purge_shutdown_worker
        self.assertIsNotNone(shutdown_worker)
        assert shutdown_worker is not None
        shutdown_worker.join(3)
        gui.poll()
        gui.poll()
        self.assertFalse(keyslot.exists())
        self.assertEqual(gui.state.route, Route('V22'))
        self.assertEqual(gui.purge.title, 'Profile access destroyed')
        self.assertEqual(gui.purge.detail, 'Powering off.')
        shutdown.request_shutdown.assert_called_once_with()
        self.assertIsNone(gui.client)
        self.assertEqual(host.profile_state.call_count, 2)
