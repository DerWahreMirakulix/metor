"""
Module managing the terminal display buffer and repainting logic.
"""

import sys
import re
import threading
from typing import Callable, List, Optional

from metor.ui.chat.models import ChatLine
from metor.ui.chat.presenter import ChatPresenter


class Display:
    """Manages the terminal output buffer and coordinates thread-safe rendering."""

    _CURSOR_HIDE: str = '\033[?25l'
    _CURSOR_SHOW: str = '\033[?25h'
    _CLEAR_INPUT_AREA: str = '\r\033[J'
    _CLEAR_SCREEN: str = '\033[2J\033[H'

    def __init__(
        self,
        initial_prompt: str,
        alias_resolver: Callable[[ChatLine], Optional[str]],
    ) -> None:
        """
        Initializes the display manager.

        Args:
            initial_prompt (str): The base prompt string (e.g., '$ ').
            alias_resolver (Callable[[ChatLine], Optional[str]]): Resolves the active alias for one line.

        Returns:
            None
        """
        self._initial_prompt: str = initial_prompt
        self._alias_resolver: Callable[[ChatLine], Optional[str]] = alias_resolver
        self.all_msgs: List[ChatLine] = []
        self.print_lock: threading.Lock = threading.Lock()

        self._ansi_escape: re.Pattern[str] = re.compile(
            r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
        )

    def get_visual_lines(self, msg: ChatLine, cols: int) -> int:
        """
        Calculates how many terminal lines a message will occupy considering word wrap.

        Args:
            msg (ChatLine): The message metadata.
            cols (int): The current column width of the terminal.

        Returns:
            int: The number of lines the formatted message consumes.
        """
        resolved_alias: Optional[str] = self._alias_resolver(msg)
        text: str = msg.text
        if resolved_alias and '{alias}' in text:
            text = text.replace('{alias}', resolved_alias)

        clean_text: str = self._ansi_escape.sub('', text)
        prefix_len: int = ChatPresenter.get_visible_prefix_len(
            msg.msg_type,
            msg.tone,
            resolved_alias,
            msg.is_drop,
            len(self._initial_prompt),
            msg.timestamp,
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

    def _append_input_area_clear(
        self,
        buffer: List[str],
        last_visual_lines: int,
        hide_cursor: bool = False,
    ) -> None:
        """
        Appends the VT100 sequence required to clear the current input block.

        Args:
            buffer (List[str]): Aggregated terminal frame buffer.
            last_visual_lines (int): The number of lines the input previously occupied.
            hide_cursor (bool): Whether to hide the cursor before clearing.

        Returns:
            None
        """
        if hide_cursor:
            buffer.append(self._CURSOR_HIDE)
        if last_visual_lines > 1:
            buffer.append(f'\033[{last_visual_lines - 1}A')
        buffer.append(self._CLEAR_INPUT_AREA)

    def restore_cursor(self) -> None:
        """
        Restores terminal cursor visibility immediately.

        Args:
            None

        Returns:
            None
        """
        sys.stdout.write(self._CURSOR_SHOW)
        sys.stdout.flush()

    def render_prompt(self, prompt: str) -> None:
        """
        Writes the prompt and guarantees that the cursor is visible.

        Args:
            prompt (str): The prompt string to render.

        Returns:
            None
        """
        sys.stdout.write(prompt + self._CURSOR_SHOW)
        sys.stdout.flush()

    def clear_input_area(self, last_visual_lines: int) -> None:
        """
        Wipes the bottom input area dynamically to prepare for a redraw.

        Args:
            last_visual_lines (int): The number of lines the input previously occupied.

        Returns:
            None
        """
        buffer: List[str] = []
        self._append_input_area_clear(buffer, last_visual_lines)
        sys.stdout.write(''.join(buffer))

    def redraw_input_area(
        self,
        prompt: str,
        current_input: str,
        line_chars: List[str],
        cursor_index: int,
        input_lines: int,
        cols: int,
        last_visual_lines: int = 1,
        clear_first: bool = False,
    ) -> None:
        """
        Prints the prompt and restores the cursor to the exact typed position.
        Uses string buffering for atomic rendering to prevent visual strobe effects.
        Always guarantees cursor visibility restoration.

        Args:
            prompt (str): The dynamic prompt string.
            current_input (str): The full input buffer string.
            line_chars (List[str]): List of individual characters representing the input.
            cursor_index (int): The current cursor position in the array.
            input_lines (int): Total visual lines the input occupies.
            cols (int): Terminal width.
            last_visual_lines (int): The number of lines the input previously occupied.
            clear_first (bool): Perform an atomic clear operation before redrawing.

        Returns:
            None
        """
        buffer: List[str] = []

        if clear_first:
            self._append_input_area_clear(
                buffer,
                last_visual_lines,
                hide_cursor=True,
            )

        buffer.append(prompt)
        padding: str = ' ' * len(prompt)
        display_input: str = current_input.replace('\n', '\n' + padding)
        buffer.append(display_input)

        text_to_cursor: str = ''.join(line_chars[:cursor_index])
        cursor_lines: int = 0
        lines: List[str] = text_to_cursor.split('\n')

        for line in lines:
            offset: int = len(prompt)
            cursor_lines += max(1, (offset + len(line) + cols - 1) // cols)

        lines_up: int = input_lines - cursor_lines
        col_pos: int = (len(prompt) + len(lines[-1])) % cols

        if lines_up > 0:
            buffer.append(f'\033[{lines_up}A')
        buffer.append(f'\r\033[{col_pos}C' if col_pos > 0 else '\r')

        buffer.append(self._CURSOR_SHOW)

        sys.stdout.write(''.join(buffer))
        sys.stdout.flush()

    def clear_screen(self) -> None:
        """
        Wipes the terminal display completely and ensures cursor visibility.

        Args:
            None

        Returns:
            None
        """
        sys.stdout.write(f'{self._CURSOR_SHOW}{self._CLEAR_SCREEN}')
        sys.stdout.flush()
        self.all_msgs.clear()
