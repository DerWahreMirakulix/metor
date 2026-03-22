"""
Module handling OS-level terminal input and non-blocking key reads.
"""

import sys
import os
from typing import Optional, List

if os.name == 'nt':
    import msvcrt
else:
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
        """
        self.history: List[str] = []
        self.history_index: int = -1

        self.current_input: str = ''
        self.line_chars: List[str] = []
        self.cursor_index: int = 0

        self._init_terminal()

    def _init_terminal(self) -> None:
        """Configures the terminal for raw, non-blocking input (POSIX only)."""
        if os.name != 'nt':
            fd: int = sys.stdin.fileno()
            old_term_settings = termios.tcgetattr(fd)

            def _reset_terminal() -> None:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term_settings)

            tty.setcbreak(fd)
            atexit.register(_reset_terminal)

    def get_char(self) -> Optional[str]:
        """
        Pulls a single character or escape sequence from the standard input buffer.

        Returns:
            Optional[str]: The raw character, a parsed SPECIAL tag, or None if empty.
        """
        if os.name == 'nt':
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ('\x00', '\xe0'):
                    ch2 = msvcrt.getwch()
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
                return ch
            return None
        else:
            ch1 = sys.stdin.read(1)
            if ch1 == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    return {
                        'A': 'SPECIAL:UP',
                        'B': 'SPECIAL:DOWN',
                        'C': 'SPECIAL:RIGHT',
                        'D': 'SPECIAL:LEFT',
                    }.get(ch3, 'SPECIAL:UNKNOWN')
                if ch2 in ('\n', '\r'):
                    return 'SPECIAL:NEWLINE'
                return 'ESC'
            if ch1 == '\x0e':
                return 'SPECIAL:NEWLINE'
            return ch1

    def process_key(self, ch: str) -> bool:
        """
        Processes a keyboard event, updating the input buffer and history pointers.

        Args:
            ch (str): The keystroke character or command.

        Returns:
            bool: True if the enter key was pressed and input is ready, False otherwise.
        """
        if ch.startswith('SPECIAL:'):
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
            return True

        elif ch in ('\b', '\x7f'):
            if self.cursor_index > 0:
                del self.line_chars[self.cursor_index - 1]
                self.cursor_index -= 1
        else:
            self.line_chars.insert(self.cursor_index, ch)
            self.cursor_index += 1

        self.current_input = ''.join(self.line_chars)
        return False
