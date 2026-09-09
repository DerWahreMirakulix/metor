"""Regression tests for the canonical raw IPC socket wire contract."""

# ruff: noqa: E402

import json
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.client import (
    MetorClient,
    build_session_auth_proof,
)
from metor.core.api import IpcEvent
from metor.utils import (
    Constants,
    create_session_auth_challenge,
    create_session_auth_salt,
)


class RawClientContractTests(unittest.TestCase):
    """Verifies that a bare TCP socket client can execute the canonical IPC lifecycle."""

    def test_canonical_raw_client_bootstrap_and_session_flow(self) -> None:
        """
        Verifies the complete canonical wire sequence from a raw socket without UI code.

        Args:
            None

        Returns:
            None
        """
        salt: bytes = create_session_auth_salt()
        salt_hex: str = salt.hex()
        challenge: str = create_session_auth_challenge()
        password: str = 'correct-master-password'

        server_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port: int = server_sock.getsockname()[1]

        received_commands: list[dict[str, object]] = []

        def _mock_daemon_worker() -> None:
            """
            Simulates a daemon responding to client handshake and auth commands.

            Args:
                None

            Returns:
                None
            """
            conn, _ = server_sock.accept()
            with conn:
                f_in = conn.makefile('r', encoding='utf-8')
                f_out = conn.makefile('w', encoding='utf-8')

                # Step 1: Client sends InitCommand
                init_line: str = f_in.readline()
                init_cmd: dict[str, object] = json.loads(init_line)
                received_commands.append(init_cmd)

                # Daemon requires session auth first
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'AUTH_REQUIRED',
                            'request_id': init_cmd.get('request_id'),
                            'challenge': challenge,
                            'salt': salt_hex,
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # Step 2: Client sends AuthenticateSessionCommand
                auth_line: str = f_in.readline()
                auth_cmd: dict[str, object] = json.loads(auth_line)
                received_commands.append(auth_cmd)

                # Daemon responds with SessionAuthenticated and InitEvent
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'SESSION_AUTHENTICATED',
                            'request_id': auth_cmd.get('request_id'),
                        }
                    )
                    + '\n'
                )
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'INIT',
                            'request_id': init_cmd.get('request_id'),
                            'onion': 'abcdefghijklmnop7654321',
                            'version': 1,
                            'min_supported': 1,
                            'profile': 'default',
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # Step 3: Client registers live consumer
                consumer_line: str = f_in.readline()
                consumer_cmd: dict[str, object] = json.loads(consumer_line)
                received_commands.append(consumer_cmd)

                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'LIVE_CONSUMER_REGISTERED',
                            'request_id': consumer_cmd.get('request_id'),
                        }
                    )
                    + '\n'
                )
                f_out.flush()

        worker_thread: threading.Thread = threading.Thread(
            target=_mock_daemon_worker, daemon=True
        )
        worker_thread.start()

        # Bare socket client
        client_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.settimeout(5.0)
        client_sock.connect(('127.0.0.1', port))

        with client_sock:
            c_in = client_sock.makefile('r', encoding='utf-8')
            c_out = client_sock.makefile('w', encoding='utf-8')

            # 1. Send InitCommand
            init_req_id: str = 'init-req-001'
            c_out.write(
                json.dumps(
                    {
                        'command_type': 'INIT',
                        'request_id': init_req_id,
                        'protocol_version': Constants.IPC_PROTOCOL_VERSION,
                        'client_version': '0.2.0',
                    }
                )
                + '\n'
            )
            c_out.flush()

            # 2. Receive AuthRequiredEvent
            auth_req_event = json.loads(c_in.readline())
            self.assertEqual(auth_req_event['event_type'], 'AUTH_REQUIRED')
            self.assertEqual(auth_req_event['request_id'], init_req_id)
            self.assertEqual(auth_req_event['challenge'], challenge)

            # 3. Derive proof and authenticate session
            proof: str = build_session_auth_proof(
                password,
                auth_req_event['challenge'],
                auth_req_event['salt'],
            )
            c_out.write(
                json.dumps(
                    {
                        'command_type': 'AUTHENTICATE_SESSION',
                        'request_id': init_req_id,
                        'proof': proof,
                    }
                )
                + '\n'
            )
            c_out.flush()

            # 4. Receive SessionAuthenticatedEvent and InitEvent
            auth_ok_event = json.loads(c_in.readline())
            self.assertEqual(auth_ok_event['event_type'], 'SESSION_AUTHENTICATED')
            init_event = json.loads(c_in.readline())
            self.assertEqual(init_event['event_type'], 'INIT')
            self.assertEqual(init_event['onion'], 'abcdefghijklmnop7654321')

            # 5. Send RegisterLiveConsumerCommand
            consumer_req_id: str = 'consumer-req-002'
            c_out.write(
                json.dumps(
                    {
                        'command_type': 'REGISTER_LIVE_CONSUMER',
                        'request_id': consumer_req_id,
                    }
                )
                + '\n'
            )
            c_out.flush()

            consumer_ok_event = json.loads(c_in.readline())
            self.assertEqual(
                consumer_ok_event['event_type'], 'LIVE_CONSUMER_REGISTERED'
            )

        worker_thread.join(timeout=2.0)
        server_sock.close()

        self.assertEqual(len(received_commands), 3)
        self.assertEqual(received_commands[0]['command_type'], 'INIT')
        self.assertEqual(received_commands[1]['command_type'], 'AUTHENTICATE_SESSION')
        self.assertEqual(received_commands[2]['command_type'], 'REGISTER_LIVE_CONSUMER')

    def test_raw_client_unlock_sequence(self) -> None:
        """
        Verifies the unlock handshake when the daemon starts locked.

        Args:
            None

        Returns:
            None
        """
        server_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port: int = server_sock.getsockname()[1]

        def _mock_daemon_worker() -> None:
            """
            Simulates a daemon responding to an unlock sequence.

            Args:
                None

            Returns:
                None
            """
            conn, _ = server_sock.accept()
            with conn:
                f_in = conn.makefile('r', encoding='utf-8')
                f_out = conn.makefile('w', encoding='utf-8')

                cmd = json.loads(f_in.readline())
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'DAEMON_LOCKED',
                            'request_id': cmd.get('request_id'),
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                unlock_cmd = json.loads(f_in.readline())
                self.assertEqual(unlock_cmd['command_type'], 'UNLOCK')
                self.assertEqual(unlock_cmd['password'], 'secret')

                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'DAEMON_UNLOCKED',
                            'request_id': unlock_cmd.get('request_id'),
                        }
                    )
                    + '\n'
                )
                f_out.flush()

        worker_thread: threading.Thread = threading.Thread(
            target=_mock_daemon_worker, daemon=True
        )
        worker_thread.start()

        client_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.settimeout(5.0)
        client_sock.connect(('127.0.0.1', port))

        with client_sock:
            c_in = client_sock.makefile('r', encoding='utf-8')
            c_out = client_sock.makefile('w', encoding='utf-8')

            c_out.write(
                json.dumps({'command_type': 'INIT', 'request_id': 'req-1'}) + '\n'
            )
            c_out.flush()

            locked_event = json.loads(c_in.readline())
            self.assertEqual(locked_event['event_type'], 'DAEMON_LOCKED')

            c_out.write(
                json.dumps(
                    {
                        'command_type': 'UNLOCK',
                        'request_id': 'req-1',
                        'password': 'secret',
                    }
                )
                + '\n'
            )
            c_out.flush()

            unlocked_event = json.loads(c_in.readline())
            self.assertEqual(unlocked_event['event_type'], 'DAEMON_UNLOCKED')

        worker_thread.join(timeout=2.0)
        server_sock.close()

    def test_metor_client_bootstrap_and_event_streaming(self) -> None:
        """
        Verifies that high-level MetorClient executes bootstrap and event streaming.

        Args:
            None

        Returns:
            None
        """
        salt = create_session_auth_salt().hex()
        challenge = create_session_auth_challenge()
        password = 'test-password'

        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def _mock_daemon() -> None:
            """
            Simulates a daemon responding to MetorClient bootstrap and streaming events.

            Args:
                None

            Returns:
                None
            """
            conn, _ = server_sock.accept()
            with conn:
                f_in = conn.makefile('r', encoding='utf-8')
                f_out = conn.makefile('w', encoding='utf-8')

                # 1. Receive InitCommand
                init_cmd = json.loads(f_in.readline())
                req_id = init_cmd.get('request_id')

                # Require auth
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'auth_required',
                            'request_id': req_id,
                            'challenge': challenge,
                            'salt': salt,
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # 2. Receive AuthenticateSessionCommand
                auth_cmd = json.loads(f_in.readline())
                self.assertEqual(auth_cmd['command_type'], 'authenticate_session')

                # Authenticated -> send SESSION_AUTHENTICATED
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'session_authenticated',
                            'request_id': auth_cmd.get('request_id'),
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # Client resends InitCommand
                resent_init_cmd = json.loads(f_in.readline())
                self.assertEqual(resent_init_cmd['command_type'], 'init')

                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'init',
                            'request_id': req_id,
                            'onion': 'testonionaddress123456789',
                            'version': 1,
                            'min_supported': 1,
                            'profile': 'default',
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # 3. Receive RegisterLiveConsumerCommand
                consumer_cmd = json.loads(f_in.readline())
                self.assertEqual(consumer_cmd['command_type'], 'register_live_consumer')

                # Push an async event to client
                f_out.write(
                    json.dumps(
                        {
                            'event_type': 'connected',
                            'alias': 'alice',
                            'onion': 'aliceonionaddress123456789',
                        }
                    )
                    + '\n'
                )
                f_out.flush()

                # Keep connection alive until client disconnects
                try:
                    f_in.readline()
                except Exception:
                    pass

        worker_thread = threading.Thread(target=_mock_daemon, daemon=True)
        worker_thread.start()

        received_async_events: list[IpcEvent] = []
        event_received_signal = threading.Event()

        class _TestAuthProvider:
            """Test auth provider supplying dummy credentials."""

            def get_unlock_password(self) -> str | None:
                """
                Returns None for unlock password in this test scenario.

                Args:
                    None

                Returns:
                    str | None: None.
                """
                return None

            def get_session_auth_proof(
                self, s_challenge: str, s_salt: str
            ) -> str | None:
                """
                Derives session auth proof for this test scenario.

                Args:
                    s_challenge (str): The challenge issued by the daemon.
                    s_salt (str): The salt issued by the daemon.

                Returns:
                    str | None: The derived proof.
                """
                return build_session_auth_proof(password, s_challenge, s_salt)

        def _on_event(event: IpcEvent) -> None:
            """
            Appends incoming event and signals completion.

            Args:
                event (IpcEvent): The event received.

            Returns:
                None
            """
            received_async_events.append(event)
            event_received_signal.set()

        client = MetorClient(
            endpoint=f'127.0.0.1:{port}',
            auth_provider=_TestAuthProvider(),
            on_event=_on_event,
            timeout=5.0,
        )

        try:
            init_event = client.bootstrap()
            self.assertIsNotNone(init_event)
            assert init_event is not None
            self.assertEqual(init_event.onion, 'testonionaddress123456789')

            registered = client.register_live_consumer()
            self.assertTrue(registered)

            self.assertTrue(event_received_signal.wait(timeout=2.0))
            self.assertEqual(len(received_async_events), 1)
            self.assertEqual(received_async_events[0].event_type.value, 'connected')
        finally:
            client.disconnect()
            worker_thread.join(timeout=2.0)
            server_sock.close()


if __name__ == '__main__':
    unittest.main()
