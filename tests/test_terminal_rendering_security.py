"""Regression coverage for terminal-safe rendering of untrusted IPC data."""

# ruff: noqa: E402

import json
import io
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.cli.content import render_content as render_cli_content
from metor.cli.translations import Translator as CliTranslator
from metor.cli.presenter.shared import format_timestamp_label as cli_timestamp_label
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
from metor.ui.terminal.help import Help as TerminalHelp
from metor.ui.terminal.chat.models import ChatLine, ChatMessageType
from metor.ui.terminal.chat.presenter import ChatPresenter
from metor.ui.terminal.chat.event.content import handle_content_event
from metor.ui.terminal.chat.event.protocols import EventHandlerProtocol
from metor.ui.terminal.chat.renderer.display import Display
from metor.ui.terminal.chat.renderer.engine import Renderer
from metor.ui.terminal.chat.renderer.input import InputHandler
from metor.ui.terminal.content import render_content as render_terminal_content
from metor.ui.terminal.cells import line_end
from metor.ui.terminal.models import AliasPolicy, StatusTone
from metor.ui.terminal.presenter.data import format_contacts
from metor.ui.terminal.presenter.transport import format_transport_state
from metor.ui.terminal.presenter.shared import (
    format_timestamp_label as terminal_timestamp_label,
)
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

    def test_escaped_json_surrogates_are_visible_utf8_safe_data(self) -> None:
        """Malformed Unicode from IPC cannot abort stdout or inject replacement UI."""
        raw = json.loads(r'"before \ud800 after \udfff"')
        rendered = escape_terminal_text(raw)
        self.assertEqual(rendered, r'before \ud800 after \udfff')
        self.assertEqual(rendered.encode('utf-8').decode('utf-8'), rendered)

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

    def test_malformed_timestamp_is_safe_and_cannot_create_a_new_line(self) -> None:
        """Fallback metadata obeys the same control boundary as message content."""
        timestamp = 'bad\x1b]0;title\x07\ncontinued'
        for formatter in (cli_timestamp_label, terminal_timestamp_label):
            with self.subTest(formatter=formatter.__module__):
                rendered = formatter(timestamp)
                self.assertEqual(rendered, r'bad\x1b]0;title\x07\ncontinued')
                self.assertNotIn('\n', rendered)
                self.assertNotIn('\x1b', rendered)

    def test_wrapping_uses_the_same_visible_encoding_as_rendering(self) -> None:
        line = ChatLine(
            text='123\x1b[2J456',
            msg_type=ChatMessageType.REMOTE,
            alias='a\x07',
        )
        rendered = ChatPresenter.format_msg(line, '$ ', None, line.alias)
        visual_lines = line_end(rendered, 20)[0] + 1

        self.assertIn(r'123\x1b[2J456', rendered)
        self.assertIn(r'From a\x07$ ', rendered)
        self.assertEqual(visual_lines, 2)

    def test_status_multiline_wrap_matches_all_visible_tone_prefixes(self) -> None:
        """Status output uses one prefix width for both hanging indent and redraw."""
        for tone in StatusTone:
            with self.subTest(tone=tone):
                line = ChatLine(
                    text='12345\n67890',
                    msg_type=ChatMessageType.STATUS,
                    tone=tone,
                )
                rendered = ChatPresenter.format_msg(line, '$ ', None)
                self.assertIn('\n     67890', rendered)
                self.assertEqual(
                    sum(line_end(row, 10)[0] + 1 for row in rendered.split('\n')), 2
                )

    def test_unicode_width_and_wide_character_wrapping_use_terminal_cells(self) -> None:
        """CJK labels, combining accents and joined emoji agree with cursor and indent."""
        display = Display()
        line = ChatLine('hello\nworld', ChatMessageType.REMOTE, alias='界')
        rendered = ChatPresenter.format_msg(line, '$ ', None)
        self.assertIn('\n' + ' ' * 9 + 'world', rendered)
        # Two-cell glyphs cannot start in the last remaining cell of a row.
        self.assertEqual(display.get_input_visual_lines('a界界', '$ ', 4), 3)
        self.assertEqual(
            display.get_input_visual_lines('e\u0301👩\u200d💻', '$ ', 6), 1
        )
        output = io.StringIO()
        text = 'e\u0301👩\u200d💻'
        with patch('metor.ui.terminal.chat.renderer.display.sys.stdout', output):
            display.redraw_input_area('$ ', text, list(text), len(text), 6)
        self.assertTrue(output.getvalue().endswith('\r\x1b[5C\x1b[?25h'))

    def test_exact_margin_input_materializes_the_cursor_row(self) -> None:
        """Cursor motion after a full row must not return to the start of that row."""
        display = Display()
        self.assertEqual(display.get_input_visual_lines('12345678', '$ ', 10), 2)
        output = io.StringIO()
        with patch('metor.ui.terminal.chat.renderer.display.sys.stdout', output):
            display.redraw_input_area('$ ', '12345678', list('12345678'), 8, 10)
        self.assertEqual(output.getvalue(), '$ 12345678\n\r\x1b[?25h')

    def test_multiline_input_clears_from_the_actual_cursor_row(self) -> None:
        """Editing near HOME cannot erase messages above a multiline draft."""
        for cursor, expected_prefix in (
            (0, '\x1b[?25l\r\x1b[J'),
            (3, '\x1b[?25l\x1b[1A\r\x1b[J'),
        ):
            with self.subTest(cursor=cursor):
                display = Display()
                text = 'a\nb\nc'
                output = io.StringIO()
                with patch('sys.stdout', output):
                    display.redraw_input_area('$ ', text, list(text), cursor, 20)
                    marker = len(output.getvalue())
                    display.redraw_input_area(
                        '$ ', text, list(text), cursor, 20, clear_first=True
                    )
                self.assertTrue(output.getvalue()[marker:].startswith(expected_prefix))

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

    def test_tall_draft_keeps_home_middle_and_end_visible(self) -> None:
        """Scrolling a draft cannot leave the edit cursor pointing at hidden text."""
        text = 'first\nsecond\nthird\nfourth\nfifth'
        for cursor, visible, relative_row, column in (
            (0, '$ first\n  second\n  third', 0, 2),
            (text.index('third'), '  second\n  third\n  fourth', 1, 2),
            (len(text), '  third\n  fourth\n  fifth', 2, 7),
        ):
            with self.subTest(cursor=cursor):
                display = Display()
                output = io.StringIO()
                with patch('sys.stdout', output):
                    display.redraw_input_area(
                        '$ ', text, list(text), cursor, 20, rows=3
                    )
                    frame = output.getvalue()
                    display.clear_input_area()
                self.assertTrue(
                    frame.startswith(visible + '\x1b')
                    or frame.startswith(visible + '\r')
                )
                self.assertTrue(frame.endswith(f'\r\x1b[{column}C\x1b[?25h'))
                self.assertNotIn('\x1b[3A', frame)
                expected_clear = (
                    f'\x1b[{relative_row}A' if relative_row else ''
                ) + '\r\x1b[J'
                self.assertEqual(output.getvalue()[len(frame) :], expected_clear)

    def test_tall_unicode_draft_clips_physical_rows_without_splitting_glyphs(
        self,
    ) -> None:
        """Wide and combined text remains intact at the visible window boundary."""
        text = '界e\u0301👩\u200d💻xyz\nsecond\nthird'
        cursor = text.index('👩')
        output = io.StringIO()
        with patch('sys.stdout', output):
            Display().redraw_input_area('$ ', text, list(text), cursor, 8, rows=2)
        self.assertEqual(
            output.getvalue(),
            '$ 界e\u0301👩\u200d💻x\nyz\x1b[1A\r\x1b[5C\x1b[?25h',
        )

    def test_draft_controls_are_visible_and_wrap_cursor_use_same_encoding(self) -> None:
        """Clipboard controls cannot execute during drafting or shift cursor geometry."""
        raw = 'Grüße\nA\x1b]0;title\x07\x9b2J\tB'
        display = Display()
        columns = 20
        encoded = escape_terminal_text(raw)
        expected_rows = sum(
            max(1, (2 + len(line) + columns - 1) // columns)
            for line in encoded.split('\n')
        )
        self.assertEqual(
            display.get_input_visual_lines(raw, '$ ', columns), expected_rows
        )
        output = io.StringIO()
        cursor_index = raw.index('B')
        with patch('metor.ui.terminal.chat.renderer.display.sys.stdout', output):
            display.redraw_input_area('$ ', raw, list(raw), cursor_index, columns)
        rendered = output.getvalue()
        self.assertIn(encoded.replace('\n', '\n  '), rendered)
        self.assertNotIn('\x1b]0;title\x07', rendered)
        self.assertNotIn('\x9b2J', rendered)
        self.assertNotIn('\t', rendered)
        cursor_line = escape_terminal_text(raw[:cursor_index]).split('\n')[-1]
        column = (2 + len(cursor_line)) % columns
        self.assertTrue(rendered.endswith(f'\r\x1b[{column}C\x1b[?25h'))
        self.assertEqual(raw, 'Grüße\nA\x1b]0;title\x07\x9b2J\tB')

    def test_renderer_owned_cursor_sequences_remain_intact(self) -> None:
        """Only the POSIX decoder receives paste delimiters; cursor controls stay intact."""
        for platform in ('posix', 'nt'):
            with self.subTest(platform=platform):
                display = Display()
                output = io.StringIO()
                with (
                    patch('metor.ui.terminal.chat.renderer.display.os.name', platform),
                    patch('metor.ui.terminal.chat.renderer.display.sys.stdout', output),
                ):
                    display.clear_screen()
                    display.enable_bracketed_paste()
                    display.enable_bracketed_paste()
                    display.restore_cursor()
                    help_text = TerminalHelp.show_chat_help()
                expected = '\x1b[?25h\x1b[2J\x1b[H'
                if platform == 'posix':
                    expected += '\x1b[?2004h\x1b[?2004l'
                    self.assertIn('Ctrl-N or Alt-Enter inserts a newline.', help_text)
                else:
                    self.assertIn('Ctrl-N inserts a newline.', help_text)
                    self.assertNotIn('Alt-Enter', help_text)
                self.assertEqual(output.getvalue(), expected + '\x1b[?25h')

    def test_resize_signal_defers_rendering_until_the_input_loop(self) -> None:
        """SIGWINCH cannot enter a lock or stdout while interrupting another render."""
        renderer = object.__new__(Renderer)
        renderer._resize_pending = False
        renderer._last_cols = 80
        renderer._last_rows = 24
        with patch.object(renderer, 'full_redraw') as redraw:
            lock = threading.Lock()
            with lock:
                renderer._on_resize(0, None)
                renderer._on_resize(0, None)
            redraw.assert_not_called()
            self.assertTrue(renderer._resize_pending)
            with patch(
                'metor.ui.terminal.chat.renderer.engine.shutil.get_terminal_size',
                return_value=SimpleNamespace(columns=40, lines=24),
            ):
                renderer._apply_pending_resize()
                renderer._apply_pending_resize()
            redraw.assert_called_once_with()
            self.assertFalse(renderer._resize_pending)
            self.assertEqual(renderer._last_cols, 40)

    def test_windows_resize_poll_detects_height_and_width_without_a_signal(
        self,
    ) -> None:
        """Windows resize events need no POSIX signal, including height-only changes."""
        renderer = object.__new__(Renderer)
        renderer._resize_pending = False
        renderer._last_cols = 80
        renderer._last_rows = 24
        with (
            patch.object(renderer, 'full_redraw') as redraw,
            patch('metor.ui.terminal.chat.renderer.engine.sys.platform', 'win32'),
            patch(
                'metor.ui.terminal.chat.renderer.engine.shutil.get_terminal_size',
                side_effect=(
                    SimpleNamespace(columns=80, lines=10),
                    SimpleNamespace(columns=40, lines=10),
                    SimpleNamespace(columns=40, lines=10),
                ),
            ),
        ):
            renderer._apply_pending_resize()
            renderer._apply_pending_resize()
            renderer._apply_pending_resize()
        self.assertEqual(redraw.call_count, 2)
        self.assertEqual((renderer._last_cols, renderer._last_rows), (40, 10))

    def test_delivery_update_redraws_with_locked_new_geometry(self) -> None:
        """A DROP label changing line wraps must repaint from a known screen origin."""
        renderer = object.__new__(Renderer)
        renderer._display = Display()
        line = ChatLine('payload', ChatMessageType.SELF, msg_id='message')
        renderer._display.all_msgs.append(line)
        lock_observations: list[bool] = []

        def observe_redraw(_cols: int) -> None:
            """Observe the enclosing synchronization boundary during actual mutation."""
            lock_observations.append(renderer._display.print_lock.locked())
            self.assertTrue(line.is_drop)

        with patch.object(renderer, '_full_redraw_locked', side_effect=observe_redraw):
            renderer.apply_fallback_to_drop(['message'])
        self.assertEqual(lock_observations, [True])

    def test_first_append_uses_current_alias_and_sanitized_prompt(self) -> None:
        """First paint and later redraw resolve the same peer label and prompt text."""
        config = Mock()
        config.get_namespace_str.return_value = '\x1b[2J\n$'
        config.get_namespace_int.return_value = 50
        output = io.StringIO()
        with (
            patch.object(InputHandler, '_init_terminal'),
            patch('metor.ui.terminal.chat.renderer.engine.signal.signal'),
            patch('sys.stdout', output),
        ):
            renderer = Renderer(config)
            renderer.set_alias_resolver(lambda _onion, _fallback: 'Renamed')
            renderer.print_message(
                'hello',
                ChatMessageType.REMOTE,
                alias='Previous',
                peer_onion='peer.onion',
                alias_policy=AliasPolicy.DYNAMIC,
            )
        self.assertIn(r'From Renamed\x1b[2J\n$ ', output.getvalue())
        self.assertNotIn('Previous', output.getvalue())
        self.assertNotIn('\x1b[2J', output.getvalue())


if __name__ == '__main__':
    unittest.main()
