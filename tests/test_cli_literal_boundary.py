"""End-to-end CLI grammar and dispatcher tests for the literal boundary."""

import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metor.cli.dispatcher import CliDispatcher
from metor.cli.entry import run_cli
from metor.cli.handlers import CommandHandlers
from metor.cli.parser import CliParser
from metor.data import ProfileManager, ProfileSecurityMode
from metor.utils import Constants


class CliLiteralBoundaryTests(unittest.TestCase):
    """Proves that only grammar-produced flags select optional behavior."""

    def setUp(self) -> None:
        """Creates one isolated profile root without touching owner data."""
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self._data_patch = patch.object(
            Constants,
            'DATA',
            Path(self._temp.name) / 'metor-data',
        )
        self._data_patch.start()
        self.addCleanup(self._data_patch.stop)
        self.profile = ProfileManager('literal-boundary')

    def dispatcher(self, argv: list[str]) -> tuple[CliDispatcher, argparse.Namespace]:
        """Parses an invocation and builds its real dispatcher."""
        args, extra = CliParser.parse(argv)
        return CliDispatcher(args, extra, self.profile), args

    def test_purge_literal_and_unknown_options_fail_before_operation(self) -> None:
        """Literal or unknown option spellings never authorize remote purge."""
        for argv in (
            ['purge', '--', '--nuke-remote'],
            ['purge', '--unknown'],
            ['purge', '--nuke'],
        ):
            with self.subTest(argv=argv):
                dispatcher, _args = self.dispatcher(argv)
                with (
                    patch.object(CommandHandlers, 'handle_purge') as operation,
                    patch('sys.stdout', io.StringIO()),
                ):
                    self.assertEqual(dispatcher.dispatch(), 1)
                operation.assert_not_called()

    def test_regular_purge_option_is_interpreted_exactly_once(self) -> None:
        """The registered pre-boundary option reaches only the final operation."""
        dispatcher, args = self.dispatcher(['purge', '--nuke-remote'])
        self.assertTrue(args.nuke_remote)
        with patch.object(CommandHandlers, 'handle_purge') as operation:
            self.assertEqual(dispatcher.dispatch(), 0)
        operation.assert_called_once_with(True)

    def test_purge_help_exits_without_profile_or_operation(self) -> None:
        """The real entry help path remains side-effect free."""
        with (
            patch(
                'metor.cli.entry.ProfileManager',
                side_effect=AssertionError('profile side effect'),
            ),
            patch.object(CommandHandlers, 'handle_purge') as operation,
            patch('sys.stdout', io.StringIO()) as output,
        ):
            self.assertEqual(run_cli(['purge', '--help']), 0)
        operation.assert_not_called()
        self.assertIn('metor purge', output.getvalue())

    def test_send_literals_reach_the_final_operation_verbatim(self) -> None:
        """Help, retired mode, and a second separator remain message text."""
        for literal_tokens, expected in (
            (['--help'], '--help'),
            (['--daemon-child'], '--daemon-child'),
            (['--', '--help'], '-- --help'),
        ):
            with self.subTest(literal_tokens=literal_tokens):
                dispatcher, _args = self.dispatcher(
                    ['send', 'alice', '--', *literal_tokens]
                )
                with (
                    patch.object(
                        dispatcher._proxy,
                        'send_drop',
                        return_value='sent',
                    ) as operation,
                    patch('sys.stdout', io.StringIO()),
                ):
                    self.assertEqual(dispatcher.dispatch(), 0)
                operation.assert_called_once_with('alice', expected)

    def test_nested_message_and_history_flags_respect_literal_boundary(self) -> None:
        """Nested typed flags differ from same-spelled literal targets."""
        message_cases = (
            (['messages', 'clear', '--non-contacts'], None, True),
            (
                ['messages', 'clear', '--', '--non-contacts'],
                '--non-contacts',
                False,
            ),
        )
        for argv, target, enabled in message_cases:
            with self.subTest(argv=argv):
                dispatcher, _args = self.dispatcher(argv)
                with (
                    patch.object(
                        dispatcher._proxy,
                        'clear_messages',
                        return_value='cleared',
                    ) as operation,
                    patch('sys.stdout', io.StringIO()),
                ):
                    self.assertEqual(dispatcher.dispatch(), 0)
                operation.assert_called_once_with(target, enabled)

        history_cases = (
            (['history', 'show', '--raw'], None, True),
            (['history', 'show', '--', '--raw'], '--raw', False),
        )
        for argv, target, enabled in history_cases:
            with self.subTest(argv=argv):
                dispatcher, _args = self.dispatcher(argv)
                with (
                    patch.object(
                        dispatcher._proxy,
                        'get_history',
                        return_value='history',
                    ) as operation,
                    patch('sys.stdout', io.StringIO()),
                ):
                    self.assertEqual(dispatcher.dispatch(), 0)
                operation.assert_called_once_with(target, None, raw=enabled)

    def test_nested_profile_flags_are_typed_and_literals_are_rejected(self) -> None:
        """Profile migration/removal no longer scan positional strings as flags."""
        dispatcher, args = self.dispatcher(
            ['profiles', 'migrate', 'alice', '--to', 'plaintext']
        )
        self.assertEqual(args.migration_target, 'plaintext')
        with (
            patch.object(
                CommandHandlers,
                'handle_profile_security_migration',
                return_value='migrated',
            ) as operation,
            patch('sys.stdout', io.StringIO()),
        ):
            self.assertEqual(dispatcher.dispatch(), 0)
        operation.assert_called_once_with(
            dispatcher._proxy,
            'alice',
            ProfileSecurityMode.PLAINTEXT,
        )

        dispatcher, args = self.dispatcher(['profiles', 'rm', 'alice', '--nuke-remote'])
        self.assertTrue(args.nuke_remote)
        with (
            patch.object(
                dispatcher._proxy,
                'remove_profile',
                return_value='removed',
            ) as operation,
            patch('sys.stdout', io.StringIO()),
        ):
            self.assertEqual(dispatcher.dispatch(), 0)
        operation.assert_called_once_with(
            'alice',
            active_profile='literal-boundary',
        )

        for argv in (
            ['profiles', 'migrate', 'alice', '--', '--to', 'plaintext'],
            ['profiles', 'rm', 'alice', '--', '--nuke-remote'],
        ):
            with self.subTest(argv=argv):
                dispatcher, _args = self.dispatcher(argv)
                with (
                    patch.object(
                        CommandHandlers,
                        'handle_profile_security_migration',
                    ) as migrate,
                    patch.object(dispatcher._proxy, 'remove_profile') as remove,
                    patch('sys.stdout', io.StringIO()),
                ):
                    self.assertEqual(dispatcher.dispatch(), 1)
                migrate.assert_not_called()
                remove.assert_not_called()

    def test_unknown_nested_option_fails_before_operation(self) -> None:
        """Pre-boundary unknown options do not become option-looking targets."""
        dispatcher, _args = self.dispatcher(
            ['messages', 'clear', '--not-a-real-option']
        )
        with (
            patch.object(dispatcher._proxy, 'clear_messages') as operation,
            patch('sys.stdout', io.StringIO()),
        ):
            self.assertEqual(dispatcher.dispatch(), 1)
        operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
