"""CLI failure outcomes retain nonzero status across local interaction boundaries."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from metor.cli.dispatcher import CliDispatcher
from metor.cli.parser import CliParser
from metor.cli.prompt import PromptAbortedError
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
