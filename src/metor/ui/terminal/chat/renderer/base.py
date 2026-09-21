"""
Module defining the abstract ChatRenderer protocol consumed by the chat core.
Decouples the Chat engine, event handlers, and command dispatcher from the
terminal-specific rendering implementation.
"""

import threading
from typing import Callable, Dict, List, Optional, Protocol

from metor.core.api import JsonValue
from metor.ui.terminal.models import AliasPolicy, StatusTone

# Local Package Imports
from metor.ui.terminal.chat.models import ChatMessageType, ChatTransportState


class ChatRenderer(Protocol):
    """Structural contract every chat UI renderer must satisfy."""

    def set_alias_resolver(
        self,
        resolver: Callable[[Optional[str], Optional[str]], Optional[str]],
    ) -> None:
        """Injects the alias resolver used for peer-bound redraws.

        Args:
            resolver (Callable[[Optional[str], Optional[str]], Optional[str]]): The resolver input.

        Returns:
            None
        """
        ...

    def set_focus(
        self,
        alias: Optional[str],
        transport_state: ChatTransportState = ChatTransportState.DROP,
    ) -> None:
        """Updates the prompt string to reflect the focused alias.

        Args:
            alias (Optional[str]): The alias input.
            transport_state (ChatTransportState): The transport state input.

        Returns:
            None
        """
        ...

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
        """Safely renders one new message to the UI.

        Args:
            msg (str): The msg input.
            msg_type (ChatMessageType): The msg type input.
            tone (Optional[StatusTone]): The tone input.
            alias (Optional[str]): The alias input.
            peer_onion (Optional[str]): The peer onion input.
            alias_policy (AliasPolicy): The alias policy input.
            timestamp (Optional[str]): The timestamp input.
            skip_prompt (bool): The skip prompt input.
            msg_id (Optional[str]): The msg id input.
            is_drop (bool): The is drop input.
            is_pending (bool): The is pending input.

        Returns:
            None
        """
        ...

    def print_messages_batch(
        self,
        messages_data: List[Dict[str, JsonValue]],
        alias: str,
        peer_onion: Optional[str] = None,
        is_live_flush: bool = False,
    ) -> None:
        """Processes a burst of messages in a single redraw.

        Args:
            messages_data (List[Dict[str, JsonValue]]): The messages data input.
            alias (str): The alias input.
            peer_onion (Optional[str]): The peer onion input.
            is_live_flush (bool): The is live flush input.

        Returns:
            None
        """
        ...

    def mark_acked(
        self,
        msg_id: Optional[str] = None,
        text: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """Marks a pending message as acknowledged and redraws it.

        Args:
            msg_id (Optional[str]): The msg id input.
            text (Optional[str]): The text input.
            timestamp (Optional[str]): The timestamp input.

        Returns:
            None
        """
        ...

    def mark_failed(self, msg_id: str) -> None:
        """Marks a pending message as failed and redraws it.

        Args:
            msg_id (str): The msg id input.

        Returns:
            None
        """
        ...

    def apply_fallback_to_drop(self, msg_ids: List[str]) -> None:
        """Converts hanging un-acked live messages into pending drops.

        Args:
            msg_ids (List[str]): The msg ids input.

        Returns:
            None
        """
        ...

    def refresh_alias_bindings(self) -> None:
        """Re-renders the chat buffer after alias bindings changed.

        Args:
            None

        Returns:
            None
        """
        ...

    def print_prompt(self) -> None:
        """Forces the UI to display the prompt and restore cursor visibility.

        Args:
            None

        Returns:
            None
        """
        ...

    def restore_cursor(self) -> None:
        """Restores cursor visibility without mutating the active screen state.

        Args:
            None

        Returns:
            None
        """
        ...

    def print_empty_line(self) -> None:
        """Prints an empty spacer line.

        Args:
            None

        Returns:
            None
        """
        ...

    def clear_input_area(self) -> None:
        """Clears the current input line securely.

        Args:
            None

        Returns:
            None
        """
        ...

    def clear_screen(self) -> None:
        """Wipes the terminal space and volatile message buffer.

        Args:
            None

        Returns:
            None
        """
        ...

    def read_line(self, stop_event: Optional[threading.Event] = None) -> Optional[str]:
        """Reads a full line of user input, or None when aborted.

        Args:
            stop_event (Optional[threading.Event]): The stop event input.

        Returns:
            Optional[str]: The resulting value.
        """
        ...
