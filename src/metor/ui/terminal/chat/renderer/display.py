"""
Module managing the terminal display buffer and repainting logic.
"""

import os
import shutil
import sys
import threading
from typing import List

from metor.shared import escape_terminal_text
from metor.ui.terminal.cells import cell_rows, cell_width, line_end

# Local Package Imports
from metor.ui.terminal.chat.models import ChatLine


class Display:
    """Manages the terminal output buffer and coordinates thread-safe rendering."""

    _CURSOR_HIDE: str = '\033[?25l'
    _CURSOR_SHOW: str = '\033[?25h'
    _PASTE_ENABLE: str = '\033[?2004h'
    _PASTE_DISABLE: str = '\033[?2004l'
    _CLEAR_INPUT_AREA: str = '\r\033[J'
    _CLEAR_SCREEN: str = '\033[2J\033[H'

    def __init__(self) -> None:
        """Initialize the owned display buffer and atomic rendering lock."""
        self.all_msgs: List[ChatLine] = []
        self.print_lock: threading.Lock = threading.Lock()
        self._paste_enabled = False
        self._input_cursor_row = 0

    @staticmethod
    def _input_layout(
        current_input: str, prompt: str, cols: int
    ) -> tuple[str, int, int]:
        """Lay out the escaped draft with a stable cursor even at the right margin."""
        padding = ' ' * cell_width(prompt)
        rendered = prompt + escape_terminal_text(current_input).replace(
            '\n', '\n' + padding
        )
        row = 0
        column = 0
        lines = rendered.split('\n')
        for index, line in enumerate(lines):
            wrapped_row, column = line_end(line, cols)
            row += wrapped_row
            if index < len(lines) - 1:
                row += 1
        if column == max(1, cols):
            # Materialize pending autowrap before a cursor-positioning sequence
            # cancels it and incorrectly puts the cursor at this row's start.
            rendered += '\n'
            row += 1
            column = 0
        return rendered, row, column

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
        return self._input_layout(current_input, prompt, cols)[1] + 1

    def _append_input_area_clear(
        self,
        buffer: List[str],
        hide_cursor: bool = False,
    ) -> None:
        """
        Appends the VT100 sequence required to clear the current input block.

        Args:
            buffer (List[str]): Aggregated terminal frame buffer.
            hide_cursor (bool): Whether to hide the cursor before clearing.

        Returns:
            None
        """
        if hide_cursor:
            buffer.append(self._CURSOR_HIDE)
        if self._input_cursor_row:
            buffer.append(f'\033[{self._input_cursor_row}A')
        buffer.append(self._CLEAR_INPUT_AREA)
        self._input_cursor_row = 0

    def enable_bracketed_paste(self) -> None:
        """Enable clipboard delimiters only for the POSIX streaming input decoder."""
        if os.name == 'posix' and not self._paste_enabled:
            self._paste_enabled = True
            sys.stdout.write(self._PASTE_ENABLE)
            sys.stdout.flush()

    def restore_cursor(self) -> None:
        """
        Restores terminal cursor visibility immediately.

        Args:
            None

        Returns:
            None
        """
        if self._paste_enabled:
            self._paste_enabled = False
            sys.stdout.write(self._PASTE_DISABLE)
        sys.stdout.write(self._CURSOR_SHOW)
        sys.stdout.flush()

    def render_prompt(self, prompt: str, cols: int) -> None:
        """
        Writes the prompt and guarantees that the cursor is visible.

        Args:
            prompt (str): The prompt string to render.
            cols (int): The terminal width used to place a wrapped prompt.

        Returns:
            None
        """
        self.redraw_input_area(prompt, '', [], 0, cols)

    def clear_input_area(self) -> None:
        """
        Wipes the bottom input area dynamically to prepare for a redraw.

        Returns:
            None
        """
        buffer: List[str] = []
        self._append_input_area_clear(buffer)
        sys.stdout.write(''.join(buffer))

    def redraw_input_area(
        self,
        prompt: str,
        current_input: str,
        line_chars: List[str],
        cursor_index: int,
        cols: int,
        clear_first: bool = False,
        *,
        rows: int | None = None,
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
            cols (int): Terminal width.
            clear_first (bool): Perform an atomic clear operation before redrawing.
            rows (int | None): Visible terminal height, or the current native height.

        Returns:
            None
        """
        buffer: List[str] = []

        if clear_first:
            self._append_input_area_clear(
                buffer,
                hide_cursor=True,
            )

        display_input, final_row, _ = self._input_layout(current_input, prompt, cols)
        _, cursor_row, col_pos = self._input_layout(
            ''.join(line_chars[:cursor_index]), prompt, cols
        )
        available_rows = max(
            1, rows if rows is not None else shutil.get_terminal_size().lines
        )
        if final_row >= available_rows:
            # A terminal cannot move the cursor back into scrolled-off content.
            # Paint only the physical rows surrounding the logical edit position.
            input_rows = cell_rows(display_input, cols)
            first_row = max(
                0,
                min(cursor_row - available_rows // 2, len(input_rows) - available_rows),
            )
            visible_rows = input_rows[first_row : first_row + available_rows]
            display_input = '\n'.join(visible_rows)
            final_row = len(visible_rows) - 1
            cursor_row -= first_row
        buffer.append(display_input)
        lines_up: int = final_row - cursor_row

        if lines_up > 0:
            buffer.append(f'\033[{lines_up}A')
        buffer.append(f'\r\033[{col_pos}C' if col_pos > 0 else '\r')

        buffer.append(self._CURSOR_SHOW)

        sys.stdout.write(''.join(buffer))
        sys.stdout.flush()
        self._input_cursor_row = cursor_row

    def reset_viewport(self) -> None:
        """Start a full repaint from a known origin without discarding the buffer."""
        sys.stdout.write(f'{self._CURSOR_SHOW}{self._CLEAR_SCREEN}')
        self._input_cursor_row = 0

    def clear_screen(self) -> None:
        """
        Wipes the terminal display completely and ensures cursor visibility.

        Args:
            None

        Returns:
            None
        """
        self.reset_viewport()
        sys.stdout.flush()
        self.all_msgs.clear()
