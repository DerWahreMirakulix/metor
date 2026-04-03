"""Facade class exposing the modular UI presenter helpers."""

from metor.core.api import (
    ContactsDataEvent,
    HistoryDataEvent,
    HistoryRawDataEvent,
    InboxCountsEvent,
    IpcEvent,
    MessagesDataEvent,
    ProfilesDataEvent,
    UnreadMessagesEvent,
)

# Local Package Imports
from metor.ui.presenter.data import (
    format_contacts,
    format_inbox,
    format_messages,
    format_profiles,
    format_read_messages,
)
from metor.ui.presenter.history import format_history, format_raw_history
from metor.ui.presenter.shared import (
    build_timestamp_prefix,
    format_prefixed_message,
    format_timestamp_label,
    get_divider_string,
    get_header_string,
    indent_multiline_text,
)


class UIPresenter:
    """Formats typed IPC DTOs into standardized UI strings."""

    format_timestamp_label = staticmethod(format_timestamp_label)
    build_timestamp_prefix = staticmethod(build_timestamp_prefix)
    indent_multiline_text = staticmethod(indent_multiline_text)
    format_prefixed_message = staticmethod(format_prefixed_message)
    get_header_string = staticmethod(get_header_string)
    get_divider_string = staticmethod(get_divider_string)
    format_contacts = staticmethod(format_contacts)
    format_history = staticmethod(format_history)
    format_raw_history = staticmethod(format_raw_history)
    format_messages = staticmethod(format_messages)
    format_inbox = staticmethod(format_inbox)
    format_read_messages = staticmethod(format_read_messages)
    format_profiles = staticmethod(format_profiles)

    @staticmethod
    def format_response(event: IpcEvent, chat_mode: bool = False) -> str:
        """
        Routes the DTO to the appropriate formatter based on its concrete type.

        Args:
            event (IpcEvent): The strictly typed IPC response event.
            chat_mode (bool): Whether chat-specific layout should be applied.

        Returns:
            str: The formatted terminal string.
        """
        if isinstance(event, ContactsDataEvent):
            return format_contacts(event, chat_mode)
        if isinstance(event, HistoryDataEvent):
            return format_history(event)
        if isinstance(event, HistoryRawDataEvent):
            return format_raw_history(event)
        if isinstance(event, MessagesDataEvent):
            return format_messages(event)
        if isinstance(event, InboxCountsEvent):
            return format_inbox(event)
        if isinstance(event, UnreadMessagesEvent):
            return format_read_messages(event)
        if isinstance(event, ProfilesDataEvent):
            return format_profiles(event)

        return 'No formatter available for this data.'
