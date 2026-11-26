"""Exact LIVE End/Cancel identities across replacement calls and delayed transport admission."""

import socket
import threading
import unittest
import gc
import weakref
from unittest.mock import patch
from unittest.mock import Mock

import test_gui_producers as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    Delivery,
    ConnectionConnectingEvent,
    ContactEntry,
    DisconnectCommand,
    IpcEvent,
    LiveContextEntry,
    LiveControlCompletedEvent,
    LiveControlRejectedEvent,
    RetunnelCommand,
    RetunnelInitiatedEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class LiveStopPresentationTests(unittest.TestCase):
    """Stop feedback bridges IPC acknowledgement and the next authoritative snapshot."""

    def setUp(self) -> None:
        """Creates one qualified invitation and controlled asynchronous admission."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.state.covered = False
        self.gui.state.capabilities = frozenset({'qualified_live_control'})
        self.gui.state.route = Route('V09', 'bob', Delivery.LIVE)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='ab' * 16
                )
            ],
            revision=4,
        )
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.refresh_state = Mock()

    def complete(self, event: IpcEvent | None) -> None:
        """Installs the correlated result while retaining the original displayed snapshot."""
        mutation = self.gui.live.pending
        self.assertIsNotNone(mutation)
        assert mutation is not None
        self.assertTrue(self.gui.live.install(Update(0, mutation.operation, event)))

    def test_cancel_feedback_is_immediate_and_acknowledgement_cannot_rearm_it(
        self,
    ) -> None:
        """Duplicate input stays blocked through the entire old-snapshot interval."""
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.gui.client.request.assert_not_called()
        self.assertFalse(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.submit.call_args.args[1]()
        command = self.gui.client.request.call_args.args[0]
        self.assertIsInstance(command, DisconnectCommand)
        self.assertEqual(command.attempt_id, 'ab' * 16)
        self.assertIsNone(command.context_generation)
        self.complete(LiveControlCompletedEvent('bob'))
        self.assertIsNone(self.gui.live.pending)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.assertFalse(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.assertFalse(self.gui.live.start('bob'))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=5)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)

    def test_end_feedback_does_not_describe_a_replacement_connection(self) -> None:
        """The original action cannot label a newer logical connection as ending."""
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry('Bob', 'bob', True, 'connected', context_generation=1)
            ],
            revision=4,
        )
        self.assertTrue(self.gui.live.end('bob', context_generation=1))
        self.assertEqual(self.gui.live.stop_status('bob'), 'Ending Live…')
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry('Bob', 'bob', True, 'connected', context_generation=2)
            ],
            revision=5,
        )
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.complete(LiveControlCompletedEvent('bob'))
        self.gui.live.poll()
        self.assertTrue(self.gui.live.end('bob', context_generation=2))

    def test_snapshot_while_cancel_pending_cannot_remove_progress(self) -> None:
        """A concurrent snapshot cannot finish a stop or substitute for post-result state."""
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='ab' * 16
                )
            ],
            revision=5,
        )
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.complete(LiveControlCompletedEvent('bob'))
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.assertFalse(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=6)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)

    def test_disconnected_snapshot_before_reply_keeps_the_cancel_owner(self) -> None:
        """An early broadcast of transport teardown cannot expose Start before confirmation."""
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[LiveContextEntry('Bob', 'bob', True, 'disconnected')],
            revision=5,
        )
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.complete(LiveControlCompletedEvent('bob'))
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=6)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertTrue(self.gui.live.retry_ready('bob'))

    def test_started_invitation_cancellation_does_not_become_connection_failure(
        self,
    ) -> None:
        """A teardown snapshot before Cancel acknowledgement stays explicit stop progress."""
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=1)
        self.assertTrue(self.gui.live.start('bob'))
        self.complete(ConnectionConnectingEvent('Bob', 'bob', revision=2))
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='ab' * 16
                )
            ],
            revision=3,
        )
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=4)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertTrue(self.gui.live.starting('bob'))
        self.complete(LiveControlCompletedEvent('bob'))
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=5)
        self.gui.live.poll()
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 2)

    def test_uncertain_cancel_requires_fresh_state_without_automatic_retry(
        self,
    ) -> None:
        """An absent reply retains progress until an authoritative read permits new intent."""
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.complete(None)
        self.assertEqual(self.gui.live.stop_status('bob'), 'Cancelling Live…')
        self.gui.live.poll()
        self.assertFalse(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='ab' * 16
                )
            ],
            revision=5,
        )
        self.gui.live.poll()
        self.assertIsNone(self.gui.live.pending)
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))

    def test_rejected_cancel_rearms_only_explicit_intent(self) -> None:
        """A rejected exact action removes progress while preserving the existing chat."""
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.complete(LiveControlRejectedEvent('bob'))
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))

    def test_stop_feedback_is_bounded_and_hidden_under_privacy_cover(self) -> None:
        """Unrefreshed stops cannot accumulate unlimited peer state or reveal private activity."""
        with patch.object(GuiLimits, 'TEXT_CONTEXTS', 1):
            self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
            self.complete(LiveControlCompletedEvent('bob'))
            self.assertFalse(self.gui.live.end('carol', context_generation=2))
        self.gui.state.covered = True
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.assertEqual(self.gui.submit.call_count, 1)

    def test_inactive_recovery_hints_allow_fresh_explicit_start(self) -> None:
        """A cancelled invitation's no-token scheduled row cannot strand the user."""
        for session in ('reconnect_grace', 'reconnect_scheduled'):
            with self.subTest(session=session):
                gui = GuiController(
                    FrontendLaunchContext('fixture', Mock()), simulator=True
                )
                gui.state.covered = False
                gui.client = Mock()
                gui.submit = Mock(return_value=True)
                gui.state.snapshot = RuntimeSnapshotEvent(
                    'fixture',
                    'self',
                    live_contexts=[LiveContextEntry('Bob', 'bob', True, session)],
                )
                self.assertTrue(gui.live.idle('bob'))
                self.assertTrue(gui.live.retry_ready('bob'))
                self.assertTrue(gui.live.start('bob'))
                self.assertTrue(gui.live.starting('bob'))
                self.assertFalse(gui.live.retry_ready('bob'))
                self.assertFalse(gui.live.start('bob'))
                self.assertEqual(gui.submit.call_count, 1)

    def test_recovery_permission_or_outbound_attempt_blocks_new_start(self) -> None:
        """A transport hint with a logical recovery token or actual attempt stays occupied."""
        for session in ('reconnect_grace', 'reconnect_scheduled'):
            for recovery, attempt in ((True, None), (False, 'ab' * 16)):
                with self.subTest(session=session, recovery=recovery, attempt=attempt):
                    self.gui.state.snapshot = RuntimeSnapshotEvent(
                        'fixture',
                        'self',
                        live_contexts=[
                            LiveContextEntry(
                                'Bob',
                                'bob',
                                True,
                                session,
                                recovery_eligible=recovery,
                                outbound_attempt_id=attempt,
                            )
                        ],
                    )
                    self.assertFalse(self.gui.live.idle('bob'))
                    self.assertFalse(self.gui.live.retry_ready('bob'))
                    self.assertEqual(self.gui.submit.call_count, 0)

    def test_cover_releases_uncertain_start_snapshot_without_rearming_request(
        self,
    ) -> None:
        """Real application lock releases sensitive projection ownership and keeps uncertainty."""
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'private-own-address',
            contacts=[ContactEntry('Sensitive contact', 'bob')],
            revision=4,
        )
        snapshot = weakref.ref(self.gui.state.snapshot)
        self.assertTrue(self.gui.live.start('bob'))
        self.complete(None)
        mutation = self.gui.live.pending
        self.assertIsNotNone(mutation)
        self.assertTrue(self.gui.live._awaiting_snapshot)
        self.assertTrue(self.gui.security.lock())
        gc.collect()
        self.assertIsNone(snapshot())
        self.assertIsNone(self.gui.live._uncertain_snapshot)
        self.assertIsNone(self.gui.live._progress.starts['bob'].snapshot)
        self.assertEqual(self.gui.live._progress.starts['bob'].phase, 'checking')
        self.assertEqual(self.gui.live._progress.starts['bob'].revision, 4)
        self.assertIs(self.gui.live.pending, mutation)
        self.assertTrue(self.gui.live._awaiting_snapshot)
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', '', revision=5)
        self.gui.live.poll()
        self.assertIs(self.gui.live.pending, mutation)
        self.assertTrue(self.gui.live._awaiting_snapshot)
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=6)
        self.gui.live.poll()
        self.assertIsNone(self.gui.live.pending)
        self.assertFalse(self.gui.live._awaiting_snapshot)
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertTrue(self.gui.live.start('bob'))
        self.assertEqual(self.gui.submit.call_count, 2)

    def test_cover_releases_stop_snapshot_preserving_exact_pending_identity(
        self,
    ) -> None:
        """A covered Cancel loses its private snapshot without abandoning result ownership."""
        assert self.gui.state.snapshot is not None
        snapshot = weakref.ref(self.gui.state.snapshot)
        self.assertTrue(self.gui.live.end('bob', attempt_id='ab' * 16))
        mutation = self.gui.live.pending
        self.assertTrue(self.gui.security.lock())
        gc.collect()
        self.assertIsNone(snapshot())
        self.assertIs(self.gui.live.pending, mutation)
        assert mutation is not None
        self.assertEqual(mutation.attempt_id, 'ab' * 16)
        stopping = self.gui.live._progress.stops['bob']
        self.assertIsNone(stopping.snapshot)
        self.assertTrue(stopping.awaiting_result)
        self.assertEqual(stopping.revision, 4)
        self.assertEqual(self.gui.live.stop_status('bob'), '')
        self.gui.live.poll()
        self.assertIs(self.gui.live.pending, mutation)
        self.assertFalse(self.gui.live.end('bob', attempt_id='ab' * 16))
        self.complete(None)
        self.assertFalse(stopping.awaiting_result)
        self.assertTrue(self.gui.live._awaiting_snapshot)
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', '', revision=5)
        self.gui.live.poll()
        self.assertIs(self.gui.live.pending, mutation)
        self.assertEqual(self.gui.submit.call_count, 1)
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=6)
        self.gui.live.poll()
        self.assertIsNone(self.gui.live.pending)
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)


class LiveControlCoreTests(unittest.TestCase):
    """Exercises real local Core IPC with inert peer sockets and controlled connection timing."""

    def setUp(self) -> None:
        """Starts an isolated protected Core without external transport.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.state = self.h.daemon._transport_state

    def pair(self) -> tuple[socket.socket, socket.socket]:
        """Creates a native local peer socket pair with deterministic test cleanup.

        Args:
            None
        Returns:
            tuple[socket.socket, socket.socket]: Managed and inert peer ends.
        """
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        return local, peer

    def test_old_end_cannot_terminate_replacement_context(self) -> None:
        """A delayed End generation is rejected while the replacement socket stays active.

        Args:
            None
        Returns:
            None
        """
        first, _ = self.pair()
        second, _ = self.pair()
        self.state.add_active_connection(self.h.onion, first)
        old = self.state.get_live_context_generation(self.h.onion)
        self.state.pop_any_connection(self.h.onion)
        self.state.add_active_connection(self.h.onion, second)
        current = self.state.get_live_context_generation(self.h.onion)
        self.assertNotEqual(old, current)
        rejected = self.h.client.request(
            DisconnectCommand(self.h.onion, context_generation=old), IpcEvent
        )
        self.assertIsInstance(rejected, LiveControlRejectedEvent)
        self.assertIs(self.state.get_connection(self.h.onion), second)
        completed = self.h.client.request(
            DisconnectCommand(self.h.onion, context_generation=current), IpcEvent
        )
        self.assertIsInstance(completed, LiveControlCompletedEvent)
        self.assertIsNone(self.state.get_connection(self.h.onion))

    def test_stale_cancel_preserves_new_attempt_and_current_cancel_closes_its_socket(
        self,
    ) -> None:
        """Cancellation uses the exact calling attempt rather than the peer alone.

        Args:
            None
        Returns:
            None
        """
        self.state.add_outbound_attempt(self.h.onion)
        old = self.state.get_outbound_attempt_id(self.h.onion)
        self.state.discard_outbound_attempt(self.h.onion)
        self.state.add_outbound_attempt(self.h.onion)
        current = self.state.get_outbound_attempt_id(self.h.onion)
        local, _ = self.pair()
        self.assertTrue(self.state.bind_outbound_socket(self.h.onion, local, current))
        self.assertNotEqual(old, current)
        snapshot = self.h.client.runtime_snapshot()
        self.assertEqual(
            next(
                row.outbound_attempt_id
                for row in snapshot.live_contexts
                if row.onion == self.h.onion
            ),
            current,
        )
        rejected = self.h.client.request(
            DisconnectCommand(self.h.onion, attempt_id=old), IpcEvent
        )
        self.assertIsInstance(rejected, LiveControlRejectedEvent)
        self.assertTrue(self.state.is_current_outbound_socket(self.h.onion, local))
        completed = self.h.client.request(
            DisconnectCommand(self.h.onion, attempt_id=current), IpcEvent
        )
        self.assertIsInstance(completed, LiveControlCompletedEvent)
        self.assertIsNone(self.state.get_outbound_attempt_id(self.h.onion))
        self.assertEqual(local.fileno(), -1)

    def test_cancelled_connect_worker_cannot_bind_or_erase_a_later_attempt(
        self,
    ) -> None:
        """A socket returned after cancellation stays outside the replacement attempt.

        Args:
            None
        Returns:
            None
        """
        local, _ = self.pair()
        entered, release = threading.Event(), threading.Event()

        def delayed(_onion: str) -> socket.socket:
            """Holds native socket creation until after explicit cancellation.

            Args:
                _onion: Original synthetic peer identity.
            Returns:
                socket.socket: Late original worker socket.
            """
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Fixture did not release delayed connection')
            return local

        network = self.h.daemon._network
        with patch.object(network._controller._tm, 'connect', side_effect=delayed):
            worker = threading.Thread(target=network.connect_to, args=(self.h.onion,))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                original = self.state.get_outbound_attempt_id(self.h.onion)
                self.assertIsNotNone(original)
                completed = self.h.client.request(
                    DisconnectCommand(self.h.onion, attempt_id=original), IpcEvent
                )
                self.assertIsInstance(completed, LiveControlCompletedEvent)
                self.state.add_outbound_attempt(self.h.onion)
                replacement = self.state.get_outbound_attempt_id(self.h.onion)
                self.assertNotEqual(original, replacement)
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(self.state.get_outbound_attempt_id(self.h.onion), replacement)
        self.assertEqual(local.fileno(), -1)

    def test_route_rotation_rechecks_context_after_io_and_excludes_drop_tunnels(
        self,
    ) -> None:
        """A delayed route change cannot tear down a replacement or rotate a DROP route.

        Args:
            None
        Returns:
            None
        """
        first, _ = self.pair()
        second, _ = self.pair()
        self.state.add_active_connection(self.h.onion, first)
        generation = self.state.get_live_context_generation(self.h.onion)
        self.assertIsNotNone(generation)
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        network = self.h.daemon._network
        original = network.retunnel

        def rotation() -> tuple[bool, None, dict[str, object]]:
            """Waits at real controller's enclosing Tor boundary.

            Args:
                None
            Returns:
                tuple: Successful synthetic circuit-rotation result.
            """
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Fixture did not release rotation')
            return True, None, {}

        def traced(target: str, context_generation: int | None = None) -> None:
            """Tracks complete qualified controller execution after its initial receipt.

            Args:
                target: Original resolved target.
                context_generation: Original caller qualification.
            Returns:
                None
            """
            try:
                original(target, context_generation)
            finally:
                if entered.is_set() and release.is_set():
                    finished.set()

        with (
            patch.object(
                network._controller._tm, 'rotate_circuits', side_effect=rotation
            ) as rotate,
            patch.object(network, 'retunnel', side_effect=traced),
            patch.object(self.h.daemon._outbox, 'reset_tunnel') as reset_drop,
        ):
            stale = self.h.client.request(
                RetunnelCommand(self.h.onion, generation + 1), IpcEvent
            )
            self.assertIsInstance(stale, LiveControlRejectedEvent)
            rotate.assert_not_called()
            try:
                started = self.h.client.request(
                    RetunnelCommand(self.h.onion, generation), IpcEvent
                )
                self.assertIsInstance(started, RetunnelInitiatedEvent)
                self.assertTrue(entered.wait(5))
                snapshot = self.h.client.runtime_snapshot()
                self.assertTrue(
                    next(
                        row.route_changing
                        for row in snapshot.live_contexts
                        if row.onion == self.h.onion
                    )
                )
                duplicate = self.h.client.request(
                    RetunnelCommand(self.h.onion, generation), IpcEvent
                )
                self.assertIsInstance(duplicate, LiveControlRejectedEvent)
                ended = self.h.client.request(
                    DisconnectCommand(self.h.onion, generation), IpcEvent
                )
                self.assertIsInstance(ended, LiveControlCompletedEvent)
                self.state.add_active_connection(self.h.onion, second)
            finally:
                release.set()
            self.assertTrue(finished.wait(5))
            rotate.assert_called_once()
            reset_drop.assert_not_called()
        self.assertIs(self.state.get_connection(self.h.onion), second)
        self.assertFalse(self.state.is_retunneling(self.h.onion))
