"""CLI failure outcomes retain nonzero status across local interaction boundaries."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from metor.cli.dispatcher import CliDispatcher
from metor.cli.parser import CliParser
from metor.cli.prompt import PromptAbortedError, prompt_hidden, prompt_text
from metor.data import ProfileManager, ProfileSecurityMode
from metor.utils import Constants


class CliFailureTests(unittest.TestCase):
    """A failed operation cannot become success through terminal formatting."""

    def setUp(self) -> None:
        """Keep metadata reads isolated from any owner's profiles."""
        temporary = TemporaryDirectory(prefix='metor-cli-failures-')
        self.addCleanup(temporary.cleanup)
        data = patch.object(Constants, 'DATA', Path(temporary.name))
        data.start()
        self.addCleanup(data.stop)
        self.profile = ProfileManager('failure-fixture')

    def dispatcher(self, argv: list[str]) -> CliDispatcher:
        """Build the real parser, dispatcher, proxy and output-status boundary."""
        args, extra = CliParser.parse(argv)
        return CliDispatcher(args, extra, self.profile)

    def test_redirected_secrets_never_use_windows_console_or_echo(self) -> None:
        """Original stdin can be a pipe; Windows getpass must never see it."""
        secret = '  unicode-λ-secret  '
        stream = io.StringIO(secret + '\r\n\nlast-secret')
        with (
            patch('sys.stdin', stream),
            patch('sys.__stdin__', stream),
            patch('sys.stderr', io.StringIO()) as output,
            patch(
                'getpass.getpass', side_effect=AssertionError('console input')
            ) as console,
        ):
            self.assertEqual(prompt_hidden('Password: '), secret)
            self.assertEqual(prompt_hidden('Password: '), '')
            self.assertEqual(prompt_hidden('Password: '), 'last-secret')
            with self.assertRaises(PromptAbortedError):
                prompt_hidden('Password: ')
        console.assert_not_called()
        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn('last-secret', output.getvalue())

    def test_terminal_secrets_keep_native_hidden_input(self) -> None:
        """A genuine terminal continues through getpass without an echoed read."""
        stream = Mock()
        stream.isatty.return_value = True
        with (
            patch('sys.stdin', stream),
            patch('getpass.getpass', return_value='private-terminal-secret') as console,
            patch('sys.stderr', io.StringIO()) as output,
        ):
            self.assertEqual(prompt_hidden('Password: '), 'private-terminal-secret')
        console.assert_called_once_with('Password: ')
        stream.readline.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_confirmation_and_unicode_secrets_share_one_utf8_pipe_decoder(self) -> None:
        """Windows ACP wrappers cannot prefetch a following UTF-8 password incorrectly."""
        secret = '  über-λ-secret  '
        with io.TextIOWrapper(
            io.BytesIO(f'yes\n{secret}\r\n{secret}\n'.encode('utf-8')),
            encoding='cp1252',
        ) as stream:
            with (
                patch('sys.stdin', stream),
                patch('sys.stdout', io.StringIO()) as output,
                patch('sys.stderr', io.StringIO()) as errors,
                patch('getpass.getpass', side_effect=AssertionError('console input')),
            ):
                self.assertEqual(prompt_text('Confirm: '), 'yes')
                self.assertEqual(prompt_hidden('Password: '), secret)
                self.assertEqual(prompt_hidden('Confirm password: '), secret)
            self.assertEqual(stream.encoding, 'utf-8')
            self.assertEqual(stream.errors, 'strict')
            self.assertNotIn(secret, output.getvalue() + errors.getvalue())

    def test_pipe_encoding_errors_abort_without_secret_or_decoder_details(self) -> None:
        """Invalid bytes and already-decoded foreign input cannot become credentials."""
        for reader in (prompt_hidden, prompt_text):
            for payload, read_first in (
                (b'private-prefix\xff\n', False),
                ('yes\nüber-secret\n'.encode('utf-8'), True),
            ):
                with self.subTest(reader=reader.__name__, read_first=read_first):
                    with io.TextIOWrapper(
                        io.BytesIO(payload), encoding='cp1252'
                    ) as stream:
                        if read_first:
                            self.assertEqual(stream.readline(), 'yes\n')
                        with (
                            patch('sys.stdin', stream),
                            patch('sys.stdout', io.StringIO()) as output,
                            patch('sys.stderr', io.StringIO()) as errors,
                            self.assertRaises(PromptAbortedError),
                        ):
                            reader('Input: ')
                        text = output.getvalue() + errors.getvalue()
                        self.assertIn('UTF-8', text)
                        self.assertNotIn('private-prefix', text)
                        self.assertNotIn('über-secret', text)
                        self.assertNotIn('UnicodeDecodeError', text)
                        self.assertNotIn('Traceback', text)

    def test_already_read_utf8_pipe_keeps_prefetched_password(self) -> None:
        """A correct decoder is never reconfigured after consuming a prior line."""
        with io.TextIOWrapper(
            io.BytesIO('yes\nüber-secret\n'.encode('utf-8')), encoding='utf-8'
        ) as stream:
            self.assertEqual(stream.readline(), 'yes\n')
            with patch('sys.stdin', stream), patch('sys.stderr', io.StringIO()):
                self.assertEqual(prompt_hidden('Password: '), 'über-secret')

    def test_oversized_pipe_secret_aborts_before_confirmation_or_creation(self) -> None:
        """A bounded read cannot turn a truncated prefix or suffix into a password."""
        dispatcher = self.dispatcher(['profiles', 'add', 'bounded-secret'])
        stream = io.StringIO(
            'x' * (Constants.CLI_PIPE_SECRET_MAX_BYTES * 4) + '\nsuffix-secret\n'
        )
        with (
            patch('sys.stdin', stream),
            patch('sys.stderr', io.StringIO()) as errors,
            patch('sys.stdout', io.StringIO()) as output,
            patch.object(dispatcher._proxy, 'add_profile') as create,
        ):
            self.assertEqual(dispatcher.dispatch(), 1)
        create.assert_not_called()
        self.assertLessEqual(stream.tell(), Constants.CLI_PIPE_SECRET_MAX_BYTES + 2)
        self.assertIn('exceeds the supported limit', errors.getvalue())
        self.assertNotIn('suffix-secret', errors.getvalue() + output.getvalue())

    def test_pipe_secret_limit_counts_utf8_bytes_and_rejects_invalid_text(self) -> None:
        """Multibyte input obeys the byte budget and never leaks invalid text."""
        at_limit = 'λ' * (Constants.CLI_PIPE_SECRET_MAX_BYTES // 2)
        with (
            patch('sys.stdin', io.StringIO(at_limit + '\n')),
            patch('sys.stderr', io.StringIO()),
        ):
            self.assertEqual(prompt_hidden('Password: '), at_limit)
        for secret in (at_limit + 'λ', '\ud800private-surrogate'):
            with self.subTest(length=len(secret)):
                with (
                    patch('sys.stdin', io.StringIO(secret + '\n')),
                    patch('sys.stderr', io.StringIO()) as output,
                    self.assertRaises(PromptAbortedError),
                ):
                    prompt_hidden('Password: ')
                self.assertNotIn('λ', output.getvalue())
                self.assertNotIn('private-surrogate', output.getvalue())

    def test_migration_rejections_never_dispatch_or_exit_successfully(self) -> None:
        """Decline, EOF, empty passwords and mismatch are failed local outcomes."""
        encrypted = ProfileSecurityMode.ENCRYPTED
        plaintext = ProfileSecurityMode.PLAINTEXT
        for current, target, confirmation, passwords, expected in (
            (encrypted, plaintext, 'no', [], 'aborted'),
            (encrypted, plaintext, PromptAbortedError(), [], 'aborted'),
            (encrypted, plaintext, 'yes', [PromptAbortedError()], 'aborted'),
            (encrypted, plaintext, 'yes', [''], 'cannot be empty'),
            (plaintext, encrypted, '', [PromptAbortedError()], 'aborted'),
            (plaintext, encrypted, '', [''], 'cannot be empty'),
            (
                plaintext,
                encrypted,
                '',
                ['first-secret', PromptAbortedError()],
                'aborted',
            ),
            (
                plaintext,
                encrypted,
                '',
                ['first-secret', 'second-secret'],
                'do not match',
            ),
        ):
            with self.subTest(current=current, expected=expected, passwords=passwords):
                dispatcher = self.dispatcher(
                    ['profiles', 'migrate', 'target', '--to', target.value]
                )
                target_profile = Mock()
                target_profile.exists.return_value = True
                target_profile.get_security_mode.return_value = current
                with (
                    patch(
                        'metor.cli.handlers.ProfileManager', return_value=target_profile
                    ),
                    patch('metor.cli.handlers.prompt_text', side_effect=[confirmation]),
                    patch('metor.cli.handlers.prompt_hidden', side_effect=passwords),
                    patch.object(
                        dispatcher._proxy, 'migrate_profile_security'
                    ) as migrate,
                    patch('sys.stdout', io.StringIO()) as output,
                ):
                    self.assertEqual(dispatcher.dispatch(), 1)
                migrate.assert_not_called()
                self.assertIn(expected, output.getvalue())
                self.assertNotIn('first-secret', output.getvalue())
                self.assertNotIn('second-secret', output.getvalue())

    def test_headless_lifecycle_failures_are_safe_nonzero_outcomes(self) -> None:
        """Allocation and incomplete cleanup fail both local routing paths safely."""
        for argv in (
            ['contacts', 'list'],
            ['profiles', 'add', 'target', '--plaintext'],
        ):
            for error_type in (OSError, RuntimeError):
                with self.subTest(argv=argv, error_type=error_type):
                    dispatcher = self.dispatcher(argv)
                    with (
                        patch.object(self.profile, 'exists', return_value=True),
                        patch.object(
                            self.profile, 'get_daemon_port', return_value=None
                        ),
                        patch.object(
                            self.profile, 'supports_password_auth', return_value=False
                        ),
                        patch(
                            'metor.cli.proxy.transport.run_with_headless_daemon',
                            side_effect=error_type(
                                'secret-password /private/profile.db'
                            ),
                        ) as headless,
                        patch('sys.stdout', io.StringIO()) as output,
                    ):
                        self.assertEqual(dispatcher.dispatch(), 1)
                    headless.assert_called_once()
                    text = output.getvalue()
                    self.assertIn('outcome could not be confirmed', text)
                    self.assertNotIn('success', text)
                    self.assertNotIn('secret-password', text)
                    self.assertNotIn('/private/profile.db', text)
                    self.assertNotIn('Traceback', text)


if __name__ == '__main__':
    unittest.main()
