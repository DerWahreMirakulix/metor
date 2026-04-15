"""
Module defining the Renderer Engine, orchestrating display, format, and input layers.
Enforces memory limits (CHAT_LIMIT) on active chat sessions.
"""

import sys
import shutil
import signal
import time
import threading
import types
from datetime import datetime, timezone
from typing import Callable, List, Dict, Optional, TYPE_CHECKING

from metor.core.api import JsonValue
from metor.ui.models import AliasPolicy, StatusTone
from metor.ui import UIPresenter
from metor.ui.chat.models import ChatMessageType, ChatLine
from metor.ui.chat.presenter import ChatPresenter
from metor.utils import Constants

# Local Package Imports
from metor.ui.chat.renderer.display import Display
from metor.ui.chat.renderer.input import InputHandler

if TYPE_CHECKING:
    from metor.data.profile import Config


UI_PROMPT_SIGN_KEY: str = 'ui.prompt_sign'
UI_CHAT_LIMIT_KEY: str = 'ui.chat_limit'
UI_CHAT_BUFFER_PADDING_KEY: str = 'ui.chat_buffer_padding'


class Renderer:
    """Facade for the UI rendering layer. Manages threading locks and sub-components."""

    def __init__(self, config: 'Config') -> None:
        """
        Initializes the Renderer Engine and its sub-components.

        Args:
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._config: 'Config' = config
        self._initial_prompt: str = f'{self._config.get_str(UI_PROMPT_SIGN_KEY)} '
        self._prompt: str = self._initial_prompt
        self._alias_resolver: Callable[
            [Optional[str], Optional[str]], Optional[str]
        ] = lambda onion, fallback_alias: fallback_alias

        self._display: Display = Display(
            self._initial_prompt,
            self._resolve_line_alias,
        )
        self._input: InputHandler = InputHandler()

        self._current_focus: Optional[str] = None
        self._is_live_focus: bool = False

        self._last_visual_lines: int = 1
        self._last_cols: int = shutil.get_terminal_size().columns
        self._is_redrawing: bool = False

        if sys.platform != 'win32':
            signal.signal(signal.SIGWINCH, self._on_resize)

    def set_alias_resolver(
        self,
        resolver: Callable[[Optional[str], Optional[str]], Optional[str]],
    ) -> None:
        """
        Injects the alias resolver used for peer-bound redraws.

        Args:
            resolver (Callable[[Optional[str], Optional[str]], Optional[str]]): Resolves the current alias for one peer onion.

        Returns:
            None
        """
        self._alias_resolver = resolver

    def _resolve_line_alias(self, chat_line: ChatLine) -> Optional[str]:
        """
        Resolves the alias that should be rendered for one chat line.

        Args:
            chat_line (ChatLine): The line to resolve.

        Returns:
            Optional[str]: The alias to render for the current redraw.
        """
        if chat_line.alias_policy is AliasPolicy.DYNAMIC and chat_line.peer_onion:
            return self._alias_resolver(chat_line.peer_onion, chat_line.alias)
        return chat_line.alias

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
        msg: str,
        msg_type: ChatMessageType = ChatMessageType.RAW,
        tone: Optional[StatusTone] = None,
        alias: Optional[str] = None,
        peer_onion: Optional[str] = None,
        alias_policy: AliasPolicy = AliasPolicy.NONE,
        timestamp: Optional[str] = None,
        skip_prompt: bool = False,
        msg_id: Optional[str] = None,
        is_drop: bool = False,
        is_pending: bool = True,
    ) -> None:
        """
        Safely renders a new message to the terminal. Constrains buffer size via sliding window.

        Args:
            msg (str): The strictly typed string message to render.
            msg_type (ChatMessageType): The visual routing type of the message.
            tone (Optional[StatusTone]): The tone for status messages.
            alias (Optional[str]): The associated remote alias.
            peer_onion (Optional[str]): The stable peer onion identity for dynamic alias redraws.
            alias_policy (AliasPolicy): Whether the alias should be rebound on redraw.
            timestamp (Optional[str]): Optional chronological timestamp for message lines.
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
                cols = Constants.DEFAULT_COLS

            if msg_type is not ChatMessageType.RAW and timestamp is None:
                timestamp = datetime.now(timezone.utc).isoformat()

            self._display.clear_input_area(self._last_visual_lines)
            previous_count: int = len(self._display.all_msgs)

            chat_line: ChatLine = ChatLine(
                text=msg,
                msg_type=msg_type,
                tone=tone,
                alias=alias,
                peer_onion=peer_onion,
                alias_policy=alias_policy,
                timestamp=timestamp,
                is_pending=bool(msg_id) if not is_drop else is_pending,
                msg_id=msg_id,
                is_drop=is_drop,
            )

            insert_index: int = self._insert_chat_line(chat_line)

            self._trim_message_buffer(self._config.get_int(UI_CHAT_LIMIT_KEY))

            if len(self._display.all_msgs) <= previous_count:
                self._redraw_from_index_locked(0, cols, skip_prompt)
                return

            if insert_index < previous_count:
                self._redraw_from_index_locked(insert_index, cols, skip_prompt)
                return

            formatted: str = ChatPresenter.format_msg(
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

    def print_messages_batch(
        self,
        messages_data: List[Dict[str, JsonValue]],
        alias: str,
        peer_onion: Optional[str] = None,
        is_live_flush: bool = False,
    ) -> None:
        """
        Processes a burst of offline drops or a headless RAM flush in a single redraw.
        Respects the chat_buffer_padding setting to ensure smooth scrolling.

        Args:
            messages_data (List[Dict[str, JsonValue]]): The list of raw message dictionaries.
            alias (str): The target alias.
            peer_onion (Optional[str]): The stable peer onion identity.
            is_live_flush (bool): Flag denoting if these messages are a live buffer flush.

        Returns:
            None
        """
        if not messages_data:
            return

        with self._display.print_lock:
            cols: int = shutil.get_terminal_size().columns
            if cols < 1:
                cols = Constants.DEFAULT_COLS

            self._display.clear_input_area(self._last_visual_lines)

            for msg_dict in messages_data:
                is_drop_value: object = msg_dict.get('is_drop')
                chat_line: ChatLine = ChatLine(
                    text=str(msg_dict.get('payload', '')),
                    msg_type=ChatMessageType.REMOTE,
                    tone=None,
                    alias=alias,
                    peer_onion=peer_onion,
                    alias_policy=(
                        AliasPolicy.DYNAMIC if peer_onion else AliasPolicy.STATIC
                    ),
                    timestamp=str(msg_dict.get('timestamp') or ''),
                    is_pending=False,
                    msg_id=str(msg_dict.get('id', '')),
                    is_drop=(
                        bool(is_drop_value)
                        if isinstance(is_drop_value, bool)
                        else not is_live_flush
                    ),
                )
                self._insert_chat_line(chat_line)

            limit: int = self._config.get_int(UI_CHAT_LIMIT_KEY)
            padding: int = self._config.get_int(UI_CHAT_BUFFER_PADDING_KEY)
            total_limit: int = limit + padding

            self._trim_message_buffer(total_limit)

            self._full_redraw_locked(cols)

    def _insert_chat_line(self, chat_line: ChatLine) -> int:
        """
        Inserts one chat line into the visible buffer.

        Args:
            chat_line (ChatLine): The line to insert.

        Returns:
            int: The final insertion index.
        """
        self._display.all_msgs.append(chat_line)
        return len(self._display.all_msgs) - 1

    def _trim_message_buffer(self, limit: int) -> None:
        """
        Shrinks the visible message buffer to the requested size.

        Args:
            limit (int): The maximum number of visible chat lines.

        Returns:
            None
        """
        while len(self._display.all_msgs) > limit:
            self._display.all_msgs.pop(0)

    def mark_acked(
        self,
        msg_id: Optional[str] = None,
        text: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """
        Marks a pending message as acknowledged and redraws it in green.
        Fallback to text matching if DB ID mapping is unavailable (e.g. Drops).

        Args:
            msg_id (Optional[str]): The unique message identifier to acknowledge.
            text (Optional[str]): The exact payload text of the message.
            timestamp (Optional[str]): The authoritative daemon timestamp, if available.

        Returns:
            None
        """
        start_idx: int = -1
        for i, msg in enumerate(self._display.all_msgs):
            if (msg_id and msg.msg_id == msg_id) or (
                text and msg.text == text and msg.is_drop and msg.is_pending
            ):
                msg.is_pending = False
                if timestamp:
                    msg.timestamp = timestamp
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def mark_failed(self, msg_id: str) -> None:
        """
        Marks a pending message as failed and redraws it in red.

        Args:
            msg_id (str): The unique message identifier that failed.

        Returns:
            None
        """
        start_idx: int = -1
        for i, msg in enumerate(self._display.all_msgs):
            if msg.msg_id == msg_id:
                msg.is_pending = False
                msg.is_failed = True
                if start_idx == -1:
                    start_idx = i

        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def apply_fallback_to_drop(self, msg_ids: List[str]) -> None:
        """
        Converts hanging un-acked live messages into pending drops.

        Args:
            msg_ids (List[str]): List of message IDs to convert.

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

    def refresh_alias_bindings(self) -> None:
        """
        Re-renders the chat buffer after alias bindings changed.

        Args:
            None

        Returns:
            None
        """
        self.full_redraw()

    def print_prompt(self) -> None:
        """
        Forces the terminal to display the prompt and restores cursor visibility.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
            self._display.render_prompt(self._prompt)

    def restore_cursor(self) -> None:
        """
        Restores cursor visibility without mutating the active screen state.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
            self._display.restore_cursor()

    def print_empty_line(self) -> None:
        """
        Prints an empty spacer line.

        Args:
            None

        Returns:
            None
        """
        self.print_message(' ', msg_type=ChatMessageType.RAW, skip_prompt=True)

    def print_divider(
        self,
        msg_type: ChatMessageType = ChatMessageType.RAW,
        compact: bool = False,
        skip_prompt: bool = False,
    ) -> None:
        """
        Prints a visual divider line.

        Args:
            msg_type (ChatMessageType): The message type for the divider.
            compact (bool): Whether to use a compact divider.
            skip_prompt (bool): Whether to avoid redrawing the prompt afterward.

        Returns:
            None
        """
        self.print_message(
            UIPresenter.get_divider_string()
            if not compact
            else UIPresenter.get_divider_string(3, add_spaces=True),
            msg_type=msg_type,
            skip_prompt=skip_prompt,
        )

    def clear_input_area(self) -> None:
        """
        Clears the current input line securely.

        Args:
            None

        Returns:
            None
        """
        with self._display.print_lock:
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

    def _redraw_from_index_locked(
        self,
        start_idx: int,
        cols: int,
        skip_prompt: bool = False,
    ) -> None:
        """
        Redraws the terminal tail while the print lock is already held.

        Args:
            start_idx (int): The index in the message buffer to start redrawing from.
            cols (int): The current terminal column width.
            skip_prompt (bool): Whether to suppress prompt redraw after the update.

        Returns:
            None
        """
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
            formatted: str = ChatPresenter.format_msg(
                self._display.all_msgs[i],
                self._initial_prompt,
                self._current_focus,
                self._resolve_line_alias(self._display.all_msgs[i]),
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
                cols = Constants.DEFAULT_COLS
            self._redraw_from_index_locked(start_idx, cols)

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
            formatted: str = ChatPresenter.format_msg(
                msg,
                self._initial_prompt,
                self._current_focus,
                self._resolve_line_alias(msg),
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
                cols = Constants.DEFAULT_COLS
            self._full_redraw_locked(cols)

    def _on_resize(self, _signum: int, _frame: Optional[types.FrameType]) -> None:
        """
        Signal handler for terminal resize events.

        Args:
            _signum (int): The signal number.
            _frame (Optional[types.FrameType]): The current stack frame.

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

    def read_line(self, stop_event: Optional[threading.Event] = None) -> Optional[str]:
        """
        Reads a full line of text securely, handling blocking I/O and atomic redraws.
        Reduces strobe effects during input by clearing and restoring the cursor in a single write.

        Args:
            stop_event (Optional[threading.Event]): Optional signal to abort the read loop.

        Returns:
            Optional[str]: The fully read user input string or None if aborted.
        """
        with self._display.print_lock:
            self._input.line_chars = []
            self._input.cursor_index = 0
            self._input.current_input = ''
            self._last_visual_lines = 1

        while True:
            if stop_event and stop_event.is_set():
                return None

            ch: Optional[str] = self._input.get_char()
            if ch is None:
                time.sleep(Constants.INPUT_SLEEP_SEC)
                continue

            with self._display.print_lock:
                cols: int = shutil.get_terminal_size().columns
                if cols < 1:
                    cols = Constants.DEFAULT_COLS

                result: Optional[str] = self._input.process_key(ch)

                if result is not None:
                    self._display.clear_input_area(self._last_visual_lines)
                    self._last_visual_lines = 1
                    sys.stdout.flush()
                    return result

                new_visual_lines: int = self._display.get_input_visual_lines(
                    self._input.current_input, self._prompt, cols
                )
                self._display.redraw_input_area(
                    self._prompt,
                    self._input.current_input,
                    self._input.line_chars,
                    self._input.cursor_index,
                    new_visual_lines,
                    cols,
                    last_visual_lines=self._last_visual_lines,
                    clear_first=True,
                )
                self._last_visual_lines = new_visual_lines
