"""Terminal call metadata cannot silently authorize audio or select LIVE chat."""

import threading
import unittest
from unittest.mock import Mock

from metor.core.api import (
    AcceptCommand,
    CallAudioEvent,
    CallAudioFrame,
    CallInfo,
    CallReason,
    CallRejectedEvent,
    CallsStateEvent,
    CallState,
    CallStateEvent,
    CancelCallCommand,
    EventType,
    GetCallsCommand,
    HangupCallCommand,
    MuteCallCommand,
    RejectCallCommand,
)
from metor.ui.terminal import Help, Translator
from metor.ui.terminal.chat.command import CommandDispatcher
from metor.ui.terminal.chat.event.handler import EventHandler
from metor.ui.terminal.chat.session import Session


class TerminalCallTests(unittest.TestCase):
    """Exercise the official dispatcher and event router with typed call DTOs."""

    def setUp(self) -> None:
        """Create a text-only Terminal client with an existing chat focus."""
        self.ipc = Mock()
        self.renderer = Mock()
        self.session = Session()
        self.session.focused_alias = 'chat-peer'
        self.dispatcher = CommandDispatcher(self.ipc, self.session, self.renderer)
        self.handler = EventHandler(
            self.ipc,
            self.session,
            self.renderer,
            threading.Event(),
            threading.Event(),
            lambda: 0.0,
            lambda: False,
        )

    def test_start_and_accept_refuse_before_core_authorization(self) -> None:
        """Missing local media support cannot start or accept a silent call."""
        for command in ('/call start peer', '/call accept Call-AB'):
            with self.subTest(command=command):
                self.assertTrue(self.dispatcher.dispatch(command))
                self.assertIn(
                    'local duplex audio adapter',
                    self.renderer.print_message.call_args.args[0],
                )
                self.ipc.send_command.assert_not_called()
                self.assertEqual(self.session.focused_alias, 'chat-peer')

    def test_control_commands_preserve_exact_id_and_do_not_guess_peer(self) -> None:
        """An explicit identity is forwarded unchanged to Core client checks."""
        expected = (
            ('reject', RejectCallCommand),
            ('cancel', CancelCallCommand),
            ('hangup', HangupCallCommand),
            ('mute', MuteCallCommand),
            ('unmute', MuteCallCommand),
        )
        for operation, command_type in expected:
            with self.subTest(operation=operation):
                self.assertTrue(self.dispatcher.dispatch(f'/call {operation} Call-AB'))
                command = self.ipc.send_command.call_args.args[0]
                self.assertIsInstance(command, command_type)
                self.assertEqual(command.call_id, 'Call-AB')
                if isinstance(command, MuteCallCommand):
                    self.assertEqual(command.muted, operation == 'mute')
                self.assertEqual(self.session.focused_alias, 'chat-peer')

        self.ipc.reset_mock()
        self.assertTrue(self.dispatcher.dispatch('/call hangup'))
        self.assertTrue(self.dispatcher.dispatch('/call reject peer extra'))
        self.ipc.send_command.assert_not_called()

    def test_status_query_requests_metadata_only(self) -> None:
        """Listing calls grants neither chat nor any media range read."""
        self.assertTrue(self.dispatcher.dispatch('/calls'))
        self.ipc.send_command.assert_called_once()
        self.assertIsInstance(self.ipc.send_command.call_args.args[0], GetCallsCommand)
        self.handler.handle(CallsStateEvent(calls=[]))
        self.assertEqual(
            self.renderer.print_message.call_args.args[0], 'No telephone calls.'
        )
        self.assertEqual(self.session.focused_alias, 'chat-peer')

    def test_incoming_call_notice_does_not_request_audio_or_accept_chat(self) -> None:
        """An incoming telephone notice offers exact rejection and a capable client."""
        self.handler.handle(
            CallStateEvent(
                call=CallInfo(
                    call_id='Call-AB',
                    alias='caller',
                    peer='caller.onion',
                    state=CallState.INCOMING,
                )
            )
        )
        text = self.renderer.print_message.call_args.args[0]
        self.assertIn('/call reject Call-AB', text)
        self.assertIn('local duplex audio adapter', text)
        self.assertNotIn('/accept', text)
        self.ipc.send_command.assert_not_called()
        self.assertEqual(self.session.focused_alias, 'chat-peer')
        self.assertEqual(self.session.active_connections, [])
        self.assertEqual(self.session.pending_connections, [])

    def test_media_and_rejected_controls_cannot_change_chat_state(self) -> None:
        """Metadata-only Terminal discards unsolicited audio without consuming it."""
        self.handler.handle(
            CallAudioEvent(
                call_id='Call-AB',
                frames=[CallAudioFrame(sequence=0, data='cHJpdmF0ZQ==')],
            )
        )
        self.renderer.print_message.assert_not_called()
        self.ipc.send_command.assert_not_called()
        self.handler.handle(
            CallRejectedEvent(call_id='Call-AB', reason=CallReason.NOT_OWNER)
        )
        self.assertIn('not owner', self.renderer.print_message.call_args.args[0])
        self.assertEqual(self.session.focused_alias, 'chat-peer')

    def test_chat_acceptance_remains_separate_from_call_acceptance(self) -> None:
        """Existing slash commands expressly concern chat, not microphone consent."""
        self.assertTrue(self.dispatcher.dispatch('/accept peer'))
        self.assertIsInstance(self.ipc.send_command.call_args.args[0], AcceptCommand)
        text, _ = Translator.get(EventType.INCOMING_CONNECTION, {'alias': 'peer'})
        self.assertIn('live chat', text)
        self.assertIn('chat messages only', text)
        self.assertIn('no call audio', Help.CHAT_COMMANDS['accept'].description)

    def test_call_identity_is_terminal_safe(self) -> None:
        """A malformed untrusted metadata ID cannot inject terminal controls."""
        self.handler.handle(
            CallStateEvent(call=CallInfo(call_id='bad\x1b[2J', state=CallState.ENDED))
        )
        text = self.renderer.print_message.call_args.args[0]
        self.assertIn(r'bad\x1b[2J', text)
        self.assertNotIn('\x1b', text)


if __name__ == '__main__':
    unittest.main()
