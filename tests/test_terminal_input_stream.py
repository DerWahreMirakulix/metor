"""Regression checks for terminal byte boundaries and finite parser state."""

import unittest
from unittest.mock import patch

from metor.ui.terminal.chat.renderer.input import InputHandler
from metor.ui.terminal.chat.renderer.keys import KeyStream
from metor.ui.terminal.constants import Constants


class TerminalInputStreamTests(unittest.TestCase):
    """Verify semantic input independently of read splitting and terminal hardware."""

    def setUp(self) -> None:
        """Create only the presentation input buffer; process tests own actual termios."""
        with patch.object(InputHandler, '_init_terminal'):
            self.input = InputHandler()
        self.stream = KeyStream()

    def feed(self, data: bytes) -> list[str]:
        """Pass actual decoder tokens through the unchanged input editing contract."""
        completed: list[str] = []
        for token in self.stream.feed(data):
            outcome = self.input.process_key(token)
            if outcome is not None:
                completed.append(outcome)
        return completed

    def test_split_utf8_is_exact_and_invalid_utf8_is_visible(self) -> None:
        """A split code point survives while malformed bytes become visible replacement."""
        self.assertEqual(self.feed(b'Gr\xc3'), [])
        self.assertEqual(self.feed(b'\xbc\xc3\x9fe\xff\r'), ['Grüße\ufffd'])

    def test_split_paste_never_submits_and_retains_only_delimiter_prefix(self) -> None:
        """Fragmented paste boundaries and embedded newlines require explicit Enter."""
        for chunk in (b'\x1b[20', b'0~one\ntwo\x1b[20', b'1~'):
            self.assertEqual(self.feed(chunk), [])
        self.assertEqual(self.input.current_input, 'one\ntwo')
        self.assertEqual(self.feed(b'\r'), ['one\ntwo'])
        for chunk in (b'\x1b[200~', b'x' * Constants.TCP_BUFFER_SIZE, b'\x1b[20'):
            self.assertEqual(self.feed(chunk), [])
            self.assertLess(len(self.stream._paste_suffix), len('\x1b[201~'))
        self.assertEqual(len(self.input.current_input), Constants.TCP_BUFFER_SIZE)

    def test_split_arrows_and_chunked_backspace_edit_text(self) -> None:
        """Editing keys keep their semantics when adjacent text shares an OS read."""
        self.assertEqual(self.feed(b'arw\x1b['), [])
        self.assertEqual(self.feed(b'Do\r'), ['arow'])
        self.assertEqual(self.feed(b'correctx\x7f\r'), ['correct'])
        self.assertEqual(self.feed(b'ac\x1b[Hb\x1b[3~\x1b[Fd\r'), ['bcd'])

    def test_paste_crlf_is_one_newline_across_every_read_boundary(self) -> None:
        """CRLF is canonicalized without losing blank lines or submitting pasted text."""
        data = b'\x1b[200~one\r\ntwo\r\n\r\nthree\rfour\n\nfive\r\x1b[201~'
        expected = 'one\ntwo\n\nthree\nfour\n\nfive\n'
        for split in range(len(data) + 1):
            with self.subTest(split=split):
                self.stream = KeyStream()
                self.assertEqual(self.feed(data[:split]), [])
                self.assertEqual(self.feed(data[split:]), [])
                self.assertEqual(self.input.current_input, expected)
                self.assertEqual(self.feed(b'\r'), [expected])

    def test_incomplete_and_unknown_csi_are_bounded_and_do_not_become_text(
        self,
    ) -> None:
        """Unknown terminal keys are ignored and a partial CSI cannot grow indefinitely."""
        self.feed(b'keep\x1b[15~')
        self.assertEqual(self.input.current_input, 'keep')
        self.feed(b'\x1b[' + b'1' * (Constants.INPUT_ESCAPE_SEQUENCE_CHARS - 2))
        self.assertEqual(self.stream._escape, '')
        self.assertEqual(self.input.current_input, 'keep')

    def test_enter_and_multiline_shortcuts_have_distinct_effects(self) -> None:
        """Ctrl-N and Alt-Enter insert lines; repeated Enter tokens are preserved."""
        self.assertEqual(self.feed(b'one\x0etwo\x1b\rthree\r'), ['one\ntwo\nthree'])
        self.stream = KeyStream()
        self.assertEqual(self.feed(b'\n\n'), ['', ''])
        self.assertEqual(self.feed(b'\r'), [''])
        self.assertEqual(self.feed(b'\n'), [])

    def test_ctrl_d_deletes_at_cursor_and_only_empty_input_exits(self) -> None:
        """EOF never implicitly submits existing text and follows normal editor deletion."""
        self.feed(b'abc\x1b[D\x04')
        self.assertEqual(self.input.current_input, 'ab')
        self.feed(b'\x04')
        self.assertEqual(self.input.current_input, 'ab')
        self.feed(b'\x7f\x7f')
        with self.assertRaises(EOFError):
            self.feed(b'\x04')


if __name__ == '__main__':
    unittest.main()
