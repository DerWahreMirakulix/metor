"""
Module managing the terminal display buffer and repainting logic.
"""

import sys
import re
import threading
from typing import List

from metor.ui.chat.models import UIChatLine

# Local Package Imports
from metor.ui.chat.renderer.formatter import Formatter


class Display:
    """Manages the terminal output buffer and coordinates thread-safe rendering."""

    def __init__(self, initial_prompt: str) -> None:
        """
        Initializes the display manager.

        Args:
            initial_prompt (str): The base prompt string (e.g., '$ ').

        Returns:
            None
        """
        self._initial_prompt: str = initial_prompt
        self.all_msgs: List[UIChatLine] = []
        self.print_lock: threading.Lock = threading.Lock()

        self._ansi_escape: re.Pattern = re.compile(
            r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
        )

    def get_visual_lines(self, msg: UIChatLine, cols: int) -> int:
        """
        Calculates how many terminal lines a message will occupy considering word wrap.

        Args:
            msg (UIChatLine): The message metadata.
            cols (int): The current column width of the terminal.

        Returns:
            int: The number of lines the formatted message consumes.
        """
        text: str = msg.text
        if msg.alias and '{alias}' in text:
            text = text.replace('{alias}', msg.alias)

        clean_text: str = self._ansi_escape.sub('', text)
        prefix_len: int = Formatter.get_visible_prefix_len(
            msg.msg_type, msg.alias, msg.is_drop, len(self._initial_prompt)
        )

        lines: List[str] = clean_text.split('\n')
        count: int = 0
        for line in lines:
            count += max(1, (prefix_len + len(line) + cols - 1) // cols)
        return count

    def get_input_visual_lines(self, current_input: str, prompt: str, cols: int) -> int:
        """
        Calculates the lines occupied by the current user input buffer.

        Args:
            current_input (str): The text currently being typed.
            prompt (str): The dynamic prompt string currently displayed.
            cols (int): The terminal column width.

        Returns:
            int: The number of vertical lines used.
        """
        lines: List[str] = current_input.split('\n')
        count: int = 0
        for line in lines:
            offset: int = len(prompt)
            count += max(1, (offset + len(line) + cols - 1) // cols)
        return count

    def clear_input_area(self, last_visual_lines: int) -> None:
        """
        Wipes the bottom input area dynamically to prepare for a redraw.

        Args:
            last_visual_lines (int): The number of lines the input previously occupied.

        Returns:
            None
        """
        if last_visual_lines > 1:
            sys.stdout.write(f'\033[{last_visual_lines - 1}A')
        sys.stdout.write('\r\033[J')

    def redraw_input_area(
        self,
        prompt: str,
        current_input: str,
        line_chars: List[str],
        cursor_index: int,
        input_lines: int,
        cols: int,
    ) -> None:
        """
        Prints the prompt and restores the cursor to the exact typed position.

        Args:
            prompt (str): The dynamic prompt string.
            current_input (str): The full input buffer string.
            line_chars (List[str]): List of individual characters representing the input.
            cursor_index (int): The current cursor position in the array.
            input_lines (int): Total visual lines the input occupies.
            cols (int): Terminal width.

        Returns:
            None
        """
        sys.stdout.write(prompt)
        padding: str = ' ' * len(prompt)
        display_input: str = current_input.replace('\n', '\n' + padding)
        sys.stdout.write(display_input)

        text_to_cursor: str = ''.join(line_chars[:cursor_index])
        cursor_lines: int = 0
        lines: List[str] = text_to_cursor.split('\n')

        for line in lines:
            offset: int = len(prompt)
            cursor_lines += max(1, (offset + len(line) + cols - 1) // cols)

        lines_up: int = input_lines - cursor_lines
        col_pos: int = (len(prompt) + len(lines[-1])) % cols

        if lines_up > 0:
            sys.stdout.write(f'\033[{lines_up}A')
        sys.stdout.write(f'\r\033[{col_pos}C' if col_pos > 0 else '\r')
        sys.stdout.flush()

    def clear_screen(self) -> None:
        """
        Wipes the terminal display completely.

        Args:
            None

        Returns:
            None
        """
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
        self.all_msgs.clear()
