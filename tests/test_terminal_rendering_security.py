"""Regression coverage for terminal-safe rendering of untrusted IPC data."""

# ruff: noqa: E402

import json
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.cli.content import render_content as render_cli_content
from metor.cli.translations import Translator as CliTranslator
from metor.core.api import (
    ContactEntry,
    ContactsDataEvent,
    Delivery,
    EventType,
    JsonValue,
    MessageReceivedEvent,
    TextContent,
    TransportStateEvent,
)
from metor.shared import escape_terminal_text
from metor.ui.terminal import Theme
from metor.ui.terminal.chat.models import ChatLine, ChatMessageType
from metor.ui.terminal.chat.presenter import ChatPresenter
from metor.ui.terminal.chat.event.content import handle_content_event
from metor.ui.terminal.chat.event.protocols import EventHandlerProtocol
from metor.ui.terminal.chat.renderer.display import Display
from metor.ui.terminal.content import render_content as render_terminal_content
from metor.ui.terminal.models import AliasPolicy, StatusTone
from metor.ui.terminal.presenter.data import format_contacts
from metor.ui.terminal.presenter.transport import format_transport_state
from metor.ui.terminal.translations import Translator as TerminalTranslator


class TerminalRenderingSecurityTests(unittest.TestCase):
    """Ensures untrusted values cannot inject terminal control sequences."""

    def test_control_characters_are_visible_but_unicode_and_newlines_survive(
        self,
    ) -> None:
        raw = 'Grüße\nESC:\x1b[2J OSC:\x1b]0;owned\x07 C1:\x9b31m NUL:\x00 CR:\r TAB:\t'

        rendered = escape_terminal_text(raw)

        self.assertEqual(rendered.count('\n'), 1)
        self.assertIn('Grüße', rendered)
        self.assertIn(r'ESC:\x1b[2J', rendered)
        self.assertIn(r'OSC:\x1b]0;owned\x07', rendered)
        self.assertIn(r'C1:\x9b31m', rendered)
        self.assertIn(r'NUL:\x00', rendered)
        self.assertIn(r'CR:\x0d', rendered)
        self.assertIn(r'TAB:\x09', rendered)
        for control in ('\x1b', '\x07', '\x9b', '\x00', '\r', '\t'):
            self.assertNotIn(control, rendered)

    def test_content_renderers_escape_without_mutating_wire_content(self) -> None:
        raw = 'literal {alias}\nclear \x1b[2J'
        content = TextContent(raw)
        event = MessageReceivedEvent(
            alias='alice',
            onion='alice.onion',
            delivery=Delivery.LIVE,
            content=content,
            msg_id='m1',
        )

        self.assertEqual(
            render_cli_content(content), r'literal {alias}' + '\n' + r'clear \x1b[2J'
        )
        self.assertEqual(
            render_terminal_content(content),
            r'literal {alias}' + '\n' + r'clear \x1b[2J',
        )
        self.assertEqual(content.text, raw)
        payload = json.loads(event.to_json())
        self.assertEqual(payload['content']['text'], raw)

    def test_real_message_event_projects_safe_text_without_mutating_event(self) -> None:
        raw = 'before \x1b[2J after {alias}'
        event = MessageReceivedEvent(
            alias='alice',
            onion='alice.onion',
            delivery=Delivery.LIVE,
            content=TextContent(raw),
            msg_id='m1',
        )
        renderer = Mock()
        handler = SimpleNamespace(
            _session=SimpleNamespace(focused_alias='alice'),
            _renderer=renderer,
            _ipc=Mock(),
            _remember_peer=Mock(),
            _remember_pushed_live_msg_id=Mock(),
        )

        self.assertTrue(
            handle_content_event(cast(EventHandlerProtocol, handler), event)
        )

        self.assertEqual(
            renderer.print_message.call_args.args[0], r'before \x1b[2J after {alias}'
        )
        self.assertEqual(cast(TextContent, event.content).text, raw)

    def test_remote_message_keeps_literal_placeholder_and_escapes_alias(self) -> None:
        line = ChatLine(
            text='hello {alias} \x1b[2J',
            msg_type=ChatMessageType.REMOTE,
            alias='A\x1b]0;owned\x07lice',
        )

        rendered = ChatPresenter.format_msg(line, '$ ', None)

        self.assertIn('hello {alias} ' + r'\x1b[2J', rendered)
        self.assertIn(r'A\x1b]0;owned\x07lice', rendered)
        self.assertNotIn('\x1b[2J', rendered)
        self.assertNotIn('\x1b]0;owned\x07', rendered)
        self.assertIn(Theme.DARK_GREY, rendered)
        self.assertIn(Theme.RESET, rendered)

    def test_dynamic_status_alias_is_substituted_safely(self) -> None:
        line = ChatLine(
            text="Connected to '{alias}'.",
            msg_type=ChatMessageType.STATUS,
            tone=StatusTone.INFO,
            alias='A\x1b[31mlice',
            alias_policy=AliasPolicy.DYNAMIC,
        )

        rendered = ChatPresenter.format_msg(line, '$ ', None)

        self.assertIn(r"Connected to 'A\x1b[31mlice'.", rendered)
        self.assertNotIn("Connected to '{alias}'.", rendered)
        self.assertNotIn('\x1b[31mlice', rendered)
        self.assertIn(Theme.YELLOW, rendered)

    def test_translation_parameters_are_escaped_before_template_formatting(
        self,
    ) -> None:
        params: dict[str, JsonValue] = {
            'error': 'bad\x1b]0;owned\x07',
            'error_detail': 'detail\x9b31m',
        }

        terminal_text, _ = TerminalTranslator.get(EventType.TOR_START_FAILED, params)
        cli_text, _ = CliTranslator.get(EventType.TOR_START_FAILED, params)

        for rendered in (terminal_text, cli_text):
            self.assertIn(r'bad\x1b]0;owned\x07', rendered)
            self.assertIn(r'detail\x9b31m', rendered)
            self.assertNotIn('\x1b]0;owned\x07', rendered)
            self.assertNotIn('\x9b31m', rendered)

    def test_wrapping_uses_the_same_visible_encoding_as_rendering(self) -> None:
        line = ChatLine(
            text='123\x1b[2J456',
            msg_type=ChatMessageType.REMOTE,
            alias='a\x07',
        )
        display = Display('$ ', lambda _line: line.alias)

        rendered = ChatPresenter.format_msg(line, '$ ', None, line.alias)
        visual_lines = display.get_visual_lines(line, cols=20)

        self.assertIn(r'123\x1b[2J456', rendered)
        self.assertIn(r'From a\x07$ ', rendered)
        self.assertEqual(visual_lines, 2)

    def test_metadata_is_escaped_before_trusted_colors_are_added(self) -> None:
        contacts = ContactsDataEvent(
            saved=[ContactEntry(alias='A\x1b[2J', onion='peer\x07.onion')],
            discovered=[],
            profile='p\x9b31m',
        )
        transport = TransportStateEvent(
            peer='A\x1b]0;owned\x07',
            session_state='connected\x00',
            drop_tunnel={'cached': True, 'opened_at': 'now\r'},
        )

        rendered_contacts = format_contacts(contacts, chat_mode=False)
        rendered_transport = format_transport_state(transport)

        self.assertIn(r'A\x1b[2J', rendered_contacts)
        self.assertIn(r'peer\x07.onion', rendered_contacts)
        self.assertIn(r'p\x9b31m', rendered_contacts)
        self.assertIn(r'A\x1b]0;owned\x07', rendered_transport)
        self.assertIn(r'connected\x00', rendered_transport)
        self.assertIn(r'now\x0d', rendered_transport)
        self.assertIn(Theme.GREEN, rendered_contacts)
        self.assertIn(Theme.CYAN, rendered_transport)

    def test_renderer_owned_cursor_sequences_remain_intact(self) -> None:
        display = Display('$ ', lambda _line: None)
        output = io.StringIO()

        with patch('metor.ui.terminal.chat.renderer.display.sys.stdout', output):
            display.clear_screen()

        self.assertEqual(output.getvalue(), '\x1b[?25h\x1b[2J\x1b[H')


if __name__ == '__main__':
    unittest.main()
