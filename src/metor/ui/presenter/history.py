"""Presenter helpers for projected and raw history output."""

from typing import Optional

from metor.core.api import (
    HistoryDataEvent,
    HistoryEntryActor,
    HistoryEntryReasonCode,
    HistoryRawDataEvent,
    HistorySummaryEventCode,
    RawHistoryEntry,
    SummaryHistoryEntry,
)

# Local Package Imports
from metor.ui.presenter.shared import (
    build_timestamp_prefix,
    format_prefixed_message,
    get_header_string,
)
from metor.ui.theme import Theme


SUMMARY_REASON_TEXTS: dict[HistoryEntryReasonCode, str] = {
    HistoryEntryReasonCode.AUTO_FALLBACK_TO_DROP: 'automatic fallback to drop',
    HistoryEntryReasonCode.DUPLICATE_INCOMING_CONNECTED: ('peer was already connected'),
    HistoryEntryReasonCode.DUPLICATE_INCOMING_PENDING: (
        'peer already had a pending incoming request'
    ),
    HistoryEntryReasonCode.LATE_ACCEPTANCE_TIMEOUT: 'late acceptance timed out',
    HistoryEntryReasonCode.MANUAL_FALLBACK_TO_DROP: 'manual fallback to drop',
    HistoryEntryReasonCode.MAX_CONNECTIONS_REACHED: (
        'maximum concurrent connections reached'
    ),
    HistoryEntryReasonCode.MUTUAL_TIEBREAKER_LOSER: (
        'lost the mutual connect tie-break'
    ),
    HistoryEntryReasonCode.OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE: (
        'outbound attempt closed before acceptance'
    ),
    HistoryEntryReasonCode.OUTBOUND_ATTEMPT_REJECTED: ('outbound attempt rejected'),
    HistoryEntryReasonCode.PENDING_ACCEPTANCE_EXPIRED: ('pending acceptance expired'),
    HistoryEntryReasonCode.RETUNNEL_PENDING_CONNECTION_MISSING: (
        'retunnel pending connection missing'
    ),
    HistoryEntryReasonCode.RETRY_EXHAUSTED: 'retry limit exhausted',
    HistoryEntryReasonCode.UNACKED_LIVE_CONVERTED_TO_DROP: (
        'unacknowledged live messages were converted to drops'
    ),
}


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


def _format_summary_peer_label(entry: SummaryHistoryEntry) -> str:
    """
    Formats one peer identity label for projected summary output.

    Args:
        entry (SummaryHistoryEntry): The history entry.

    Returns:
        str: The formatted peer label.
    """
    alias_label: str = entry.alias or 'unknown'
    return f'{Theme.PURPLE}{alias_label}{Theme.RESET}'


def _format_raw_peer_label(entry: RawHistoryEntry) -> str:
    """
    Formats one peer identity label for raw ledger output.

    Args:
        entry (RawHistoryEntry): The history entry.

    Returns:
        str: The formatted raw peer label.
    """
    alias_label: str = entry.alias or 'unknown'
    if entry.peer_onion:
        return (
            f'{Theme.PURPLE}{alias_label}{Theme.RESET} '
            f'[{Theme.YELLOW}{entry.peer_onion}{Theme.RESET}]'
        )
    return f'{Theme.PURPLE}{alias_label}{Theme.RESET}'


def _append_reason(base: str, entry: SummaryHistoryEntry) -> str:
    """
    Appends one humanized machine-readable reason suffix when available.

    Args:
        base (str): The base summary sentence.
        entry (SummaryHistoryEntry): The history entry.

    Returns:
        str: The augmented summary sentence.
    """
    reason_text: Optional[str] = None
    if entry.detail_code is not None:
        reason_text = SUMMARY_REASON_TEXTS.get(entry.detail_code)
    if not reason_text:
        return base
    return f'{base} {Theme.DARK_GREY}Reason:{Theme.RESET} {reason_text}.'


def _describe_summary_entry(entry: SummaryHistoryEntry) -> str:
    """
    Converts one projected history entry into one concise sentence.

    Args:
        entry (SummaryHistoryEntry): The projected history entry.

    Returns:
        str: The formatted summary sentence.
    """
    peer_label: str = _format_summary_peer_label(entry)
    family_prefix: str = f'{Theme.DARK_GREY}{entry.family.value.upper()}{Theme.RESET} '

    if entry.event_code is HistorySummaryEventCode.CONNECTION_REQUESTED:
        if entry.actor is HistoryEntryActor.REMOTE:
            return f'{family_prefix}Incoming connection request from {peer_label}.'
        return f'{family_prefix}Connection request sent to {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.CONNECTED:
        return f'{family_prefix}Connected to {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.CONNECTION_REJECTED:
        if entry.actor is HistoryEntryActor.LOCAL:
            return _append_reason(
                f'{family_prefix}Rejected connection with {peer_label}.',
                entry,
            )
        return _append_reason(
            f'{family_prefix}Connection with {peer_label} rejected.',
            entry,
        )

    if entry.event_code is HistorySummaryEventCode.CONNECTION_FAILED:
        return _append_reason(
            f'{family_prefix}Connection to {peer_label} failed.',
            entry,
        )

    if entry.event_code is HistorySummaryEventCode.CONNECTION_LOST:
        return _append_reason(
            f'{family_prefix}Connection to {peer_label} lost.',
            entry,
        )

    if entry.event_code is HistorySummaryEventCode.DISCONNECTED:
        if entry.actor is HistoryEntryActor.REMOTE:
            return f'{family_prefix}{peer_label} disconnected.'
        return f'{family_prefix}Disconnected from {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.PENDING_EXPIRED:
        return f'{family_prefix}Acceptance window for {peer_label} expired.'

    if entry.event_code is HistorySummaryEventCode.RETUNNEL_INITIATED:
        return f'{family_prefix}Retunnel started for {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.RETUNNEL_SUCCEEDED:
        return f'{family_prefix}Retunnel completed for {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.DROP_QUEUED:
        return _append_reason(
            f'{family_prefix}Queued drop for {peer_label}.',
            entry,
        )

    if entry.event_code is HistorySummaryEventCode.DROP_SENT:
        return f'{family_prefix}Delivered drop to {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.DROP_RECEIVED:
        return f'{family_prefix}Received drop from {peer_label}.'

    if entry.event_code is HistorySummaryEventCode.DROP_FAILED:
        return _append_reason(
            f'{family_prefix}Drop delivery for {peer_label} failed.',
            entry,
        )

    return f'{family_prefix}{entry.event_code.value} -> {peer_label}'


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
        peer_label: str = _format_raw_peer_label(entry)
        line: str = (
            f'{Theme.DARK_GREY}family:{Theme.RESET} {Theme.CYAN}{entry.family.value}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}event:{Theme.RESET} {Theme.YELLOW}{entry.event_code.value}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}actor:{Theme.RESET} {Theme.GREEN}{entry.actor.value}{Theme.RESET}\n'
            f'{Theme.DARK_GREY}peer:{Theme.RESET} {peer_label}\n'
            f'{Theme.DARK_GREY}flow:{Theme.RESET} {Theme.CYAN}{entry.flow_id}{Theme.RESET}\n'
        )
        if entry.trigger:
            line += f'{Theme.DARK_GREY}trigger:{Theme.RESET} {Theme.CYAN}{entry.trigger.value}{Theme.RESET}\n'
        if entry.detail_code:
            line += (
                f'{Theme.DARK_GREY}detail code:{Theme.RESET} '
                f'{Theme.CYAN}{entry.detail_code.value}{Theme.RESET}\n'
            )
        if entry.detail_text:
            line += (
                f'{Theme.DARK_GREY}detail:{Theme.RESET} '
                f'{Theme.CYAN}{entry.detail_text}{Theme.RESET}\n'
            )
        out += f'{format_prefixed_message(prefix, prefix_visible, line)}\n'
    return out
