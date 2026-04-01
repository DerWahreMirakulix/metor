"""
Module providing centralized UI presentation logic.
Transforms strictly typed DTOs into formatted strings for both CLI and Chat interfaces.
Enforces the Zero-Text Policy by offloading formatting from the backend.
"""

from typing import List

from metor.core.api import (
    IpcEvent,
    ContactsDataEvent,
    HistoryDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
)
from metor.data import MessageDirection, MessageStatus

# Local Package Imports
from metor.ui.theme import Theme


class UIPresenter:
    """Formats strongly typed DTOs into standardized UI strings."""

    @staticmethod
    def get_header_string(text: str) -> str:
        """
        Creates a simple header string with the given text.

        Args:
            text (str): The header text to display.

        Returns:
            str: The formatted header string.
        """
        return f'\n--- {text} ---\n'

    @staticmethod
    def get_divider_string(length: int = 30, add_spaces: bool = False) -> str:
        """
        Generates a divider string consisting of dashes.

        Args:
            length (int): The number of dashes in the divider.
            add_spaces (bool): Whether to add a space between the dashes.

        Returns:
            str: The divider string.
        """
        divider = '-' * length
        if add_spaces:
            divider = ' '.join(divider)
        return divider

    @staticmethod
    def format_response(event: IpcEvent, chat_mode: bool = False) -> str:
        """
        Routes the DTO to the appropriate formatting function based on its concrete type.

        Args:
            event (IpcEvent): The strictly typed IPC response event.
            chat_mode (bool): Flag to apply Chat-specific layout adjustments.

        Returns:
            str: The formatted terminal string.
        """
        if isinstance(event, ContactsDataEvent):
            return UIPresenter.format_contacts(event, chat_mode)
        if isinstance(event, HistoryDataEvent):
            return UIPresenter.format_history(event)
        if isinstance(event, MessagesDataEvent):
            return UIPresenter.format_messages(event)
        if isinstance(event, InboxCountsEvent):
            return UIPresenter.format_inbox(event)
        if isinstance(event, UnreadMessagesEvent):
            return UIPresenter.format_read_messages(event)
        if isinstance(event, ProfilesDataEvent):
            return UIPresenter.format_profiles(event)

        return 'No formatter available for this data.'

    @staticmethod
    def format_contacts(event: ContactsDataEvent, chat_mode: bool) -> str:
        """
        Formats the address book and discovered peers.

        Args:
            event (ContactsDataEvent): The contacts data DTO.
            chat_mode (bool): Whether to format strictly for the chat UI.

        Returns:
            str: The formatted contacts list.
        """
        profile_suffix: str = '' if chat_mode else f" for profile '{event.profile}'"
        lines: List[str] = []

        if event.saved:
            lines.append(f'Available contacts{profile_suffix}:')
            for entry in event.saved:
                lines.append(
                    f'   {Theme.GREEN}{entry.alias}{Theme.RESET} -> {entry.onion}'
                )
        else:
            lines.append(f'No contacts in address book{profile_suffix}.')

        if event.discovered:
            lines.append('\nDiscovered peers:')
            for entry in event.discovered:
                lines.append(
                    f'   {Theme.DARK_GREY}{entry.alias}{Theme.RESET} -> {entry.onion}'
                )

        return '\n'.join(lines)

    @staticmethod
    def format_history(event: HistoryDataEvent) -> str:
        """
        Formats the historical connection events.

        Args:
            event (HistoryDataEvent): The history data DTO.

        Returns:
            str: The formatted event history output.
        """
        if event.alias:
            disp_name: str = f'peer {Theme.CYAN}{event.alias}{Theme.RESET}'
        else:
            disp_name = f'profile {Theme.CYAN}{event.profile}{Theme.RESET}'

        if not event.history:
            return f'No event history available for {disp_name}.'

        out: str = f'{UIPresenter.get_header_string(f"Event history for {disp_name} (Last {len(event.history)})")}\n'

        for item in event.history:
            row_onion: str = item.onion or 'Unknown'
            row_alias: str = item.alias or 'n/a'
            line: str = f'[{item.timestamp}] {Theme.CYAN}{item.status}{Theme.RESET} | remote alias: {Theme.PURPLE}{row_alias}{Theme.RESET} | remote identity: {Theme.YELLOW}{row_onion}{Theme.RESET}'
            if item.reason:
                line += f' | reason: {Theme.CYAN}{item.reason}{Theme.RESET}'
            out += f'{line}\n'

        return out

    @staticmethod
    def format_messages(event: MessagesDataEvent) -> str:
        """
        Formats the historical message record.

        Args:
            event (MessagesDataEvent): The message history data DTO.

        Returns:
            str: The formatted terminal output of the chat history.
        """
        if not event.messages:
            return f"No chat history found for '{event.alias}'."

        out: str = f'{UIPresenter.get_header_string(f"Chat History with {Theme.CYAN}{event.alias}{Theme.RESET} (Last {len(event.messages)})")}\n'
        for msg in event.messages:
            if msg.direction == MessageDirection.OUT.value:
                if msg.status == MessageStatus.DELIVERED.value:
                    prefix: str = f'{Theme.GREEN}To {event.alias}{Theme.RESET}'
                else:
                    prefix = f'To {event.alias}'
            else:
                prefix = f'{Theme.PURPLE}From {event.alias}{Theme.RESET}'

            out += f'[{msg.timestamp}] {prefix}: {msg.payload}\n'

        return out

    @staticmethod
    def format_inbox(event: InboxCountsEvent) -> str:
        """
        Formats the current unread inbox counts.

        Args:
            event (InboxCountsEvent): The inbox counts DTO.

        Returns:
            str: Formatting string output.
        """
        if not event.inbox:
            return 'Inbox is empty.'

        out: str = 'Unread Offline Messages:\n'
        for alias, count in event.inbox.items():
            out += f' - {Theme.CYAN}{alias}{Theme.RESET}: {Theme.YELLOW}{count}{Theme.RESET} new message(s)\n'

        return out.strip()

    @staticmethod
    def format_read_messages(event: UnreadMessagesEvent) -> str:
        """
        Formats unread messages fetched from the inbox.

        Args:
            event (UnreadMessagesEvent): The unread messages DTO.

        Returns:
            str: The colorized terminal output displaying the messages.
        """
        if not event.messages:
            return f"No unread messages from '{event.alias}'."

        out: str = f'{UIPresenter.get_header_string(f"Messages from {Theme.CYAN}{event.alias}{Theme.RESET}")}\n'
        for msg in event.messages:
            prefix: str = f'{Theme.PURPLE}From {event.alias}{Theme.RESET}'
            out += f'[{msg.timestamp}] {prefix}: {msg.payload}\n'

        return out

    @staticmethod
    def format_profiles(event: ProfilesDataEvent) -> str:
        """
        Formats the list of isolated profiles.

        Args:
            event (ProfilesDataEvent): The profiles data DTO.

        Returns:
            str: Formatted terminal string.
        """
        if not event.profiles:
            return 'No profiles found.'

        lines: List[str] = ['Available profiles:']
        for p in event.profiles:
            marker: str = '*' if p.is_active else ' '
            tags: List[str] = []

            if p.is_remote:
                tags.append('REMOTE')
            elif p.port:
                tags.append(f'PORT:{p.port}')

            tag_str: str = (
                f' [{Theme.YELLOW}{"|".join(tags)}{Theme.RESET}]' if tags else ''
            )

            if p.is_active:
                lines.append(f' {Theme.GREEN}{marker} {p.name}{Theme.RESET}{tag_str}')
            else:
                lines.append(f'   {p.name}{tag_str}')

        return '\n'.join(lines)
