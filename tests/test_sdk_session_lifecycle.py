"""Public SDK authentication failure and connection-state lifecycle regressions."""

import unittest
from unittest.mock import Mock

from metor.client import MetorClient, parse_endpoint
from metor.core.api import (
    AuthenticateSessionCommand,
    AuthRequiredEvent,
    InitCommand,
    InitEvent,
    UnlockCommand,
)
from metor.versioning import IPC_PROTOCOL_MIN_SUPPORTED, IPC_PROTOCOL_VERSION


class SdkSessionLifecycleTests(unittest.TestCase):
    """Keep public initialization evidence confined to its active connection."""

    def test_missing_auth_challenge_ends_request_without_second_wait(self) -> None:
        """A malformed auth gate returns failure instead of becoming a timeout."""
        client = MetorClient(1)
        transport = Mock()
        transport.wait_for_response.side_effect = [
            AuthRequiredEvent(),
            AssertionError('The failed auth gate must not wait again.'),
        ]
        client._ipc = transport
        self.assertIsNone(
            client.request(
                InitCommand(IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED),
                InitEvent,
            )
        )
        transport.wait_for_response.assert_called_once()
        transport.end_request.assert_called_once()

    def test_connection_transitions_clear_previous_initialization(self) -> None:
        """A previous authenticated snapshot cannot describe a replacement socket."""
        for transition in (
            'connect',
            'failed_connect',
            'disconnect',
            '_handle_disconnect',
        ):
            with self.subTest(transition=transition):
                disconnected = Mock()
                client = MetorClient(1, on_disconnect=disconnected)
                client._ipc = Mock()
                client._init_event = InitEvent(
                    IPC_PROTOCOL_VERSION,
                    IPC_PROTOCOL_VERSION,
                    IPC_PROTOCOL_MIN_SUPPORTED,
                    onion='previous-onion',
                    profile='previous-profile',
                )
                client._lease_joined = True
                if transition == 'failed_connect':
                    client._ipc.connect.return_value = False
                    client._ipc._socket = None
                    self.assertFalse(client.connect())
                else:
                    getattr(client, transition)()
                self.assertIsNone(client.init_event)
                self.assertFalse(client._lease_joined)
                if transition == '_handle_disconnect':
                    disconnected.assert_called_once_with()

    def test_refused_concurrent_connect_preserves_active_session(self) -> None:
        """A refused replacement leaves the existing connection's lease intact."""
        client = MetorClient(1)
        client._ipc = Mock()
        client._ipc.connect.return_value = False
        client._init_event = InitEvent(
            IPC_PROTOCOL_VERSION, IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED
        )
        previous = client.init_event
        client._lease_joined = True
        self.assertFalse(client.connect())
        self.assertIs(client.init_event, previous)
        self.assertTrue(client._lease_joined)

    def test_endpoint_validation_rejects_unusable_configuration_early(self) -> None:
        """Ports and address-family mistakes fail before attempting network I/O."""
        for value in (
            False,
            True,
            -1,
            0,
            65536,
            '',
            'host:-1',
            'host:65536',
            '[::1]:5',
        ):
            with self.subTest(endpoint=value), self.assertRaises(ValueError):
                parse_endpoint(value)
        for value, expected in (
            (1, ('127.0.0.1', 1)),
            ('65535', ('127.0.0.1', 65535)),
            (':50051', ('127.0.0.1', 50051)),
            (' example.local:50051 ', ('example.local', 50051)),
        ):
            with self.subTest(endpoint=value):
                self.assertEqual(parse_endpoint(value), expected)

    def test_credential_commands_do_not_disclose_secrets_in_repr(self) -> None:
        """Debugging a command must not accidentally expose passwords or proofs."""
        for command in (
            UnlockCommand('private-password'),
            AuthenticateSessionCommand('private-proof'),
        ):
            with self.subTest(command_type=command.command_type):
                self.assertNotIn('private-', repr(command))
                self.assertIn('private-', command.to_json())


if __name__ == '__main__':
    unittest.main()
