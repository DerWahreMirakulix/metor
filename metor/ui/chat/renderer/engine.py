"""
Module defining the Renderer Engine, orchestrating display, format, and input layers.
Enforces memory limits (CHAT_LIMIT) on active chat sessions.
"""

import sys
import shutil
import signal
import time
from typing import Optional, Any

from metor.data.settings import SettingKey, Settings
from metor.ui.chat.models import UIMessageType, UIChatLine
from metor.utils.helper import get_divider_string

# Local Package Imports
from metor.ui.chat.renderer.display import Display
from metor.ui.chat.renderer.input import InputHandler
from metor.ui.chat.renderer.formatter import Formatter


class Renderer:
    """Facade for the UI rendering layer. Manages threading locks and sub-components."""

    def __init__(self) -> None:
        """
        Initializes the Renderer Engine and its sub-components.

        Args:
            None

        Returns:
            None
        """
        self._initial_prompt: str = f'{Settings.get(SettingKey.PROMPT_SIGN)} '
        self._prompt: str = self._initial_prompt

        self._display: Display = Display(self._initial_prompt)
        self._input: InputHandler = InputHandler()

        self._current_focus: Optional[str] = None
        self._is_live_focus: bool = False

        self._last_visual_lines: int = 1
        self._last_cols: int = shutil.get_terminal_size().columns
        self._is_redrawing: bool = False

        if sys.platform != 'win32':
            signal.signal(signal.SIGWINCH, self._on_resize)

    def set_focus(self, alias: Optional[str], is_live: bool = False) -> None:
        """
        Updates the prompt string to reflect the focused alias.

        Args:
            alias (Optional[str]): The alias to focus on.
            is_live (bool): Whether the connection is active/live.

        Returns:
            None
        """
        with self._display.print_lock:
            self._current_focus = alias
            self._is_live_focus = is_live
            if alias:
                drop_tag: str = '' if is_live else ' [Drop]'
                self._prompt = f'{alias}{drop_tag}{self._initial_prompt}'
            else:
                self._prompt = self._initial_prompt
        self.full_redraw()

    def print_message(
        self,
        msg: Any,
        msg_type: UIMessageType = UIMessageType.RAW,
        alias: Optional[str] = None,
        skip_prompt: bool = False,
        msg_id: Optional[str] = None,
        is_drop: bool = False,
        is_pending: bool = True,
    ) -> None:
        """
        Safely renders a new message to the terminal. Constrains buffer size via settings.

        Args:
            msg (Any): The message content to render.
            msg_type (UIMessageType): The visual routing type of the message.
            alias (Optional[str]): The associated remote alias.
            skip_prompt (bool): Flag to skip rendering the prompt after the message.
            msg_id (Optional[str]): Unique identifier for the message.
            is_drop (bool): Flag indicating if the message is an asynchronous drop.
            is_pending (bool): Flag indicating if the message is awaiting acknowledgment.

        Returns:
            None
        """
        with self._display.print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80

            self._display.clear_input_area(self._last_visual_lines)

            chat_line: UIChatLine = UIChatLine(
                text=str(msg),
                msg_type=msg_type,
                alias=alias,
                is_pending=bool(msg_id) if not is_drop else is_pending,
                msg_id=msg_id,
                is_drop=is_drop,
            )

            self._display.all_msgs.append(chat_line)

            limit: int = Settings.get(SettingKey.CHAT_LIMIT)
            if len(self._display.all_msgs) > limit:
                self._display.all_msgs = self._display.all_msgs[-limit:]
                self._full_redraw_locked(cols)
                return

            formatted: str = Formatter.format_msg(
                chat_line, self._initial_prompt, self._current_focus
            )
            sys.stdout.write(formatted + '\n')

            if not skip_prompt:
                self._last_visual_lines = self._display.get_input_visual_lines(
                    self._input.current_input, self._prompt, cols
                )
                self._display.redraw_input_area(
                    self._prompt,
                    self._input.current_input,
                    self._input.line_chars,
                    self._input.cursor_index,
                    self._last_visual_lines,
                    cols,
                )
            else:
                self._last_visual_lines = 1

            sys.stdout.flush()

    def mark_acked(self, msg_id: str) -> None:
        """
        Marks a pending message as acknowledged and redraws it in green.

        Args:
            msg_id (str): The unique message identifier to acknowledge.

        Returns:
            None
        """
        start_idx: int = -1
        for i, msg in enumerate(self._display.all_msgs):
            if msg.msg_id == msg_id:
                msg.is_pending = False
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def apply_fallback_to_drop(self, msg_ids: list[str]) -> None:
        """
        Converts hanging un-acked live messages into pending drops.

        Args:
            msg_ids (list[str]): List of message IDs to convert.

        Returns:
            None
        """
        start_idx: int = -1
        for i, msg in enumerate(self._display.all_msgs):
            if msg.msg_id in msg_ids:
                msg.is_drop = True
                msg.is_pending = True
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def rename_alias_in_history(self, old_alias: str, new_alias: str) -> None:
        """
        Updates old alias references to a new one in the UI buffer.

        Args:
            old_alias (str): The current alias string.
            new_alias (str): The new alias string.

        Returns:
            None
        """
        start_idx: int = -1
        for i, msg in enumerate(self._display.all_msgs):
            if msg.alias == old_alias:
                msg.alias = new_alias
                if start_idx == -1:
                    start_idx = i
        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def print_prompt(self) -> None:
        """
        Forces the terminal to display the prompt.

        Args:
            None

        Returns:
            None
        """
        sys.stdout.write(self._prompt)
        sys.stdout.flush()

    def print_empty_line(self) -> None:
        """
        Prints an empty spacer line.

        Args:
            None

        Returns:
            None
        """
        self.print_message(' ', msg_type=UIMessageType.RAW, skip_prompt=True)

    def print_divider(self, msg_type: UIMessageType = UIMessageType.RAW) -> None:
        """
        Prints a visual divider line.

        Args:
            msg_type (UIMessageType): The message type for the divider.

        Returns:
            None
        """
        self.print_message(get_divider_string(), msg_type=msg_type)

    def clear_input_area(self) -> None:
        """
        Clears the current input line securely.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80
            self._display.clear_input_area(self._last_visual_lines)
            sys.stdout.flush()

    def clear_screen(self) -> None:
        """
        Wipes the terminal space and volatile message buffer.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
            self._display.clear_screen()

    def _redraw_from_index(self, start_idx: int) -> None:
        """
        Soft redraw of messages starting from a specific index.

        Args:
            start_idx (int): The index in the message buffer to start redrawing from.

        Returns:
            None
        """
        with self._display.print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80

            self._display.clear_input_area(self._last_visual_lines)
            lines_up: int = sum(
                self._display.get_visual_lines(self._display.all_msgs[i], cols)
                for i in range(start_idx, len(self._display.all_msgs))
            )

            if lines_up >= shutil.get_terminal_size().lines:
                self._full_redraw_locked(cols)
                return

            if lines_up > 0:
                sys.stdout.write(f'\033[{lines_up}A\r\033[J')

            for i in range(start_idx, len(self._display.all_msgs)):
                formatted: str = Formatter.format_msg(
                    self._display.all_msgs[i], self._initial_prompt, self._current_focus
                )
                sys.stdout.write(formatted + '\n')

            self._last_visual_lines = self._display.get_input_visual_lines(
                self._input.current_input, self._prompt, cols
            )
            self._display.redraw_input_area(
                self._prompt,
                self._input.current_input,
                self._input.line_chars,
                self._input.cursor_index,
                self._last_visual_lines,
                cols,
            )

    def _full_redraw_locked(self, cols: int) -> None:
        """
        Internal locked method executing the full terminal redraw sequence.

        Args:
            cols (int): The terminal column width.

        Returns:
            None
        """
        sys.stdout.write('\033[2J\033[H')
        for msg in self._display.all_msgs:
            formatted: str = Formatter.format_msg(
                msg, self._initial_prompt, self._current_focus
            )
            sys.stdout.write(formatted + '\n')

        self._last_visual_lines = self._display.get_input_visual_lines(
            self._input.current_input, self._prompt, cols
        )
        self._display.redraw_input_area(
            self._prompt,
            self._input.current_input,
            self._input.line_chars,
            self._input.cursor_index,
            self._last_visual_lines,
            cols,
        )
        sys.stdout.flush()

    def full_redraw(self) -> None:
        """
        Forces a complete redraw of the entire terminal UI.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = 80
            self._full_redraw_locked(cols)

    def _on_resize(self, _signum: Any, _frame: Any) -> None:
        """
        Signal handler for terminal resize events.

        Args:
            _signum (Any): The signal number.
            _frame (Any): The current stack frame.

        Returns:
            None
        """
        if self._is_redrawing:
            return
        cols: int = shutil.get_terminal_size().columns
        if cols == self._last_cols:
            return
        self._last_cols = cols
        self._is_redrawing = True
        try:
            self.full_redraw()
        finally:
            self._is_redrawing = False

    def read_line(self) -> str:
        """
        Reads a full line of text securely, handling blocking I/O and redraws.

        Args:
            None

        Returns:
            str: The fully read user input string.
        """
        with self._display.print_lock:
            self._input.line_chars = []
            self._input.cursor_index = 0
            self._input.current_input = ''
            self._last_visual_lines = 1

        while True:
            ch: Optional[str] = self._input.get_char()
            if ch is None:
                time.sleep(0.02)
                continue

            with self._display.print_lock:
                cols: int = shutil.get_terminal_size().columns
                if cols < 1:
                    cols = 80

                ready: bool = self._input.process_key(ch)
                self._display.clear_input_area(self._last_visual_lines)

                if ready:
                    sys.stdout.flush()
                    return (
                        ''.join(self._input.history[-1]) if self._input.history else ''
                    )

                self._last_visual_lines = self._display.get_input_visual_lines(
                    self._input.current_input, self._prompt, cols
                )
                self._display.redraw_input_area(
                    self._prompt,
                    self._input.current_input,
                    self._input.line_chars,
                    self._input.cursor_index,
                    self._last_visual_lines,
                    cols,
                )
