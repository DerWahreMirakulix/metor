"""Exact LIVE End/Cancel identities across replacement calls and delayed transport admission."""

import socket
import threading
import unittest
from unittest.mock import patch

import test_gui_producers as support
from metor.core.api import (
    DisconnectCommand,
    IpcEvent,
    LiveControlCompletedEvent,
    LiveControlRejectedEvent,
    RetunnelCommand,
    RetunnelInitiatedEvent,
)


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
