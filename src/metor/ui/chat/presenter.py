"""
Module providing stateless text formatting and ANSI color logic for the interactive chat terminal.
"""

from typing import Optional, List

from metor.core.api import (
    ConnectionOrigin,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    UnreadInboxSummaryEntry,
)
from metor.ui import Theme, UIPresenter
from metor.ui.models import StatusTone

# Local Package Imports
from metor.ui.chat.models import ChatMessageType, ChatLine


class ChatPresenter:
    """Utility class for formatting chat lines, calculating visible string lengths, and converting raw data dictionaries into standardized UI strings."""

    @staticmethod
    def format_session_state(
        active: List[str],
        pending: List[str],
        contacts: List[str],
        focused: Optional[str],
        is_header_mode: bool = False,
    ) -> str:
        """
        Returns a formatted string representing active and pending connections.

        Args:
            active (List[str]): List of active connections.
            pending (List[str]): List of pending connections.
            contacts (List[str]): List of saved contacts.
            focused (Optional[str]): The currently focused alias.
            is_header_mode (bool): If True, formats without UI system decorators.

        Returns:
            str: The colorized multi-line state string.
        """
        if not active and not pending and not is_header_mode:
            return 'No active or pending sessions.'

        lines: List[str] = []
        if active:
            lines.append('Active session:')
            for alias in active:
                color: str = Theme.GREEN if alias in contacts else Theme.DARK_GREY
                marker: str = '*' if alias == focused else ' '
                lines.append(f' {color}{marker} {alias}{Theme.RESET}')
            if pending:
                lines.append('')

        if pending:
            lines.append('Pending session:')
            for p in pending:
                lines.append(f'   {Theme.DARK_GREY}{p}{Theme.RESET}')

        return '\n'.join(lines)

    @staticmethod
    def _format_pending_startup_entry(entry: PendingConnectionEntry) -> str:
        """
        Formats one retained pending-request startup entry.

        Args:
            entry (PendingConnectionEntry): The retained pending request.

        Returns:
            str: The formatted startup summary line.
        """
        line: str
        if entry.reason is PendingConnectionReasonCode.CONSUMER_ABSENT:
            if entry.origin in (
                ConnectionOrigin.AUTO_RECONNECT,
                ConnectionOrigin.GRACE_RECONNECT,
                ConnectionOrigin.RETUNNEL,
            ):
                line = f'{entry.alias}: recovery reconnect waiting for chat attach'
            else:
                line = (
                    f'{entry.alias}: incoming live request retained until chat attach'
                )
        else:
            line = f'{entry.alias}: incoming live request waiting for /accept'

        expiry_label: str = UIPresenter.format_timestamp_label(entry.expires_at)
        if expiry_label:
            line += f' until {expiry_label}'
        return line

    @staticmethod
    def _format_unread_startup_entry(entry: UnreadInboxSummaryEntry) -> str:
        """
        Formats one unread-summary startup entry.

        Args:
            entry (UnreadInboxSummaryEntry): The unread summary entry.

        Returns:
            str: The formatted startup summary line.
        """
        message_word: str = 'message' if entry.total_unread == 1 else 'messages'
        detail_parts: List[str] = []
        if entry.drop_unread > 0:
            detail_parts.append(f'{entry.drop_unread} drop')
        if entry.live_unread > 0:
            detail_parts.append(f'{entry.live_unread} live')

        detail_suffix: str = ''
        if detail_parts:
            detail_suffix = f' ({", ".join(detail_parts)})'

        return (
            f'{entry.alias}: {entry.total_unread} unread {message_word}{detail_suffix}'
        )

    @staticmethod
    def format_startup_recovery(
        pending: List[PendingConnectionEntry],
        unread: List[UnreadInboxSummaryEntry],
    ) -> str:
        """
        Formats the first-attach recovery summary for chat bootstrap.

        Args:
            pending (List[PendingConnectionEntry]): Retained pending live requests.
            unread (List[UnreadInboxSummaryEntry]): Unread inbox summaries.

        Returns:
            str: The formatted recovery summary, or an empty string.
        """
        if not pending and not unread:
            return ''

        lines: List[str] = ['Startup summary:']
        if pending:
            lines.append('Retained requests:')
            for entry in pending:
                lines.append(f'  {ChatPresenter._format_pending_startup_entry(entry)}')

        if unread:
            if pending:
                lines.append('')
            lines.append('Unread inbox:')
            for unread_entry in unread:
                lines.append(
                    f'  {ChatPresenter._format_unread_startup_entry(unread_entry)}'
                )

        return '\n'.join(lines)

    @staticmethod
    def get_visible_prefix_len(
        msg_type: ChatMessageType,
        tone: Optional[StatusTone],
        alias: Optional[str],
        is_drop: bool,
        prompt_len: int,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Calculates the exact visible length of the prefix without invisible ANSI color codes.

        Args:
            msg_type (ChatMessageType): The category of the message.
            tone (Optional[StatusTone]): The tone for status lines.
            alias (Optional[str]): The associated remote alias.
            is_drop (bool): True if the message has the [Drop] suffix.
            prompt_len (int): The length of the base prompt signature.
            timestamp (Optional[str]): Optional visible timestamp prefix.

        Returns:
            int: The visible character count of the prefix.
        """
        _, timestamp_visible = UIPresenter.build_timestamp_prefix(
            timestamp,
            is_drop=(msg_type in (ChatMessageType.SELF, ChatMessageType.REMOTE))
            and is_drop,
            compact=True,
        )

        if msg_type == ChatMessageType.STATUS:
            if tone == StatusTone.INFO:
                return len(timestamp_visible) + 4 + prompt_len
            if tone == StatusTone.ERROR:
                return len(timestamp_visible) + 5 + prompt_len
            return len(timestamp_visible) + 6 + prompt_len
        if msg_type == ChatMessageType.RAW:
            return 0
        if msg_type == ChatMessageType.SELF:
            return (
                len(timestamp_visible) + len(f'To {alias}') + prompt_len
                if alias
                else len(timestamp_visible) + 4 + prompt_len
            )
        if msg_type == ChatMessageType.REMOTE:
            return (
                len(timestamp_visible) + len(f'From {alias}') + prompt_len
                if alias
                else len(timestamp_visible) + 6 + prompt_len
            )
        return 0

    @staticmethod
    def format_msg(
        msg: ChatLine,
        initial_prompt: str,
        current_focus: Optional[str],
        resolved_alias: Optional[str] = None,
    ) -> str:
        """
        Formats a strictly typed ChatLine into a colorized CLI string.

        Args:
            msg (ChatLine): The data object containing message metadata.
            initial_prompt (str): The base prompt string (e.g., '$ ').
            current_focus (Optional[str]): The alias the user is currently focused on.
            resolved_alias (Optional[str]): The alias resolved for the current redraw.

        Returns:
            str: The fully formatted string ready for stdout.
        """
        active_alias: Optional[str] = resolved_alias if resolved_alias else msg.alias
        text: str = msg.text
        if active_alias and '{alias}' in text:
            text = text.replace('{alias}', active_alias)

        prefix: str = ''
        visible_prefix: str = ''

        timestamp_prefix: str = ''
        timestamp_visible: str = ''
        if msg.msg_type == ChatMessageType.STATUS:
            timestamp_prefix, timestamp_visible = UIPresenter.build_timestamp_prefix(
                msg.timestamp,
                compact=True,
            )
        elif msg.msg_type in (ChatMessageType.SELF, ChatMessageType.REMOTE):
            timestamp_prefix, timestamp_visible = UIPresenter.build_timestamp_prefix(
                msg.timestamp,
                is_drop=msg.is_drop,
                compact=True,
            )

        if msg.msg_type == ChatMessageType.STATUS:
            prefix_raw: str
            if msg.tone == StatusTone.INFO:
                prefix_raw = f'inf{initial_prompt}'
                prefix = f'{timestamp_prefix}{Theme.YELLOW}{prefix_raw}{Theme.RESET}'
            elif msg.tone == StatusTone.ERROR:
                prefix_raw = f'err{initial_prompt}'
                prefix = f'{timestamp_prefix}{Theme.RED}{prefix_raw}{Theme.RESET}'
            else:
                prefix_raw = f'sys{initial_prompt}'
                prefix = f'{timestamp_prefix}{Theme.CYAN}{prefix_raw}{Theme.RESET}'
            visible_prefix = f'{timestamp_visible}{prefix_raw}'
        elif msg.msg_type != ChatMessageType.RAW:
            is_focused: bool = (
                (active_alias == current_focus) if active_alias else False
            )

            if msg.msg_type == ChatMessageType.SELF:
                prefix_raw = (
                    f'To {active_alias}{initial_prompt}'
                    if active_alias
                    else f'self{initial_prompt}'
                )
                visible_prefix = f'{timestamp_visible}{prefix_raw}'

                if not is_focused:
                    prefix = (
                        f'{timestamp_prefix}{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
                    )
                else:
                    if msg.is_failed:
                        prefix = (
                            f'{timestamp_prefix}{Theme.RED}{prefix_raw}{Theme.RESET}'
                        )
                    elif msg.is_pending:
                        prefix = f'{timestamp_prefix}{prefix_raw}'
                    else:
                        prefix = (
                            f'{timestamp_prefix}{Theme.GREEN}{prefix_raw}{Theme.RESET}'
                        )

            elif msg.msg_type == ChatMessageType.REMOTE:
                prefix_raw = (
                    f'From {active_alias}{initial_prompt}'
                    if active_alias
                    else f'remote{initial_prompt}'
                )
                visible_prefix = f'{timestamp_visible}{prefix_raw}'
                prefix = (
                    f'{timestamp_prefix}{Theme.PURPLE}{prefix_raw}{Theme.RESET}'
                    if is_focused
                    else f'{timestamp_prefix}{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
                )

        if '\n' in text and msg.msg_type != ChatMessageType.RAW:
            text = UIPresenter.indent_multiline_text(
                text,
                len(visible_prefix),
            )

        return f'{prefix}{text}'
