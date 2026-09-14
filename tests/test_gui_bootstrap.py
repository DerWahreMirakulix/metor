"""Exercises GUI bootstrap through a real public SDK loopback transport."""

import json
import socket
import threading
import unittest
from unittest.mock import Mock

from metor.client import (
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


class BootstrapTransportTests(unittest.TestCase):
    """Scripted peer evidence is distinct from actual Core/Tor integration."""

    def test_password_prompt_subscription_snapshot_and_inventory_over_sdk(self) -> None:
        """Graphical interaction supplies SDK auth without terminal prompts."""
        challenge, salt = '11' * 32, '22' * 16
        expected = build_session_auth_proof('test-password', challenge, salt)
        commands: list[str] = []
        errors: list[Exception] = []
        finished = threading.Event()
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(5)

            def serve() -> None:
                """Returns strict correlated DTOs for one isolated test client."""
                authenticated = False
                try:
                    connection, _address = server.accept()
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
                                        2,
                                        2,
                                        2,
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
            host.bootstrap.return_value = FrontendBootstrapResult(
                'test',
                False,
                server.getsockname()[1],
                False,
                OneUseSecretProvider(None),
                Mock(),
                True,
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
                bridge.answer('test-password')
                controller._worker.join(5)
                self.assertFalse(controller._worker.is_alive())
                controller.poll()
                self.assertFalse(controller.state.covered)
                self.assertEqual(controller.state.snapshot.epoch, 'test-epoch')
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
