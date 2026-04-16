"""Regression tests for shared UI-side IPC framing and auth-gate helpers."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nacl.pwhash

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import AuthenticateSessionCommand, EventType, IpcEvent, create_event
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.ipc import BufferedIpcEventReader, IpcAuthExchange
from metor.utils import Constants


class _ChunkSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: list[bytes] = chunks

    def recv(self, _size: int) -> bytes:
        if not self._chunks:
            return b''
        return self._chunks.pop(0)


class UiIpcContractTests(unittest.TestCase):
    def test_buffered_event_reader_reassembles_fragmented_ipc_event(self) -> None:
        reader = BufferedIpcEventReader()
        payload = (
            '\n' + create_event(EventType.DAEMON_UNLOCKED).to_json() + '\n'
        ).encode('utf-8')
        sock = _ChunkSocket([payload[:5], payload[5:]])

        event = reader.read_from_socket(sock)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertIs(event.event_type, EventType.DAEMON_UNLOCKED)

    def test_auth_exchange_resends_original_command_after_session_auth(self) -> None:
        sent_commands: list[object] = []
        challenge = 'ab' * Constants.SESSION_AUTH_CHALLENGE_BYTES
        salt = 'cd' * nacl.pwhash.argon2i.SALTBYTES
        exchange = IpcAuthExchange(
            prompt_session_proof=lambda _challenge, _salt: 'proof',
            prompt_unlock_password=lambda: 'secret',
            send_command=sent_commands.append,
        )

        first = exchange.handle(
            IpcEvent.from_dict(
                {
                    'event_type': 'auth_required',
                    'challenge': challenge,
                    'salt': salt,
                }
            )
        )
        second = exchange.handle(create_event(EventType.SESSION_AUTHENTICATED))

        self.assertTrue(first.handled)
        self.assertEqual(len(sent_commands), 1)
        self.assertIsInstance(sent_commands[0], AuthenticateSessionCommand)
        self.assertTrue(second.handled)
        self.assertTrue(second.resend_original_command)

    def test_auth_exchange_returns_terminal_invalid_password_after_limit(self) -> None:
        challenge = 'ab' * Constants.SESSION_AUTH_CHALLENGE_BYTES
        salt = 'cd' * nacl.pwhash.argon2i.SALTBYTES
        exchange = IpcAuthExchange(
            prompt_session_proof=lambda _challenge, _salt: 'proof',
            prompt_unlock_password=lambda: 'secret',
            send_command=lambda _command: None,
        )
        exchange.handle(
            IpcEvent.from_dict(
                {
                    'event_type': 'auth_required',
                    'challenge': challenge,
                    'salt': salt,
                }
            )
        )

        result = None
        for _ in range(Constants.IPC_AUTH_FAILURE_LIMIT):
            result = exchange.handle(
                IpcEvent.from_dict(
                    {
                        'event_type': 'invalid_password',
                        'challenge': challenge,
                        'salt': salt,
                    }
                )
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.handled)
        self.assertIsNotNone(result.terminal_event)
        assert result.terminal_event is not None
        self.assertIs(result.terminal_event.event_type, EventType.INVALID_PASSWORD)

    def test_remote_nuke_requires_typed_self_destruct_success_event(self) -> None:
        remote_pm = Mock()
        remote_pm.is_remote.return_value = True
        proxy = Mock()
        proxy.nuke_daemon_event.return_value = create_event(EventType.INTERNAL_ERROR)

        with (
            patch('metor.ui.cli.handlers.ProfileManager', return_value=remote_pm),
            patch('metor.ui.cli.handlers.CliProxy', return_value=proxy),
            patch('metor.ui.cli.handlers.prompt_text', return_value='n') as prompt_mock,
            patch('builtins.print'),
        ):
            result = CommandHandlers._nuke_remote_profiles(['remote-a'])

        self.assertFalse(result)
        proxy.nuke_daemon_event.assert_called_once()
        prompt_mock.assert_called_once()

    def test_remote_nuke_accepts_typed_self_destruct_success_event(self) -> None:
        remote_pm = Mock()
        remote_pm.is_remote.return_value = True
        proxy = Mock()
        proxy.nuke_daemon_event.return_value = create_event(
            EventType.SELF_DESTRUCT_INITIATED
        )

        with (
            patch('metor.ui.cli.handlers.ProfileManager', return_value=remote_pm),
            patch('metor.ui.cli.handlers.CliProxy', return_value=proxy),
            patch('metor.ui.cli.handlers.prompt_text') as prompt_mock,
            patch('builtins.print'),
        ):
            result = CommandHandlers._nuke_remote_profiles(['remote-a'])

        self.assertTrue(result)
        proxy.nuke_daemon_event.assert_called_once()
        prompt_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
