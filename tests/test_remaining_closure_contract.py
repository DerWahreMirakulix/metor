"""Remaining closure regressions through real daemon and transport ownership."""

import socket
import threading
import unittest
import io
from unittest.mock import patch

import test_closure_integration as support
from metor.core.api import (
    ConnectionRejectedEvent,
    RejectCommand,
    DisconnectCommand,
    DisconnectedEvent,
)
from metor.core.daemon.managed.writer import BoundedSocketWriter
from metor.utils import Constants
from scripts import validate_generated_docs
from pathlib import Path
from contextlib import redirect_stdout


class RemainingTransportTests(unittest.TestCase):
    """Observe production cleanup without closing workers from the assertions."""

    def setUp(self) -> None:
        self.support = support.ClosureDaemonTests()
        self.support.setUp()
        self.addCleanup(self.support.doCleanups)
        self.daemon = self.support.daemon()
        self.client = self.support.client(self.daemon)
        self.state = self.daemon._transport_state
        self.onion = self.support.fixture.receiver_onion

    def pair(self) -> tuple[socket.socket, socket.socket]:
        local, peer = socket.socketpair()
        for conn in (local, peer):
            self.addCleanup(conn.close)
            conn.settimeout(2)
        return local, peer

    def retired(self, conn: socket.socket, writer: BoundedSocketWriter) -> None:
        writer._thread.join(2)
        self.assertFalse(writer._thread.is_alive())
        self.assertNotIn(conn, self.state._socket_writers)
        self.assertEqual(conn.fileno(), -1)

    def pause(self, conn: socket.socket) -> threading.Event:
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def claim() -> bool:
            entered.set()
            return release.wait(5)

        self.state.send_frame(conn, b'prior\n', claim)
        self.assertTrue(entered.wait(2))
        return release

    def test_ordinary_reject_dispatch_drains_before_eof_and_other_ipc(self) -> None:
        local, peer = self.pair()
        self.state.add_pending_connection(self.onion, local, b'')
        release = self.pause(local)
        writer = self.state._socket_writers[local]
        result = self.client.request(RejectCommand(self.onion), ConnectionRejectedEvent)
        self.assertIsNotNone(result)
        other = self.support.client(self.daemon)
        self.assertIsNotNone(other.runtime_snapshot())
        release.set()
        data = bytearray()
        while block := peer.recv(4096):
            data.extend(block)
        self.assertEqual(
            data,
            f'prior\n/reject manual {self.support.fixture.sender_onion}\n'.encode(),
        )
        self.retired(local, writer)

    def test_replacement_retires_drained_active_and_pending_writers(self) -> None:
        for pending in (False, True):
            with self.subTest(pending=pending):
                local, peer = self.pair()
                new, new_peer = self.pair()
                self.state.abort_all_sockets()

                def add(conn: socket.socket) -> None:
                    if pending:
                        self.state.add_pending_connection(self.onion, conn, b'')
                    else:
                        self.state.add_active_connection(self.onion, conn)

                add(local)
                self.state.send_frame(local, b'old')
                writer = self.state._socket_writers[local]
                self.assertEqual(peer.recv(3), b'old')
                self.assertTrue(writer.flush(2))
                add(new)
                self.retired(local, writer)
                self.state.send_frame(new, b'new')
                self.assertEqual(new_peer.recv(3), b'new')
                self.state.abort_all_sockets()

    def test_ordinary_reject_saturated_final_admission_retires(self) -> None:
        local, peer = self.pair()
        self.state.add_pending_connection(self.onion, local, b'')
        with patch.object(Constants, 'PEER_WRITER_QUEUE_FRAMES', 1):
            release = self.pause(local)
        writer = self.state._socket_writers[local]
        self.state.send_frame(local, b'queued\n')
        result = self.client.request(RejectCommand(self.onion), ConnectionRejectedEvent)
        self.assertIsNotNone(result)
        release.set()
        self.retired(local, writer)
        self.assertEqual(peer.recv(4096), b'')
        self.assertIsNotNone(self.client.runtime_snapshot())

    def test_remote_disconnect_and_eof_repeatedly_retire_drained_writers(self) -> None:
        for cycle in range(12):
            with self.subTest(cycle=cycle):
                local, peer = self.pair()
                self.state.add_active_connection(self.onion, local)
                self.state.send_frame(local, b'probe\n')
                writer = self.state._socket_writers[local]
                self.assertEqual(peer.recv(6), b'probe\n')
                self.assertTrue(writer.flush(2))
                receiver = threading.Thread(
                    target=self.daemon._network._receiver._receiver_target,
                    args=(self.onion, local),
                )
                receiver.start()
                if cycle % 2:
                    peer.sendall(b'/disconnect manual\n')
                else:
                    peer.shutdown(socket.SHUT_WR)
                receiver.join(2)
                self.assertFalse(receiver.is_alive())
                self.retired(local, writer)
                self.assertFalse(self.state._socket_writers)
        self.assertIsNotNone(self.client.runtime_snapshot())

    def test_receiver_cleanup_preserves_admitted_final_and_duplicate_cleanup(
        self,
    ) -> None:
        local, peer = self.pair()
        self.state.add_active_connection(self.onion, local)
        release = self.pause(local)
        writer = self.state._socket_writers[local]
        self.assertIsNotNone(
            self.client.request(DisconnectCommand(self.onion), DisconnectedEvent)
        )
        self.state.finish_connection(local, b'not-a-second-final\n')
        with self.assertRaises(ConnectionError):
            self.state.send_frame(local, b'not-admitted\n')
        peer.shutdown(socket.SHUT_WR)
        receiver = threading.Thread(
            target=self.daemon._network._receiver._receiver_target,
            args=(self.onion, local),
        )
        receiver.start()
        receiver.join(2)
        self.assertFalse(receiver.is_alive())
        self.state.retire_connection(local, preserve_final=True)
        self.state.finish_connection(local, b'not-a-second-final-after-cleanup\n')
        self.assertFalse(writer._closed.is_set())
        release.set()
        received = bytearray()
        while block := peer.recv(4096):
            received.extend(block)
        self.assertEqual(
            received,
            f'prior\n/disconnect manual {self.support.fixture.sender_onion}\n'.encode(),
        )
        self.retired(local, writer)
        self.state.retire_connection(local)
        self.state.retire_connection(local)
        self.assertFalse(self.state.has_live_reconnect_grace(self.onion))

    def test_reject_final_timeout_and_shutdown_release_retiring_writer(self) -> None:
        for shutdown in (False, True):
            with self.subTest(shutdown=shutdown):
                local, peer = self.pair()
                self.state.add_pending_connection(self.onion, local, b'')
                release = self.pause(local)
                writer = self.state._socket_writers[local]
                with patch.object(Constants, 'SOCKET_WRITER_FLUSH_TIMEOUT_SEC', 0.1):
                    self.assertIsNotNone(
                        self.client.request(
                            RejectCommand(self.onion), ConnectionRejectedEvent
                        )
                    )
                if shutdown:
                    self.state.abort_all_sockets()
                self.assertTrue(writer._closed.wait(2))
                release.set()
                self.retired(local, writer)
                self.assertEqual(peer.recv(4096), b'')

    def test_reject_oversized_final_admission_retires_exact_writer(self) -> None:
        local, peer = self.pair()
        self.state.add_pending_connection(self.onion, local, b'')
        with patch.object(Constants, 'MAX_STREAM_BYTES', 8):
            release = self.pause(local)
        writer = self.state._socket_writers[local]
        self.assertIsNotNone(
            self.client.request(RejectCommand(self.onion), ConnectionRejectedEvent)
        )
        release.set()
        self.retired(local, writer)
        self.assertEqual(peer.recv(4096), b'')

    def test_timeout_registry_retirement_waits_for_physical_descriptor_close(
        self,
    ) -> None:
        local, peer = self.pair()
        self.state.add_pending_connection(self.onion, local, b'')
        release_writer = self.pause(local)
        writer = self.state._socket_writers[local]
        closing, release_close, failed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self.addCleanup(release_close.set)
        physical_close = socket.socket.close
        failure_callback = writer._on_failure

        def observe_failure(conn: socket.socket, error: Exception) -> None:
            if failure_callback is not None:
                failure_callback(conn, error)
            failed.set()

        writer._on_failure = observe_failure

        def close(conn: socket.socket) -> None:
            if conn is local:
                closing.set()
                self.assertTrue(release_close.wait(5))
            physical_close(conn)

        with (
            patch.object(socket.socket, 'close', close),
            patch.object(Constants, 'SOCKET_WRITER_FLUSH_TIMEOUT_SEC', 0.1),
        ):
            self.assertIsNotNone(
                self.client.request(RejectCommand(self.onion), ConnectionRejectedEvent)
            )
            self.assertTrue(closing.wait(2))
            release_writer.set()
            self.assertTrue(failed.wait(2))
            writer._thread.join(0.1)
            self.assertTrue(writer._thread.is_alive())
            self.assertIs(self.state._socket_writers.get(local), writer)
            self.assertIsNotNone(self.client.runtime_snapshot())
            release_close.set()
            self.retired(local, writer)
        self.assertEqual(peer.recv(4096), b'')


class RemainingGeneratedReferenceTests(unittest.TestCase):
    """Freshness remains byte-exact and distinct from second-pass determinism."""

    def test_semantically_stale_and_nondeterministic_outputs_are_distinguished(
        self,
    ) -> None:
        path = Path('deliberately-stale.json')
        for original, first, second, diagnostic in (
            (
                b'{"generation": 1}\n',
                b'{"generation": 2}\n',
                b'{"generation": 2}\n',
                'stale=True, non-deterministic=False',
            ),
            (
                b'{"generation": 1}\n',
                b'{"generation": 1}\n',
                b'{"generation": 2}\n',
                'stale=False, non-deterministic=True',
            ),
            (
                b'{"generation": 1}\r\n',
                b'{"generation": 1}\n',
                b'{"generation": 1}\n',
                'stale=True, non-deterministic=False',
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                output = io.StringIO()
                with (
                    patch.object(
                        validate_generated_docs, 'GENERATED_ARTIFACT_PATHS', (path,)
                    ),
                    patch.object(validate_generated_docs, 'run_generators'),
                    patch.object(
                        validate_generated_docs,
                        'generated_artifacts',
                        side_effect=[
                            {path: data} for data in (original, first, second)
                        ],
                    ),
                    redirect_stdout(output),
                ):
                    self.assertEqual(validate_generated_docs.main(), 1)
                self.assertIn(diagnostic, output.getvalue())
