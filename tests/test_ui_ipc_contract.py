"""Regression tests for shared UI-side IPC framing and auth-gate helpers."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from typing import Any, Optional, cast
from unittest.mock import Mock, patch

import nacl.pwhash

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    AuthenticateSessionCommand,
    EventType,
    InitCommand,
    IpcEvent,
    create_event,
)
from metor.data.settings import SettingKey
from metor.ui.cli.ipc.request import IpcRequestSession
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.ipc import BufferedIpcEventReader, IpcAuthExchange
from metor.ui import get_session_auth_prompt
from metor.utils import Constants


class _ChunkSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: list[bytes] = chunks

    def recv(self, _size: int) -> bytes:
        if not self._chunks:
            return b''
        return self._chunks.pop(0)


class _RequestSessionSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: list[bytes] = chunks
        self.connected_to: Optional[tuple[str, int]] = None
        self.sent: list[bytes] = []
        self.timeout: Optional[float] = None

    def __enter__(self) -> '_RequestSessionSocket':
        return self

    def __exit__(self, *args: object) -> None:
        del args
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple[str, int]) -> None:
        self.connected_to = address

    def recv(self, _size: int) -> bytes:
        if not self._chunks:
            return b''
        return self._chunks.pop(0)

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)


class _RequestSessionConfig:
    def get_float(self, _key: Any) -> float:
        return 1.5


class _RequestSessionProfileManager:
    def __init__(self) -> None:
        self.config: _RequestSessionConfig = _RequestSessionConfig()

    def uses_encrypted_storage(self) -> bool:
        return True

    def uses_plaintext_storage(self) -> bool:
        return False


class _AuthPromptConfig:
    def __init__(self, require_local_auth: bool) -> None:
        self._require_local_auth: bool = require_local_auth

    def get_bool(self, key: Any) -> bool:
        if key is SettingKey.REQUIRE_LOCAL_AUTH:
            return self._require_local_auth
        return False


class _AuthPromptProfileManager:
    def __init__(self, *, encrypted: bool, require_local_auth: bool) -> None:
        self.profile_name: str = 'default'
        self.config: _AuthPromptConfig = _AuthPromptConfig(require_local_auth)
        self._encrypted: bool = encrypted

    def is_remote(self) -> bool:
        return False

    def is_daemon_running(self) -> bool:
        return False

    def uses_encrypted_storage(self) -> bool:
        return self._encrypted

    def uses_plaintext_storage(self) -> bool:
        return not self._encrypted


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
        request_id = 'req-auth-1'
        exchange = IpcAuthExchange(
            prompt_session_proof=lambda _challenge, _salt: 'proof',
            prompt_unlock_password=lambda: 'secret',
            send_command=sent_commands.append,
            request_id=request_id,
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
        self.assertEqual(
            cast(AuthenticateSessionCommand, sent_commands[0]).request_id,
            request_id,
        )
        self.assertTrue(second.handled)
        self.assertTrue(second.resend_original_command)

    def test_request_session_ignores_foreign_request_events_and_reuses_request_id(
        self,
    ) -> None:
        challenge = 'ab' * Constants.SESSION_AUTH_CHALLENGE_BYTES
        salt = 'cd' * nacl.pwhash.argon2i.SALTBYTES
        request_id = 'req-session-1'
        cmd = InitCommand(request_id=request_id)
        sent_commands: list[object] = []
        socket_payload = ''.join(
            event.to_json() + '\n'
            for event in (
                create_event(
                    EventType.RENAME_SUCCESS,
                    {
                        'old_alias': 'before',
                        'new_alias': 'after',
                        'request_id': 'other-request',
                    },
                ),
                create_event(
                    EventType.AUTH_REQUIRED,
                    {
                        'challenge': challenge,
                        'salt': salt,
                        'request_id': request_id,
                    },
                ),
                create_event(
                    EventType.SESSION_AUTHENTICATED,
                    {'request_id': request_id},
                ),
                create_event(EventType.DAEMON_OFFLINE, {'request_id': request_id}),
            )
        ).encode('utf-8')
        fake_socket = _RequestSessionSocket([socket_payload, b''])
        session = IpcRequestSession(
            _RequestSessionProfileManager(),
            async_event_types=set(),
            format_event=lambda event: event.event_type.value,
            format_message=lambda message: message,
            prompt_password=lambda _prompt: 'secret',
            send_socket_command=lambda sock, command: (
                sent_commands.append(command),
                sock.sendall((command.to_json() + '\n').encode('utf-8')),
            )[-1],
        )

        with (
            patch(
                'metor.ui.cli.ipc.request.session.socket.socket',
                return_value=fake_socket,
            ),
            patch(
                'metor.ui.cli.ipc.request.session.prompt_session_auth_proof',
                return_value='proof',
            ),
        ):
            result = session.execute_result(4312, cmd, wait_for_response=True)

        self.assertIsNotNone(result.event)
        assert result.event is not None
        self.assertIs(result.event.event_type, EventType.DAEMON_OFFLINE)
        self.assertEqual(len(sent_commands), 3)
        self.assertIsInstance(sent_commands[0], InitCommand)
        self.assertIsInstance(sent_commands[1], AuthenticateSessionCommand)
        self.assertIsInstance(sent_commands[2], InitCommand)
        self.assertTrue(
            all(
                getattr(command, 'request_id', None) == request_id
                for command in sent_commands
            )
        )
        self.assertEqual(fake_socket.connected_to, ('127.0.0.1', 4312))
        self.assertEqual(fake_socket.timeout, 1.5)

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

    def test_session_auth_prompt_uses_plaintext_specific_label(self) -> None:
        prompt = get_session_auth_prompt(
            _AuthPromptProfileManager(encrypted=False, require_local_auth=True)
        )

        self.assertEqual(prompt, 'Enter Session Auth Password: ')

    def test_handle_daemon_prompts_for_plaintext_session_auth_password(self) -> None:
        pm = _AuthPromptProfileManager(encrypted=False, require_local_auth=True)

        with (
            patch(
                'metor.ui.cli.handlers.prompt_hidden',
                return_value='session-secret',
            ) as prompt_mock,
            patch('metor.ui.cli.handlers.configure_daemon_runtime_logging'),
            patch('metor.ui.cli.handlers.run_managed_daemon') as run_daemon,
            patch('builtins.print'),
        ):
            CommandHandlers.handle_daemon(pm)

        prompt_mock.assert_called_once()
        self.assertEqual(
            prompt_mock.call_args.args[0],
            '\x1b[32mEnter Session Auth Password: \x1b[0m',
        )
        self.assertIsNone(run_daemon.call_args.kwargs['password'])
        self.assertEqual(
            run_daemon.call_args.kwargs['session_auth_password'],
            'session-secret',
        )

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
