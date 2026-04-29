"""
Module handling OS-level terminal input and non-blocking key reads.
"""

import sys
import os
from typing import Optional, List

from metor.utils import Constants

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
            fd: int = sys.stdin.fileno()
            tcgetattr = getattr(termios, 'tcgetattr')
            tcsetattr = getattr(termios, 'tcsetattr')
            tcsa_drain = getattr(termios, 'TCSADRAIN')
            setcbreak = getattr(tty, 'setcbreak')
            old_term_settings = tcgetattr(fd)

            def _reset_terminal() -> None:
                """
                Restores the original terminal settings upon application exit.

                Args:
                    None

                Returns:
                    None
                """
                tcsetattr(fd, tcsa_drain, old_term_settings)

            setcbreak(fd)
            atexit.register(_reset_terminal)

    def get_char(self) -> Optional[str]:
        """
        Pulls a single character or escape sequence from the standard input buffer.

        Args:
            None

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

            data: str = os.read(sys.stdin.fileno(), Constants.TCP_BUFFER_SIZE).decode(
                'utf-8', errors='ignore'
            )
            if not data:
                return None

            self._pending_tokens.extend(self._tokenize_posix_input(data))
            if self._pending_tokens:
                return self._pending_tokens.pop(0)
            return None

    def _tokenize_posix_input(self, data: str) -> List[str]:
        """
        Splits raw POSIX terminal bytes into semantic key or paste tokens.

        Args:
            data (str): The decoded terminal input chunk.

        Returns:
            List[str]: Parsed tokens in processing order.
        """
        tokens: List[str] = []
        index: int = 0
        newline_chars: tuple[str, str] = (
            '\r',
            '\n',
        )
        control_chars: tuple[str, ...] = (
            '\x1b',
            '\r',
            '\n',
            '\x0e',
        )

        while index < len(data):
            if data.startswith('\x1b[200~', index):
                end_index: int = data.find('\x1b[201~', index + len('\x1b[200~'))
                if end_index != -1:
                    pasted_text: str = data[index + len('\x1b[200~') : end_index]
                    if pasted_text:
                        tokens.append(f'PASTE:{pasted_text}')
                    index = end_index + len('\x1b[201~')
                    continue

            if data.startswith('\x1b[A', index):
                tokens.append('SPECIAL:UP')
                index += len('\x1b[A')
                continue
            if data.startswith('\x1b[B', index):
                tokens.append('SPECIAL:DOWN')
                index += len('\x1b[B')
                continue
            if data.startswith('\x1b[C', index):
                tokens.append('SPECIAL:RIGHT')
                index += len('\x1b[C')
                continue
            if data.startswith('\x1b[D', index):
                tokens.append('SPECIAL:LEFT')
                index += len('\x1b[D')
                continue
            if data.startswith('\x1b\r', index) or data.startswith('\x1b\n', index):
                tokens.append('SPECIAL:NEWLINE')
                index += len('\x1b\r')
                continue

            char: str = data[index]
            if char == '\x0e':
                tokens.append('SPECIAL:NEWLINE')
                index += 1
                continue

            if char in newline_chars:
                tokens.append('\n')
                if index + 1 < len(data) and data[index + 1] in newline_chars:
                    index += 2
                else:
                    index += 1
                continue

            if char == '\x1b':
                tokens.append('ESC')
                index += 1
                continue

            text_start: int = index
            while index < len(data) and data[index] not in control_chars:
                index += 1

            text_chunk: str = data[text_start:index]
            if not text_chunk:
                continue

            if len(text_chunk) == 1:
                tokens.append(text_chunk)
            else:
                tokens.append(f'PASTE:{text_chunk}')

        return tokens

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

        elif ch in ('\b', '\x7f'):
            if self.cursor_index > 0:
                del self.line_chars[self.cursor_index - 1]
                self.cursor_index -= 1
        else:
            self.line_chars.insert(self.cursor_index, ch)
            self.cursor_index += 1

        self.current_input = ''.join(self.line_chars)
        return None
