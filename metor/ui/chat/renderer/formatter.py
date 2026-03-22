"""
Module providing stateless text formatting and ANSI color logic for the terminal.
"""

from typing import Optional, List

from metor.ui.theme import Theme
from metor.ui.chat.models import UIMessageType, UIChatLine


class Formatter:
    """Utility class for formatting chat lines and calculating visible string lengths."""

    @staticmethod
    def get_visible_prefix_len(
        msg_type: UIMessageType, alias: Optional[str], is_drop: bool, prompt_len: int
    ) -> int:
        """
        Calculates the exact visible length of the prefix without invisible ANSI color codes.

        Args:
            msg_type (UIMessageType): The category of the message.
            alias (Optional[str]): The associated remote alias.
            is_drop (bool): True if the message has the [Drop] suffix.
            prompt_len (int): The length of the base prompt signature.

        Returns:
            int: The visible character count of the prefix.
        """
        drop_len: int = len(' [Drop]') if is_drop else 0

        if msg_type == UIMessageType.INFO:
            return 4 + prompt_len
        if msg_type == UIMessageType.SYSTEM:
            return 6 + prompt_len
        if msg_type == UIMessageType.RAW:
            return 0
        if msg_type == UIMessageType.SELF:
            return (
                len(f'To {alias}') + drop_len + prompt_len
                if alias
                else 4 + drop_len + prompt_len
            )
        if msg_type == UIMessageType.REMOTE:
            return (
                len(f'From {alias}') + drop_len + prompt_len
                if alias
                else 6 + drop_len + prompt_len
            )
        return 0

    @staticmethod
    def format_msg(
        msg: UIChatLine, initial_prompt: str, current_focus: Optional[str]
    ) -> str:
        """
        Formats a strictly typed UIChatLine into a colorized CLI string.

        Args:
            msg (UIChatLine): The data object containing message metadata.
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

        if msg.msg_type == UIMessageType.INFO:
            prefix = f'{Theme.YELLOW}info{initial_prompt}{Theme.RESET}'
        elif msg.msg_type == UIMessageType.SYSTEM:
            prefix = f'{Theme.CYAN}system{initial_prompt}{Theme.RESET}'
        elif msg.msg_type != UIMessageType.RAW:
            is_focused: bool = (msg.alias == current_focus) if msg.alias else False

            if msg.msg_type == UIMessageType.SELF:
                prefix_raw: str = (
                    f'To {msg.alias}{drop_tag}{initial_prompt}'
                    if msg.alias
                    else f'self{drop_tag}{initial_prompt}'
                )

                if not is_focused:
                    prefix = f'{Theme.DARK_GREY}{prefix_raw}{Theme.RESET}'
                else:
                    if msg.is_pending:
                        prefix = prefix_raw
                    else:
                        prefix = f'{Theme.GREEN}{prefix_raw}{Theme.RESET}'

            elif msg.msg_type == UIMessageType.REMOTE:
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

        if '\n' in text and msg.msg_type != UIMessageType.RAW:
            pad_len: int = Formatter.get_visible_prefix_len(
                msg.msg_type, msg.alias, msg.is_drop, len(initial_prompt)
            )
            padding: str = ' ' * pad_len
            lines: List[str] = text.split('\n')
            text = f'\n{padding}'.join(lines)

        return f'{prefix}{text}'
