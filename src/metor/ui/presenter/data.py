"""Presenter helpers for contacts, messages, inbox, and profiles."""

from typing import List

from metor.core.api import (
    ContactsDataEvent,
    InboxCountsEvent,
    MessagesDataEvent,
    ProfilesDataEvent,
    UnreadMessagesEvent,
)
from metor.data import MessageDirection, MessageStatus

# Local Package Imports
from metor.ui.presenter.shared import (
    build_timestamp_prefix,
    format_prefixed_message,
    get_header_string,
)
from metor.ui.theme import Theme


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
            lines.append(f'   {Theme.GREEN}{entry.alias}{Theme.RESET} -> {entry.onion}')
    else:
        lines.append(f'No contacts in address book{profile_suffix}.')

    if event.discovered:
        lines.append('\nDiscovered peers:')
        for entry in event.discovered:
            lines.append(
                f'   {Theme.DARK_GREY}{entry.alias}{Theme.RESET} -> {entry.onion}'
            )

    return '\n'.join(lines)


def format_messages(event: MessagesDataEvent) -> str:
    """
    Formats the stored chat history for one peer.

    Args:
        event (MessagesDataEvent): The message history DTO.

    Returns:
        str: The formatted message history.
    """
    if not event.messages:
        return f"No chat history found for '{event.alias}'."

    header_text: str = (
        f'Chat History with {Theme.CYAN}{event.alias}{Theme.RESET} '
        f'(Last {len(event.messages)})'
    )
    out: str = f'{get_header_string(header_text)}\n'
    for msg in event.messages:
        if msg.direction == MessageDirection.OUT.value:
            prefix_text: str = f'To {event.alias}: '
            rendered_prefix_text: str = (
                f'{Theme.GREEN}{prefix_text}{Theme.RESET}'
                if msg.status == MessageStatus.DELIVERED.value
                else prefix_text
            )
        else:
            prefix_text = f'From {event.alias}: '
            rendered_prefix_text = f'{Theme.PURPLE}{prefix_text}{Theme.RESET}'

        timestamp_prefix, timestamp_visible = build_timestamp_prefix(msg.timestamp)
        out += (
            format_prefixed_message(
                f'{timestamp_prefix}{rendered_prefix_text}',
                f'{timestamp_visible}{prefix_text}',
                msg.payload,
            )
            + '\n'
        )

    return out


def format_inbox(event: InboxCountsEvent) -> str:
    """
    Formats current unread inbox counts.

    Args:
        event (InboxCountsEvent): The inbox count DTO.

    Returns:
        str: The formatted inbox count output.
    """
    if not event.inbox:
        return 'Inbox is empty.'

    out: str = 'Unread messages:\n'
    for alias, count in event.inbox.items():
        out += (
            f' - {Theme.PURPLE}{alias}{Theme.RESET}: '
            f'{Theme.YELLOW}{count}{Theme.RESET} new message(s)\n'
        )

    return out.strip()


def format_read_messages(event: UnreadMessagesEvent) -> str:
    """
    Formats unread messages fetched explicitly from the inbox.

    Args:
        event (UnreadMessagesEvent): The unread message DTO.

    Returns:
        str: The colorized terminal output displaying the messages.
    """
    if not event.messages:
        return f"No unread messages from '{event.alias}'."

    header_text: str = f'Unread messages from {Theme.PURPLE}{event.alias}{Theme.RESET}'
    out: str = f'{get_header_string(header_text)}\n'
    for msg in event.messages:
        prefix_text: str = f'From {event.alias}: '
        rendered_prefix_text: str = f'{Theme.PURPLE}{prefix_text}{Theme.RESET}'
        timestamp_prefix, timestamp_visible = build_timestamp_prefix(
            msg.timestamp,
            is_drop=msg.is_drop,
        )
        out += (
            format_prefixed_message(
                f'{timestamp_prefix}{rendered_prefix_text}',
                f'{timestamp_visible}{prefix_text}',
                msg.payload,
            )
            + '\n'
        )

    return out


def format_profiles(event: ProfilesDataEvent) -> str:
    """
    Formats the list of isolated profiles.

    Args:
        event (ProfilesDataEvent): The profile list DTO.

    Returns:
        str: The formatted profile list.
    """
    if not event.profiles:
        return 'No profiles found.'

    lines: List[str] = ['Available profiles:']
    for profile in event.profiles:
        marker: str = '*' if profile.is_active else ' '
        tags: List[str] = []

        if profile.is_remote:
            tags.append('REMOTE')
        elif profile.port:
            tags.append(f'PORT:{profile.port}')

        tag_str: str = f' [{Theme.YELLOW}{"|".join(tags)}{Theme.RESET}]' if tags else ''

        if profile.is_active:
            lines.append(f' {Theme.GREEN}{marker} {profile.name}{Theme.RESET}{tag_str}')
        else:
            lines.append(f'   {profile.name}{tag_str}')

    return '\n'.join(lines)
