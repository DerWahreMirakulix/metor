"""Regression tests for shared UI-side IPC framing and auth-gate helpers."""

# ruff: noqa: E402

import socket
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
    IpcCommand,
    IpcEvent,
    create_event,
)
from metor.data import ProfileManager
from metor.data.settings import SettingKey
from metor.ui.cli.ipc.request import IpcRequestSession
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.ipc import BufferedIpcEventReader, IpcAuthExchange
from metor.ui import get_session_auth_prompt
from metor.utils import Constants


class _ChunkSocket:
    """
    Provides a chunk socket helper for test scenarios.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        """
        Initializes the chunk socket helper.

        Args:
            chunks (list[bytes]): The chunks.

        Returns:
            None
        """

        self._chunks: list[bytes] = chunks

    def recv(self, _size: int) -> bytes:
        """
        Returns the next buffered payload chunk.

        Args:
            _size (int): The size.

        Returns:
            bytes: The computed return value.
        """

        if not self._chunks:
            return b''
        return self._chunks.pop(0)


class _RequestSessionSocket:
    """
    Provides a request session socket helper for test scenarios.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        """
        Initializes the request session socket helper.

        Args:
            chunks (list[bytes]): The chunks.

        Returns:
            None
        """

        self._chunks: list[bytes] = chunks
        self.connected_to: Optional[tuple[str, int]] = None
        self.sent: list[bytes] = []
        self.timeout: Optional[float] = None

    def __enter__(self) -> '_RequestSessionSocket':
        """
        Enters the helper context manager.

        Args:
            None

        Returns:
            '_RequestSessionSocket': The computed return value.
        """

        return self

    def __exit__(self, *args: object) -> None:
        """
        Exits the helper context manager.

        Args:
            *args (object): Extra args values.

        Returns:
            None
        """

        del args
        return None

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeout = timeout

    def connect(self, address: tuple[str, int]) -> None:
        """
        Captures the requested connection target.

        Args:
            address (tuple[str, int]): The address.

        Returns:
            None
        """

        self.connected_to = address

    def recv(self, _size: int) -> bytes:
        """
        Returns the next buffered payload chunk.

        Args:
            _size (int): The size.

        Returns:
            bytes: The computed return value.
        """

        if not self._chunks:
            return b''
        return self._chunks.pop(0)

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.sent.append(payload)


class _RequestSessionConfig:
    """
    Provides a request session config helper for test scenarios.
    """

    def get_float(self, _key: Any) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            float: The computed return value.
        """

        return 1.5

    def get_int(self, key: Any) -> int:
        """
        Returns int for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            int: The computed return value.
        """

        if key is SettingKey.LOCAL_AUTH_FAILURE_LIMIT:
            return 3
        return 0


class _RequestSessionProfileManager:
    """
    Provides a request session profile manager helper for test scenarios.
    """

    def __init__(self) -> None:
        """
        Initializes the request session profile manager helper.

        Args:
            None

        Returns:
            None
        """

        self.config: _RequestSessionConfig = _RequestSessionConfig()

    def uses_encrypted_storage(self) -> bool:
        """
        Reports whether the helper uses encrypted storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return True

    def uses_plaintext_storage(self) -> bool:
        """
        Reports whether the helper uses plaintext storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


class _AuthPromptConfig:
    """
    Provides a auth prompt config helper for test scenarios.
    """

    def __init__(self, require_local_auth: bool) -> None:
        """
        Initializes the auth prompt config helper.

        Args:
            require_local_auth (bool): The require local auth.

        Returns:
            None
        """

        self._require_local_auth: bool = require_local_auth

    def get_bool(self, key: Any) -> bool:
        """
        Returns bool for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            bool: The computed return value.
        """

        if key is SettingKey.REQUIRE_LOCAL_AUTH:
            return self._require_local_auth
        return False


class _AuthPromptProfileManager:
    """
    Provides a auth prompt profile manager helper for test scenarios.
    """

    def __init__(self, *, encrypted: bool, require_local_auth: bool) -> None:
        """
        Initializes the auth prompt profile manager helper.

        Args:
            encrypted (bool): The encrypted.
            require_local_auth (bool): The require local auth.

        Returns:
            None
        """

        self.profile_name: str = 'default'
        self.config: _AuthPromptConfig = _AuthPromptConfig(require_local_auth)
        self._encrypted: bool = encrypted

    def is_remote(self) -> bool:
        """
        Reports whether the helper is remote.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False

    def is_daemon_running(self) -> bool:
        """
        Reports whether the helper is daemon running.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False

    def uses_encrypted_storage(self) -> bool:
        """
        Reports whether the helper uses encrypted storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return self._encrypted

    def uses_plaintext_storage(self) -> bool:
        """
        Reports whether the helper uses plaintext storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return not self._encrypted


class UiIpcContractTests(unittest.TestCase):
    """
    Covers UI IPC contract regression scenarios.
    """

    def test_buffered_event_reader_reassembles_fragmented_ipc_event(self) -> None:
        """
        Verifies that buffered event reader reassembles fragmented IPC event.

        Args:
            None

        Returns:
            None
        """

        reader = BufferedIpcEventReader()
        payload = (
            '\n' + create_event(EventType.DAEMON_UNLOCKED).to_json() + '\n'
        ).encode('utf-8')
        sock = _ChunkSocket([payload[:5], payload[5:]])

        event = reader.read_from_socket(cast(socket.socket, sock))

        self.assertIsNotNone(event)
        assert event is not None
        self.assertIs(event.event_type, EventType.DAEMON_UNLOCKED)

    def test_auth_exchange_resends_original_command_after_session_auth(self) -> None:
        """
        Verifies that auth exchange resends original command after session auth.

        Args:
            None

        Returns:
            None
        """

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
        """
        Verifies that request session ignores foreign request events and reuses request ID.

        Args:
            None

        Returns:
            None
        """

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

        def _send_socket_command(sock: socket.socket, command: IpcCommand) -> None:
            sent_commands.append(command)
            sock.sendall((command.to_json() + '\n').encode('utf-8'))

        session = IpcRequestSession(
            cast(ProfileManager, _RequestSessionProfileManager()),
            async_event_types=set(),
            format_event=lambda event: event.event_type.value,
            format_message=lambda message: message,
            prompt_password=lambda _prompt: 'secret',
            send_socket_command=_send_socket_command,
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
        """
        Verifies that auth exchange returns terminal invalid password after limit.

        Args:
            None

        Returns:
            None
        """

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

    def test_auth_exchange_honors_custom_failure_limit(self) -> None:
        """
        Verifies that auth exchange honors the configured failure limit.

        Args:
            None

        Returns:
            None
        """

        challenge = 'ab' * Constants.SESSION_AUTH_CHALLENGE_BYTES
        salt = 'cd' * nacl.pwhash.argon2i.SALTBYTES
        exchange = IpcAuthExchange(
            prompt_session_proof=lambda _challenge, _salt: 'proof',
            prompt_unlock_password=lambda: 'secret',
            send_command=lambda _command: None,
            failure_limit=1,
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

        result = exchange.handle(
            IpcEvent.from_dict(
                {
                    'event_type': 'invalid_password',
                    'challenge': challenge,
                    'salt': salt,
                }
            )
        )

        self.assertTrue(result.handled)
        self.assertIsNotNone(result.terminal_event)
        assert result.terminal_event is not None
        self.assertIs(result.terminal_event.event_type, EventType.INVALID_PASSWORD)

    def test_session_auth_prompt_uses_plaintext_specific_label(self) -> None:
        """
        Verifies that session auth prompt uses plaintext specific label.

        Args:
            None

        Returns:
            None
        """

        prompt = get_session_auth_prompt(
            cast(
                ProfileManager,
                _AuthPromptProfileManager(
                    encrypted=False,
                    require_local_auth=True,
                ),
            )
        )

        self.assertEqual(prompt, 'Enter Session Auth Password: ')

    def test_handle_daemon_prompts_for_plaintext_session_auth_password(self) -> None:
        """
        Verifies that handle daemon prompts for plaintext session auth password.

        Args:
            None

        Returns:
            None
        """

        pm = cast(
            ProfileManager,
            _AuthPromptProfileManager(encrypted=False, require_local_auth=True),
        )

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

    def test_handle_daemon_sanitizes_sensitive_value_errors(self) -> None:
        """
        Verifies that daemon startup sanitizes sensitive local runtime validation errors.

        Args:
            None

        Returns:
            None
        """

        pm = cast(
            ProfileManager,
            _AuthPromptProfileManager(encrypted=True, require_local_auth=True),
        )

        with (
            patch(
                'metor.ui.cli.handlers.prompt_hidden',
                return_value='secret',
            ),
            patch('metor.ui.cli.handlers.configure_daemon_runtime_logging'),
            patch(
                'metor.ui.cli.handlers.run_managed_daemon',
                side_effect=ValueError('/home/yoda/secret/storage.db: invalid state'),
            ),
            patch('builtins.print') as print_mock,
        ):
            CommandHandlers.handle_daemon(pm)

        self.assertEqual(
            print_mock.call_args_list[-1].args[0],
            'Failed to validate local daemon state.',
        )

    def test_remote_nuke_requires_typed_self_destruct_success_event(self) -> None:
        """
        Verifies that remote nuke requires typed self destruct success event.

        Args:
            None

        Returns:
            None
        """

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
        """
        Verifies that remote nuke accepts typed self destruct success event.

        Args:
            None

        Returns:
            None
        """

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
