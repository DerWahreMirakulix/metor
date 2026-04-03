"""Presenter helpers for projected and raw history output."""

from typing import Optional

from metor.core.api import HistoryDataEvent, HistoryEntry, HistoryRawDataEvent

# Local Package Imports
from metor.ui.presenter.shared import (
    build_timestamp_prefix,
    format_prefixed_message,
    get_header_string,
)
from metor.ui.theme import Theme


def _format_scope_label(
    profile: str,
    alias: Optional[str],
) -> str:
    """
    Resolves the formatted scope label for history headers.

    Args:
        profile (str): The active profile name.
        alias (Optional[str]): The filtered peer alias.

    Returns:
        str: The formatted scope label.
    """
    if alias:
        return f'peer {Theme.PURPLE}{alias}{Theme.RESET}'
    return f'profile {Theme.CYAN}{profile}{Theme.RESET}'


def _format_peer_label(entry: HistoryEntry) -> str:
    """
    Formats one peer identity label for history output.

    Args:
        entry (HistoryEntry): The history entry.

    Returns:
        str: The formatted peer label.
    """
    alias_label: str = entry.alias or 'unknown'
    if entry.peer_onion:
        return (
            f'{Theme.PURPLE}{alias_label}{Theme.RESET} '
            f'[{Theme.YELLOW}{entry.peer_onion}{Theme.RESET}]'
        )
    return f'{Theme.PURPLE}{alias_label}{Theme.RESET}'


def _append_detail_text(base: str, entry: HistoryEntry) -> str:
    """
    Appends one concise detail suffix when additional context exists.

    Args:
        base (str): The base summary sentence.
        entry (HistoryEntry): The history entry.

    Returns:
        str: The augmented summary sentence.
    """
    if entry.detail_text:
        return f'{base} {Theme.DARK_GREY}[{entry.detail_text}]{Theme.RESET}'
    return base


def _describe_summary_entry(entry: HistoryEntry) -> str:
    """
    Converts one projected history entry into one concise sentence.

    Args:
        entry (HistoryEntry): The projected history entry.

    Returns:
        str: The formatted summary sentence.
    """
    peer_label: str = _format_peer_label(entry)
    family_prefix: str = f'{Theme.DARK_GREY}{entry.family.upper()}{Theme.RESET} '

    if entry.event_code == 'connection_requested':
        if entry.actor == 'remote':
            return f'{family_prefix}Incoming connection request from {peer_label}.'
        return f'{family_prefix}Connection request sent to {peer_label}.'

    if entry.event_code == 'connected':
        return f'{family_prefix}Connected to {peer_label}.'

    if entry.event_code == 'connection_rejected':
        if entry.actor == 'local':
            return f'{family_prefix}Rejected connection with {peer_label}.'
        return f'{family_prefix}Connection with {peer_label} rejected.'

    if entry.event_code == 'connection_failed':
        return _append_detail_text(
            f'{family_prefix}Connection to {peer_label} failed.',
            entry,
        )

    if entry.event_code == 'connection_lost':
        return _append_detail_text(
            f'{family_prefix}Connection to {peer_label} lost.',
            entry,
        )

    if entry.event_code == 'disconnected':
        if entry.actor == 'remote':
            return f'{family_prefix}{peer_label} disconnected.'
        return f'{family_prefix}Disconnected from {peer_label}.'

    if entry.event_code == 'pending_expired':
        return f'{family_prefix}Acceptance window for {peer_label} expired.'

    if entry.event_code == 'retunnel_initiated':
        return f'{family_prefix}Retunnel started for {peer_label}.'

    if entry.event_code == 'retunnel_succeeded':
        return f'{family_prefix}Retunnel completed for {peer_label}.'

    if entry.event_code == 'drop_queued':
        return _append_detail_text(
            f'{family_prefix}Queued drop for {peer_label}.',
            entry,
        )

    if entry.event_code == 'drop_sent':
        return f'{family_prefix}Delivered drop to {peer_label}.'

    if entry.event_code == 'drop_received':
        return f'{family_prefix}Received drop from {peer_label}.'

    if entry.event_code == 'drop_failed':
        return _append_detail_text(
            f'{family_prefix}Drop delivery for {peer_label} failed.',
            entry,
        )

    return f'{family_prefix}{entry.event_code} -> {peer_label}'


def format_history(event: HistoryDataEvent) -> str:
    """
    Formats projected user-facing history summary rows.

    Args:
        event (HistoryDataEvent): The history summary DTO.

    Returns:
        str: The formatted history output.
    """
    scope_label: str = _format_scope_label(event.profile, event.alias)
    if not event.entries:
        return f'No history available for {scope_label}.'

    header_text: str = f'History for {scope_label} (Last {len(event.entries)})'
    out: str = f'{get_header_string(header_text)}\n'
    for entry in event.entries:
        prefix, prefix_visible = build_timestamp_prefix(entry.timestamp)
        out += f'{format_prefixed_message(prefix, prefix_visible, _describe_summary_entry(entry))}\n'
    return out


def format_raw_history(event: HistoryRawDataEvent) -> str:
    """
    Formats raw transport history ledger rows.

    Args:
        event (HistoryRawDataEvent): The raw history DTO.

    Returns:
        str: The formatted raw history output.
    """
    scope_label: str = _format_scope_label(event.profile, event.alias)
    if not event.entries:
        return f'No raw history available for {scope_label}.'

    header_text: str = f'Raw History for {scope_label} (Last {len(event.entries)})'
    out: str = f'{get_header_string(header_text)}\n'
    for entry in event.entries:
        prefix, prefix_visible = build_timestamp_prefix(entry.timestamp)
        peer_label: str = _format_peer_label(entry)
        line: str = (
            f'{Theme.DARK_GREY}family:{Theme.RESET} {Theme.CYAN}{entry.family}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}event:{Theme.RESET} {Theme.YELLOW}{entry.event_code}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}actor:{Theme.RESET} {Theme.GREEN}{entry.actor}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}peer:{Theme.RESET} {peer_label}\n'
            f'{Theme.DARK_GREY}flow:{Theme.RESET} {Theme.CYAN}{entry.flow_id}{Theme.RESET}\n'
        )
        if entry.trigger:
            line += f'{Theme.DARK_GREY}trigger:{Theme.RESET} {Theme.CYAN}{entry.trigger}{Theme.RESET}\n'
        if entry.detail_code:
            line += (
                f'{Theme.DARK_GREY}detail code:{Theme.RESET} '
                f'{Theme.CYAN}{entry.detail_code}{Theme.RESET}\n'
            )
        if entry.detail_text:
            line += (
                f'{Theme.DARK_GREY}detail:{Theme.RESET} '
                f'{Theme.CYAN}{entry.detail_text}{Theme.RESET}\n'
            )
        out += f'{format_prefixed_message(prefix, prefix_visible, line)}\n'
    return out
