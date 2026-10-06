"""Terminal contact actions preserve chosen display labels across typed IPC."""

import unittest
from unittest.mock import Mock

from metor.core.api import AddContactCommand, RemoveContactCommand, RenameContactCommand
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


if __name__ == '__main__':
    unittest.main()
