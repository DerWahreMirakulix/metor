"""
Module providing stateless text formatting and ANSI color logic for the interactive chat terminal.
"""

from typing import Optional, List

from metor.ui import Theme
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
    def get_visible_prefix_len(
        msg_type: ChatMessageType,
        tone: Optional[StatusTone],
        alias: Optional[str],
        is_drop: bool,
        prompt_len: int,
    ) -> int:
        """
        Calculates the exact visible length of the prefix without invisible ANSI color codes.

        Args:
            msg_type (ChatMessageType): The category of the message.
            tone (Optional[StatusTone]): The tone for status lines.
            alias (Optional[str]): The associated remote alias.
            is_drop (bool): True if the message has the [Drop] suffix.
            prompt_len (int): The length of the base prompt signature.

        Returns:
            int: The visible character count of the prefix.
        """
        drop_len: int = len(' [Drop]') if is_drop else 0

        if msg_type == ChatMessageType.STATUS:
            if tone == StatusTone.INFO:
                return 4 + prompt_len
            if tone == StatusTone.ERROR:
                return 5 + prompt_len
            return 6 + prompt_len
        if msg_type == ChatMessageType.RAW:
            return 0
        if msg_type == ChatMessageType.SELF:
            return (
                len(f'To {alias}') + drop_len + prompt_len
                if alias
                else 4 + drop_len + prompt_len
            )
        if msg_type == ChatMessageType.REMOTE:
            return (
                len(f'From {alias}') + drop_len + prompt_len
                if alias
                else 6 + drop_len + prompt_len
            )
        return 0

    @staticmethod
    def format_msg(
        msg: ChatLine, initial_prompt: str, current_focus: Optional[str]
    ) -> str:
        """
        Formats a strictly typed ChatLine into a colorized CLI string.

        Args:
            msg (ChatLine): The data object containing message metadata.
            initial_prompt (str): The base prompt string (e.g., '$ ').
            current_focus (Optional[str]): The alias the user is currently focused on.

        Returns:
            str: The fully formatted string ready for stdout.
        """
        text: str = msg.text
        if msg.alias and '{alias}' in text:
            text = text.replace('{alias}', msg.alias)

        prefix: str = ''
        drop_tag: str = ' [Drop]' if msg.is_drop else ''

        if msg.msg_type == ChatMessageType.STATUS:
            if msg.tone == StatusTone.INFO:
                prefix = f'{Theme.YELLOW}info{initial_prompt}{Theme.RESET}'
            elif msg.tone == StatusTone.ERROR:
                prefix = f'{Theme.RED}error{initial_prompt}{Theme.RESET}'
            else:
                prefix = f'{Theme.CYAN}system{initial_prompt}{Theme.RESET}'
        elif msg.msg_type != ChatMessageType.RAW:
            is_focused: bool = (msg.alias == current_focus) if msg.alias else False

            if msg.msg_type == ChatMessageType.SELF:
                prefix_raw: str = (
                    f'To {msg.alias}{drop_tag}{initial_prompt}'
                    if msg.alias
                    else f'self{drop_tag}{initial_prompt}'
                )

                if not is_focused:
                    prefix = f'{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
                else:
                    if msg.is_failed:
                        prefix = f'{Theme.RED}{prefix_raw}{Theme.RESET}'
                    elif msg.is_pending:
                        prefix = prefix_raw
                    else:
                        prefix = f'{Theme.GREEN}{prefix_raw}{Theme.RESET}'

            elif msg.msg_type == ChatMessageType.REMOTE:
                prefix_raw = (
                    f'From {msg.alias}{drop_tag}{initial_prompt}'
                    if msg.alias
                    else f'remote{drop_tag}{initial_prompt}'
                )
                prefix = (
                    f'{Theme.PURPLE}{prefix_raw}{Theme.RESET}'
                    if is_focused
                    else f'{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
                )

        if '\n' in text and msg.msg_type != ChatMessageType.RAW:
            pad_len: int = ChatPresenter.get_visible_prefix_len(
                msg.msg_type,
                msg.tone,
                msg.alias,
                msg.is_drop,
                len(initial_prompt),
            )
            padding: str = ' ' * pad_len
            lines: List[str] = text.split('\n')
            text = f'\n{padding}'.join(lines)

        return f'{prefix}{text}'
