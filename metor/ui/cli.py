"""
Module handling non-blocking terminal input, history, and reactive UI rendering for the chat interface.
"""

import shutil
import signal
import sys
import os
import time
import re
import threading
from typing import List, Dict, Any, Optional

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty
    import atexit

from metor.data.settings import Settings
from metor.ui.theme import Theme


class CommandLineInput:
    """Handles non-blocking input with command history and a reactive UI renderer."""

    def __init__(self) -> None:
        """Initializes the CLI renderer and terminal settings."""
        self._initial_prompt: str = f'{Settings.get("prompt_sign")} '
        self._prompt: str = self._initial_prompt
        self._input_history: List[str] = []
        self._history_index: int = -1
        self._current_input: str = ''
        self._all_msgs: List[Dict[str, Any]] = []
        self._current_focus: Optional[str] = None
        self._is_redrawing: bool = False
        self._last_cols: int = shutil.get_terminal_size().columns

        self._line_chars: List[str] = []
        self._cursor_index: int = 0
        self._last_visual_lines: int = 1
        self._print_lock: threading.Lock = threading.Lock()

        self._ansi_escape: re.Pattern = re.compile(
            r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
        )

        self._init_terminal()

        if os.name != 'nt':
            signal.signal(signal.SIGWINCH, self._on_resize)

    def _init_terminal(self) -> None:
        """Configures the terminal for raw, non-blocking input (POSIX only)."""
        if os.name != 'nt':
            fd: int = sys.stdin.fileno()
            old_term_settings: List[Any] = termios.tcgetattr(fd)

            def _reset_terminal() -> None:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term_settings)

            tty.setcbreak(fd)
            atexit.register(_reset_terminal)

    def set_focus(self, alias: Optional[str]) -> None:
        """
        Updates the prompt to reflect the currently focused chat alias.

        Args:
            alias (Optional[str]): The alias to focus on, or None to unfocus.
        """
        with self._print_lock:
            self._current_focus = alias
            self._prompt = (
                f'{alias}{self._initial_prompt}' if alias else self._initial_prompt
            )
        self.full_redraw()

    def _get_visible_prefix_len(self, msg_type: str, alias: Optional[str]) -> int:
        """
        Calculates the exact length of the prefix without invisible color codes.

        Args:
            msg_type (str): The type of the message.
            alias (Optional[str]): The associated alias.

        Returns:
            int: The visible length of the prefix.
        """
        prompt_len: int = len(self._initial_prompt)
        if msg_type == 'info':
            return 4 + prompt_len
        if msg_type == 'system':
            return 6 + prompt_len
        if msg_type == 'raw':
            return 0
        if msg_type == 'self':
            return len(f'To {alias}') + prompt_len if alias else 4 + prompt_len
        if msg_type == 'remote':
            return len(f'From {alias}') + prompt_len if alias else 6 + prompt_len
        return 0

    def _format_msg(self, msg_dict: Dict[str, Any]) -> str:
        """
        Formats a raw message dictionary into a colorized CLI string.

        Args:
            msg_dict (Dict[str, Any]): The message data.

        Returns:
            str: The formatted message string.
        """
        msg_type: str = msg_dict['msg_type']
        alias: Optional[str] = msg_dict['alias']
        text: str = msg_dict['text']
        is_pending: bool = msg_dict['is_pending']

        if alias and '{alias}' in text:
            text = text.replace('{alias}', alias)

        prefix: str = ''
        if msg_type == 'info':
            prefix = f'{Theme.YELLOW}info{self._initial_prompt}{Theme.RESET}'
        elif msg_type == 'system':
            prefix = f'{Theme.CYAN}system{self._initial_prompt}{Theme.RESET}'
        elif msg_type != 'raw':
            is_focused: bool = (alias == self._current_focus) if alias else False
            if not is_focused:
                prefix_raw: str = (
                    f'To {alias}{self._initial_prompt}'
                    if (msg_type == 'self' and alias)
                    else f'self{self._initial_prompt}'
                    if msg_type == 'self'
                    else f'From {alias}{self._initial_prompt}'
                    if alias
                    else f'remote{self._initial_prompt}'
                )
                prefix = f'{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
            elif msg_type == 'self':
                prefix_raw = (
                    f'To {alias}{self._initial_prompt}'
                    if alias
                    else f'self{self._initial_prompt}'
                )
                prefix = (
                    f'{prefix_raw}'
                    if is_pending
                    else f'{Theme.GREEN}{prefix_raw}{Theme.RESET}'
                )
            elif msg_type == 'remote':
                prefix_raw = (
                    f'From {alias}{self._initial_prompt}'
                    if alias
                    else f'remote{self._initial_prompt}'
                )
                prefix = f'{Theme.PURPLE}{prefix_raw}{Theme.RESET}'

        if '\n' in text and msg_type != 'raw':
            pad_len: int = self._get_visible_prefix_len(msg_type, alias)
            padding: str = ' ' * pad_len
            lines: List[str] = text.split('\n')
            text = f'\n{padding}'.join(lines)

        return f'{prefix}{text}'

    def _get_visual_lines(self, msg_dict: Dict[str, Any], cols: int) -> int:
        """
        Calculates exactly how many terminal lines a message will occupy due to line wrapping.
        """
        msg_type: str = msg_dict.get('msg_type', 'raw')
        alias: Optional[str] = msg_dict.get('alias')
        text: str = msg_dict.get('text', '')

        if alias and '{alias}' in text:
            text = text.replace('{alias}', alias)

        clean_text: str = self._ansi_escape.sub('', text)
        prefix_len: int = self._get_visible_prefix_len(msg_type, alias)

        lines: List[str] = clean_text.split('\n')
        count: int = 0
        for line in lines:
            count += max(1, (prefix_len + len(line) + cols - 1) // cols)
        return count

    def _get_input_visual_lines(self, cols: int) -> int:
        """Calculates lines occupied by the current user input."""
        lines: List[str] = self._current_input.split('\n')
        count: int = 0
        for line in lines:
            offset: int = len(self._prompt)
            count += max(1, (offset + len(line) + cols - 1) // cols)
        return count

    def _clear_input_area_locked(self, cols: int) -> None:
        """Clears the input area dynamically, regardless of how many line breaks it has."""
        if self._last_visual_lines > 1:
            sys.stdout.write(f'\033[{self._last_visual_lines - 1}A')
        sys.stdout.write('\r\033[J')

    def _print_prompt_and_input(self, cols: int, input_lines: int) -> None:
        """Prints the prompt and restores the cursor to the exact character."""
        sys.stdout.write(self._prompt)

        padding: str = ' ' * len(self._prompt)
        display_input: str = self._current_input.replace('\n', '\n' + padding)
        sys.stdout.write(display_input)

        text_to_cursor: str = ''.join(self._line_chars[: self._cursor_index])
        cursor_lines: int = 0
        lines: List[str] = text_to_cursor.split('\n')

        for line in lines:
            offset: int = len(self._prompt)
            cursor_lines += max(1, (offset + len(line) + cols - 1) // cols)

        lines_up: int = input_lines - cursor_lines
        cursor_part: str = lines[-1]

        col_pos: int = (len(self._prompt) + len(cursor_part)) % cols

        if lines_up > 0:
            sys.stdout.write(f'\033[{lines_up}A')
        sys.stdout.write(f'\r\033[{col_pos}C' if col_pos > 0 else '\r')
        sys.stdout.flush()

    def print_message(
        self,
        msg: Any,
        msg_type: Optional[str] = None,
        alias: Optional[str] = None,
        skip_prompt: bool = False,
        msg_id: Optional[str] = None,
    ) -> None:
        """
        Prints a new message to the terminal safely, avoiding input collision.
        """
        with self._print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80

            self._clear_input_area_locked(cols)

            msg_dict: Dict[str, Any] = {
                'text': str(msg),
                'msg_type': msg_type or 'raw',
                'alias': alias,
                'is_pending': bool(msg_id),
                'msg_id': msg_id,
            }
            self._all_msgs.append(msg_dict)
            formatted_msg: str = self._format_msg(msg_dict)
            sys.stdout.write(formatted_msg + '\n')

            if not skip_prompt:
                self._last_visual_lines = self._get_input_visual_lines(cols)
                self._print_prompt_and_input(cols, self._last_visual_lines)
            else:
                self._last_visual_lines = 1

            sys.stdout.flush()

    def mark_acked(self, msg_id: str) -> None:
        """Marks a pending message as acknowledged by the remote peer."""
        start_idx: int = -1
        for i, msg in enumerate(self._all_msgs):
            if msg.get('msg_id') == msg_id:
                msg['is_pending'] = False
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def rename_alias_in_history(self, old_alias: str, new_alias: str) -> None:
        """Updates past messages with a new alias dynamically."""
        start_idx: int = -1
        for i, msg in enumerate(self._all_msgs):
            if msg.get('alias') == old_alias:
                msg['alias'] = new_alias
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def _redraw_from_index(self, start_idx: int) -> None:
        """Clears and redraws only the changed part of the screen (Soft Redraw)."""
        with self._print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80

            self._clear_input_area_locked(cols)

            lines_to_go_up: int = 0
            for i in range(start_idx, len(self._all_msgs)):
                lines_to_go_up += self._get_visual_lines(self._all_msgs[i], cols)

            term_height: int = shutil.get_terminal_size().lines
            if lines_to_go_up >= term_height:
                self._full_redraw_locked(cols)
                return

            if lines_to_go_up > 0:
                sys.stdout.write(f'\033[{lines_to_go_up}A\r\033[J')

            for i in range(start_idx, len(self._all_msgs)):
                formatted_msg: str = self._format_msg(self._all_msgs[i])
                sys.stdout.write(formatted_msg + '\n')

            self._last_visual_lines = self._get_input_visual_lines(cols)
            self._print_prompt_and_input(cols, self._last_visual_lines)

    def print_prompt(self) -> None:
        """Prints the command prompt."""
        sys.stdout.write(self._prompt)
        sys.stdout.flush()

    def print_empty_line(self) -> None:
        """Prints an empty spacer line."""
        self.print_message(' ', msg_type='raw', skip_prompt=True)

    def print_divider(self, msg_type: Optional[str] = None) -> None:
        """Prints a visual divider line."""
        self.print_message('---------------------------------', msg_type=msg_type)

    def clear_line(self) -> None:
        """Clears the current input line safely."""
        with self._print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80
            self._clear_input_area_locked(cols)
            sys.stdout.flush()

    def clear_input_area(self) -> None:
        """Alias for clear_line."""
        self.clear_line()

    def clear_screen(self) -> None:
        """Clears the entire terminal and wipes UI message history."""
        with self._print_lock:
            sys.stdout.write('\033[2J\033[H')
            sys.stdout.flush()
            self._all_msgs = []

    def _on_resize(self, _signum: Any, _frame: Any) -> None:
        """Handles terminal window resize events."""
        if self._is_redrawing:
            return
        current_cols: int = shutil.get_terminal_size().columns
        if current_cols == self._last_cols:
            return
        self._last_cols = current_cols
        self._is_redrawing = True
        try:
            self.full_redraw()
        finally:
            self._is_redrawing = False

    def full_redraw(self) -> None:
        """Forces a complete redraw of the entire terminal UI."""
        with self._print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80
            self._full_redraw_locked(cols)

    def _full_redraw_locked(self, cols: int) -> None:
        """Internal locked method for full terminal redraw."""
        sys.stdout.write('\033[2J\033[H')
        for msg_dict in self._all_msgs:
            formatted_msg: str = self._format_msg(msg_dict)
            sys.stdout.write(formatted_msg + '\n')

        self._last_visual_lines = self._get_input_visual_lines(cols)
        self._print_prompt_and_input(cols, self._last_visual_lines)
        sys.stdout.flush()

    def start_loading(self, msg: str = '...', show_prompt: bool = False) -> None:
        """Displays a loading indicator."""
        if show_prompt:
            self.print_prompt()
        sys.stdout.write(msg)
        sys.stdout.flush()

    def end_loading(self) -> None:
        """Ends the loading state and flushes pending inputs."""
        self._flush_input()

    def _flush_input(self) -> None:
        """Clears pending characters from the input buffer."""
        if os.name == 'nt':
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)

    def _get_char(self) -> Optional[str]:
        """Reads a single character or escape sequence from the terminal."""
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
                    else:
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

    def read_line(self) -> str:
        """Reads a full line of input securely, handling history and special keys."""
        with self._print_lock:
            self._line_chars = []
            self._cursor_index = 0
            self._current_input = ''
            self._last_visual_lines = 1

        while True:
            ch: Optional[str] = self._get_char()
            if ch is None:
                time.sleep(0.02)
                continue

            with self._print_lock:
                cols: int = shutil.get_terminal_size().columns
                if cols < 1:
                    cols = 80

                if ch.startswith('SPECIAL:'):
                    key: str = ch.split(':')[1]
                    if key == 'UP':
                        if (
                            self._input_history
                            and self._history_index < len(self._input_history) - 1
                        ):
                            self._history_index += 1
                            new_line: str = self._input_history[
                                -(self._history_index + 1)
                            ]
                        else:
                            new_line = (
                                self._input_history[0] if self._input_history else ''
                            )
                        self._line_chars = list(new_line)
                        self._cursor_index = len(self._line_chars)
                    elif key == 'DOWN':
                        if self._history_index > 0:
                            self._history_index -= 1
                            new_line = self._input_history[-(self._history_index + 1)]
                        else:
                            self._history_index = -1
                            new_line = ''
                        self._line_chars = list(new_line)
                        self._cursor_index = len(self._line_chars)
                    elif key == 'LEFT':
                        if self._cursor_index > 0:
                            self._cursor_index -= 1
                    elif key == 'RIGHT':
                        if self._cursor_index < len(self._line_chars):
                            self._cursor_index += 1
                    elif key == 'NEWLINE':
                        self._line_chars.insert(self._cursor_index, '\n')
                        self._cursor_index += 1

                elif ch in ('\n', '\r'):
                    self._clear_input_area_locked(cols)
                    line: str = ''.join(self._line_chars)
                    if line.strip():
                        self._input_history.append(line)
                    self._history_index = -1
                    self._current_input = ''
                    self._line_chars = []
                    self._cursor_index = 0
                    self._last_visual_lines = 1
                    sys.stdout.flush()
                    return line

                elif ch in ('\b', '\x7f'):
                    if self._cursor_index > 0:
                        del self._line_chars[self._cursor_index - 1]
                        self._cursor_index -= 1
                else:
                    self._line_chars.insert(self._cursor_index, ch)
                    self._cursor_index += 1

                self._current_input = ''.join(self._line_chars)
                self._clear_input_area_locked(cols)
                self._last_visual_lines = self._get_input_visual_lines(cols)
                self._print_prompt_and_input(cols, self._last_visual_lines)
