"""Exercises GUI bootstrap through a real public SDK loopback transport."""

import json
import socket
import ssl
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock
from private_fixtures import PrivateTemporaryDirectory
from metor.data.profile.ipc_identity import daemon_tls_context, read_daemon_certificate

from metor.client import (
    FrontendProfileState,
    FrontendBootstrapResult,
    FrontendLaunchContext,
    OneUseSecretProvider,
    build_session_auth_proof,
)
from metor.core.api import (
    AuthRequiredEvent,
    InitEvent,
    IpcEvent,
    RetainedMessagesEvent,
    RuntimeSnapshotEvent,
    SessionAuthenticatedEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.versioning import IPC_PROTOCOL_MIN_SUPPORTED, IPC_PROTOCOL_VERSION


class BootstrapTransportTests(unittest.TestCase):
    """Scripted peer evidence is distinct from actual Core/Tor integration."""

    def test_expired_tls_deadline_preserves_already_buffered_data(self) -> None:
        from metor.shared.ipc_tls import authenticate_daemon

        profile = Path(self.enterContext(PrivateTemporaryDirectory()))
        tls = daemon_tls_context(profile)
        tls.sslsocket_class = ssl.SSLSocket
        remote, local = socket.socketpair()
        self.addCleanup(remote.close)
        self.addCleanup(local.close)
        remote.settimeout(3)
        local.settimeout(3)

        def serve() -> None:
            with tls.wrap_socket(remote, server_side=True) as stream:
                stream.sendall(b'ab')

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        with authenticate_daemon(local, read_daemon_certificate(profile)) as client:
            self.assertEqual(client.recv(1), b'a')
            with self.assertRaises(TimeoutError):
                client.read_before(1, 0)
            self.assertEqual(client.recv(1), b'b')
        worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_wrong_daemon_certificate_rejects_socket_before_prompt(self) -> None:
        """A different valid profile listener cannot obtain the selected profile's credentials."""
        from metor.client import MetorClient

        expected = Path(self.enterContext(PrivateTemporaryDirectory()))
        other = Path(self.enterContext(PrivateTemporaryDirectory()))
        daemon_tls_context(expected)
        tls = daemon_tls_context(other)
        provider = Mock()
        listener = self.enterContext(socket.socket())
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(3)
        finished = threading.Event()

        def serve() -> None:
            try:
                raw, _ = listener.accept()
                with raw, tls.wrap_socket(raw, server_side=True):
                    pass
            except ssl.SSLError:
                pass
            finally:
                finished.set()

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        client = MetorClient(
            listener.getsockname()[1],
            timeout=2,
            daemon_certificate=read_daemon_certificate(expected),
            auth_provider=provider,
        )
        self.addCleanup(client.disconnect)
        self.assertIsNone(client.bootstrap())
        self.assertTrue(finished.wait(3))
        worker.join(3)
        self.assertEqual(provider.mock_calls, [])

    def test_password_prompt_subscription_snapshot_and_inventory_over_sdk(self) -> None:
        """Graphical interaction supplies SDK auth without terminal prompts."""
        challenge, salt = '11' * 32, '22' * 16
        expected = build_session_auth_proof('test-password', challenge, salt)
        commands: list[str] = []
        errors: list[Exception] = []
        finished = threading.Event()
        profile = Path(self.enterContext(PrivateTemporaryDirectory()))
        tls = daemon_tls_context(profile)
        tls.sslsocket_class = ssl.SSLSocket
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(5)

            def serve() -> None:
                """Returns strict correlated DTOs for one isolated test client."""
                authenticated = False
                try:
                    raw, _address = server.accept()
                    connection = tls.wrap_socket(raw, server_side=True)
                    with connection, connection.makefile('rwb') as stream:
                        connection.settimeout(5)
                        while line := stream.readline():
                            command = json.loads(line)
                            kind = command['command_type']
                            commands.append(kind)
                            response: IpcEvent
                            if kind == 'init':
                                response = (
                                    InitEvent(
                                        IPC_PROTOCOL_VERSION,
                                        IPC_PROTOCOL_VERSION,
                                        IPC_PROTOCOL_MIN_SUPPORTED,
                                        capabilities=[
                                            'runtime_snapshot',
                                            'retained_message_inventory',
                                        ],
                                    )
                                    if authenticated
                                    else AuthRequiredEvent(challenge, salt)
                                )
                            elif kind == 'authenticate_session':
                                self.assertEqual(command['proof'], expected)
                                authenticated = True
                                response = SessionAuthenticatedEvent()
                            elif kind == 'register_live_consumer':
                                continue
                            elif kind == 'get_runtime_snapshot':
                                response = RuntimeSnapshotEvent(
                                    'test', 'onion', epoch='test-epoch', revision=1
                                )
                            elif kind == 'list_retained_messages':
                                response = RetainedMessagesEvent(
                                    epoch='test-epoch', revision=1
                                )
                            else:
                                raise AssertionError('Unexpected command: ' + kind)
                            response.request_id = command.get('request_id')
                            stream.write((response.to_json() + '\n').encode())
                            stream.flush()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            host = Mock()
            host.profile_state.return_value = FrontendProfileState(
                'test', True, False, True
            )
            host.bootstrap.return_value = FrontendBootstrapResult(
                'test',
                False,
                server.getsockname()[1],
                False,
                OneUseSecretProvider(None),
                Mock(),
                True,
                daemon_certificate=read_daemon_certificate(profile),
            )
            controller = GuiController(FrontendLaunchContext('test', host))
            try:
                self.assertTrue(controller.open_profile())
                bridge = controller.interactions
                with bridge._condition:
                    self.assertTrue(
                        bridge._condition.wait_for(
                            lambda: bridge._prompt is not None, timeout=5
                        )
                    )
                self.assertTrue(controller.state.covered)
                self.assertTrue(controller.state.busy)
                with bridge._condition:
                    bridge.answer('test-password')
                    self.assertIsNone(bridge.prompt)
                    bridge.answer('ignored-repeat')
                worker = controller._worker
                assert worker is not None
                worker.join(5)
                self.assertFalse(worker.is_alive())
                controller.poll()
                self.assertFalse(controller.state.covered)
                snapshot = controller.state.snapshot
                assert snapshot is not None
                self.assertEqual(snapshot.epoch, 'test-epoch')
                self.assertEqual(
                    commands,
                    [
                        'init',
                        'authenticate_session',
                        'init',
                        'register_live_consumer',
                        'get_runtime_snapshot',
                        'list_retained_messages',
                    ],
                )
            finally:
                controller.close()
                self.assertTrue(finished.wait(5))
                thread.join(5)
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
