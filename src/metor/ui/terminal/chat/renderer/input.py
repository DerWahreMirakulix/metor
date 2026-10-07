"""
Module handling OS-level terminal input and non-blocking key reads.
"""

import sys
import os
from typing import Optional, List

from metor.ui.terminal.constants import Constants

# Local Package Imports
from metor.ui.terminal.chat.renderer.keys import KeyStream

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore

if os.name != 'nt':
    import select
    import termios
    import tty
    import atexit


class InputHandler:
    """Manages raw terminal inputs and command history."""

    def __init__(self) -> None:
        """
        Initializes the InputHandler and configures the POSIX terminal if required.

        Args:
            None

        Returns:
            None
        """
        self.history: List[str] = []
        self.history_index: int = -1

        self.current_input: str = ''
        self.line_chars: List[str] = []
        self.cursor_index: int = 0
        self._pending_tokens: List[str] = []
        self._key_stream = KeyStream()

        self._init_terminal()

    def _init_terminal(self) -> None:
        """
        Configures the terminal for raw, non-blocking input (POSIX only).

        Args:
            None

        Returns:
            None
        """
        if os.name != 'nt':
            try:
                fd: int = sys.stdin.fileno()
            except (AttributeError, OSError, ValueError):
                print(
                    'Error: interactive chat requires a terminal (stdin has no file descriptor).',
                    file=sys.stderr,
                )
                sys.exit(1)
            tcgetattr = getattr(termios, 'tcgetattr')
            tcsetattr = getattr(termios, 'tcsetattr')
            tcsa_drain = getattr(termios, 'TCSADRAIN')
            setcbreak = getattr(tty, 'setcbreak')
            try:
                old_term_settings = tcgetattr(fd)
            except (getattr(termios, 'error'), OSError) as exc:
                print(
                    f'Error: interactive chat requires a TTY (termios failed: {exc}). '
                    'Run "metor chat" from a terminal.',
                    file=sys.stderr,
                )
                sys.exit(1)

            def _reset_terminal() -> None:
                """
                Restores the original terminal settings upon application exit.

                Args:
                    None

                Returns:
                    None
                """
                tcsetattr(fd, tcsa_drain, old_term_settings)

            atexit.register(_reset_terminal)
            try:
                setcbreak(fd)
                # Preserve CR identity until the streaming decoder normalizes CRLF.
                # Line-discipline translation would turn pasted CRLF into two LFs.
                edit_settings = tcgetattr(fd)
                edit_settings[0] &= ~(
                    getattr(termios, 'ICRNL')
                    | getattr(termios, 'INLCR')
                    | getattr(termios, 'IGNCR')
                )
                tcsetattr(fd, tcsa_drain, edit_settings)
            except (getattr(termios, 'error'), OSError) as exc:
                print(
                    f'Error: interactive chat requires a TTY (setcbreak failed: {exc}). '
                    'Run "metor chat" from a terminal.',
                    file=sys.stderr,
                )
                sys.exit(1)

    def get_char(self) -> Optional[str]:
        """
        Pulls a single character or escape sequence from the standard input buffer.

        Args:
            None

        Raises:
            EOFError: The terminal input stream was closed.

        Returns:
            Optional[str]: The raw character, a parsed SPECIAL tag, or None if empty.
        """
        if self._pending_tokens:
            return self._pending_tokens.pop(0)

        if os.name == 'nt' and msvcrt:
            if getattr(msvcrt, 'kbhit')():
                ch = getattr(msvcrt, 'getwch')()
                if ch in ('\x00', '\xe0'):
                    ch2 = getattr(msvcrt, 'getwch')()
                    if ch2 == 'H':
                        return 'SPECIAL:UP'
                    elif ch2 == 'P':
                        return 'SPECIAL:DOWN'
                    elif ch2 == 'K':
                        return 'SPECIAL:LEFT'
                    elif ch2 == 'M':
                        return 'SPECIAL:RIGHT'
                    return ''
                if ch == '\x0e':
                    return 'SPECIAL:NEWLINE'
                return str(ch)
            return None
        else:
            ready, _, _ = select.select(
                [sys.stdin],
                [],
                [],
                Constants.INPUT_SELECT_TIMEOUT_SEC,
            )
            if not ready:
                return None

            data = os.read(sys.stdin.fileno(), Constants.TCP_BUFFER_SIZE)
            if not data:
                raise EOFError

            self._pending_tokens.extend(self._key_stream.feed(data))
            if self._pending_tokens:
                return self._pending_tokens.pop(0)
            return None

    def process_key(self, ch: str) -> Optional[str]:
        """
        Processes a keyboard event, updating the input buffer and history pointers.

        Args:
            ch (str): The keystroke character or command.

        Returns:
            Optional[str]: The completed input line if enter was pressed, None otherwise.
        """
        if ch.startswith('PASTE:'):
            pasted_text: str = (
                ch[len('PASTE:') :].replace('\r\n', '\n').replace('\r', '\n')
            )
            for char in pasted_text:
                self.line_chars.insert(self.cursor_index, char)
                self.cursor_index += 1

        elif ch.startswith('SPECIAL:'):
            key: str = ch.split(':')[1]
            if key == 'UP':
                if self.history and self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    new_line = self.history[-(self.history_index + 1)]
                else:
                    new_line = self.history[0] if self.history else ''
                self.line_chars = list(new_line)
                self.cursor_index = len(self.line_chars)
            elif key == 'DOWN':
                if self.history_index > 0:
                    self.history_index -= 1
                    new_line = self.history[-(self.history_index + 1)]
                else:
                    self.history_index = -1
                    new_line = ''
                self.line_chars = list(new_line)
                self.cursor_index = len(self.line_chars)
            elif key == 'LEFT':
                if self.cursor_index > 0:
                    self.cursor_index -= 1
            elif key == 'RIGHT':
                if self.cursor_index < len(self.line_chars):
                    self.cursor_index += 1
            elif key == 'HOME':
                self.cursor_index = 0
            elif key == 'END':
                self.cursor_index = len(self.line_chars)
            elif key == 'DELETE':
                if self.cursor_index < len(self.line_chars):
                    del self.line_chars[self.cursor_index]
            elif key == 'NEWLINE':
                self.line_chars.insert(self.cursor_index, '\n')
                self.cursor_index += 1

        elif ch in ('\n', '\r'):
            line: str = ''.join(self.line_chars)
            if line.strip():
                self.history.append(line)
            self.history_index = -1
            self.current_input = ''
            self.line_chars = []
            self.cursor_index = 0
            return line

        elif ch == '\x04':
            if not self.line_chars:
                raise EOFError
            if self.cursor_index < len(self.line_chars):
                del self.line_chars[self.cursor_index]
        elif ch == '\x03':
            raise KeyboardInterrupt
        elif ch in ('\b', '\x7f'):
            if self.cursor_index > 0:
                del self.line_chars[self.cursor_index - 1]
                self.cursor_index -= 1
        else:
            self.line_chars.insert(self.cursor_index, ch)
            self.cursor_index += 1

        self.current_input = ''.join(self.line_chars)
        return None
