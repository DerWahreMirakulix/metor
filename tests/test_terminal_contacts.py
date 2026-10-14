"""Terminal contact actions preserve chosen display labels across typed IPC."""

import unittest
from unittest.mock import Mock

from metor.core.api import (
    AddContactCommand,
    ConnectCommand,
    MarkReadCommand,
    RemoveContactCommand,
    RenameContactCommand,
    SwitchCommand,
)
from metor.ui.terminal.chat.command import CommandDispatcher
from metor.ui.terminal.chat.session import Session


class TerminalContactTests(unittest.TestCase):
    """Checks explicit and focused contact commands against the public DTO boundary."""

    def test_chosen_and_existing_display_aliases_keep_their_spelling(self) -> None:
        """Neither new labels nor a captured old label are lowercased by the frontend."""
        ipc, session = Mock(), Session()
        dispatcher = CommandDispatcher(ipc, session, Mock())
        for text, expected in (
            (
                '/contacts add McAlice peer.onion',
                AddContactCommand('McAlice', 'peer.onion'),
            ),
            ('/contacts add Straße', AddContactCommand('Straße')),
            (
                '/contacts rename McAlice McALICE',
                RenameContactCommand('McAlice', 'McALICE'),
            ),
            ('/contacts remove Straße', RemoveContactCommand('Straße')),
        ):
            with self.subTest(text=text):
                self.assertTrue(dispatcher.dispatch(text))
                self.assertEqual(ipc.send_command.call_args.args[0], expected)
        session.focused_alias = 'McAlice'
        self.assertTrue(dispatcher.dispatch('/contacts rename McALICE'))
        self.assertEqual(
            ipc.send_command.call_args.args[0],
            RenameContactCommand('McAlice', 'McALICE'),
        )
        self.assertEqual(session.focused_alias, 'McAlice')

    def test_peer_commands_preserve_alias_spelling(self) -> None:
        """All frontend entry paths pass display identities to the same Core resolver."""
        ipc = Mock()
        dispatcher = CommandDispatcher(ipc, Session(), Mock())
        for text, expected in (
            ('/switch McAlice', SwitchCommand('McAlice')),
            ('/connect Straße', ConnectCommand('Straße')),
            ('/inbox McALICE', MarkReadCommand('McALICE')),
            ('/switch "Alice Smith"', SwitchCommand('Alice Smith')),
            (
                '/contacts rename "Alice Smith" "Mc Alice"',
                RenameContactCommand('Alice Smith', 'Mc Alice'),
            ),
        ):
            with self.subTest(text=text):
                self.assertTrue(dispatcher.dispatch(text))
                self.assertEqual(ipc.send_command.call_args.args[0], expected)

    def test_extra_operands_and_command_prefixes_cannot_trigger_actions(self) -> None:
        """Typos and a multiline pasted command never partially execute a mutation."""
        for text in (
            '/end Alice Bob',
            '/connect Alice\n/end Bob',
            '/accept Alice Bob',
            '/reject Alice Bob',
            '/switch Alice Bob',
            '/fallback Alice Bob',
            '/retunnel Alice Bob',
            '/inbox Alice Bob',
            '/sessions Alice',
            '/transport Alice Bob',
            '/contacts list Alice',
            '/contacts-typo remove Alice',
            '/contacts remove "Alice',
        ):
            with self.subTest(text=text):
                ipc, renderer = Mock(), Mock()
                session = Session()
                dispatcher = CommandDispatcher(ipc, session, renderer)
                recognized = dispatcher.dispatch(text)
                ipc.send_command.assert_not_called()
                self.assertIsNone(session.pending_focus_target)
                self.assertIsNone(session.pending_accept_focus_target)
                if recognized:
                    renderer.print_message.assert_called_once()


if __name__ == '__main__':
    unittest.main()
