"""
Module providing centralized UI presentation logic.
Transforms raw domain data into formatted strings for both CLI and Chat interfaces.
Enforces the Zero-Text Policy by offloading formatting from the backend.
"""

from typing import Dict, Any, List, Tuple, Optional

from metor.core.api import Action
from metor.data import MessageDirection, MessageStatus

# Local Package Imports
from metor.ui.theme import Theme


class UIPresenter:
    """Formats raw data dictionaries into standardized UI strings."""

    @staticmethod
    def get_header_string(text: str) -> str:
        """
        Creates a simple header string with the given text.

        Args:
            text (str): The header text to display.

        Returns:
            str: The formatted header string.
        """
        return f'--- {text} ---'

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
    def format_response(
        action: Action, data: Dict[str, Any], chat_mode: bool = False
    ) -> str:
        """
        Routes the raw data to the appropriate formatting function based on the IPC action.

        Args:
            action (Action): The executed IPC command action.
            data (Dict[str, Any]): The raw data payload.
            chat_mode (bool): Flag to apply Chat-specific layout adjustments.

        Returns:
            str: The formatted terminal string.
        """
        if action == Action.GET_CONTACTS_LIST:
            return UIPresenter.format_contacts(data, chat_mode)
        if action == Action.GET_HISTORY:
            return UIPresenter.format_history(data)
        if action == Action.GET_MESSAGES:
            return UIPresenter.format_messages(data)
        if action == Action.GET_INBOX:
            return UIPresenter.format_inbox(data)
        if action == Action.MARK_READ:
            return UIPresenter.format_read_messages(data)
        return 'No formatter available for this data.'

    @staticmethod
    def format_contacts(data: Dict[str, Any], chat_mode: bool) -> str:
        """
        Formats the address book and discovered peers.

        Args:
            data (Dict[str, Any]): Raw contacts data.
            chat_mode (bool): Whether to format strictly for the chat UI.

        Returns:
            str: The formatted contacts list.
        """
        profile_suffix: str = (
            '' if chat_mode else f" for profile '{data.get('profile', '')}'"
        )
        lines: List[str] = []

        saved: List[Tuple[str, str]] = data.get('saved', [])
        if saved:
            lines.append(f'Available contacts{profile_suffix}:')
            for row in saved:
                lines.append(f'   {Theme.GREEN}{row[0]}{Theme.RESET} -> {row[1]}')
        else:
            lines.append(f'No contacts in address book{profile_suffix}.')

        discovered: List[Tuple[str, str]] = data.get('discovered', [])
        if discovered:
            lines.append('\nDiscovered peers:')
            for row in discovered:
                lines.append(f'   {Theme.DARK_GREY}{row[0]}{Theme.RESET} -> {row[1]}')

        return '\n'.join(lines)

    @staticmethod
    def format_history(data: Dict[str, Any]) -> str:
        """
        Formats the historical connection events.

        Args:
            data (Dict[str, Any]): Raw history data.

        Returns:
            str: The formatted event history output.
        """
        history: List[Dict[str, Any]] = data.get('history', [])
        target: str = data.get('target', '')
        profile: str = data.get('profile', '')

        if target:
            disp_name: str = f'peer {Theme.CYAN}{target}{Theme.RESET}'
        else:
            disp_name = f'profile {Theme.CYAN}{profile}{Theme.RESET}'

        if not history:
            return f'No event history available for {disp_name}.'

        out: str = f'{UIPresenter.get_header_string(f"Event history for {disp_name} (Last {len(history)})")}\n'

        for item in history:
            timestamp: str = item.get('timestamp', '')
            status: str = item.get('status', '')
            row_onion: str = item.get('onion') or 'Unknown'
            reason: str = item.get('reason', '')
            display_alias: str = item.get('alias', 'Unknown')

            line: str = f'[{timestamp}] {Theme.CYAN}{status}{Theme.RESET} | remote alias: {Theme.PURPLE}{display_alias}{Theme.RESET} | remote identity: {Theme.YELLOW}{row_onion}{Theme.RESET}'
            if reason:
                line += f' | reason: {Theme.CYAN}{reason}{Theme.RESET}'
            out += f'{line}\n'

        out += UIPresenter.get_divider_string()
        return out

    @staticmethod
    def format_messages(data: Dict[str, Any]) -> str:
        """
        Formats the historical message record.

        Args:
            data (Dict[str, Any]): Raw message history data.

        Returns:
            str: The formatted terminal output of the chat history.
        """
        messages: List[Dict[str, Any]] = data.get('messages', [])
        target: str = data.get('target', '')

        if not messages:
            return f"No chat history found for '{target}'."

        out: str = f'{UIPresenter.get_header_string(f"Chat History with {Theme.CYAN}{target}{Theme.RESET} (Last {len(messages)})")}\n'
        for msg in messages:
            time_str: str = msg.get('timestamp', '')
            direction: str = msg.get('direction', '')
            status: str = msg.get('status', '')
            payload: str = msg.get('payload', '')

            if direction == MessageDirection.OUT.value:
                if status == MessageStatus.DELIVERED.value:
                    prefix: str = f'{Theme.GREEN}To {target}{Theme.RESET}'
                else:
                    prefix = f'To {target}'
            else:
                prefix = f'{Theme.PURPLE}From {target}{Theme.RESET}'

            out += f'[{time_str}] {prefix}: {payload}\n'

        out += UIPresenter.get_divider_string()
        return out

    @staticmethod
    def format_inbox(data: Dict[str, Any]) -> str:
        """
        Formats the current unread inbox counts.

        Args:
            data (Dict[str, Any]): Dictionary mapping aliases to their unread message count.

        Returns:
            str: Formatting string output.
        """
        inbox: Dict[str, int] = data.get('inbox', {})
        if not inbox:
            return 'Inbox is empty.'

        out: str = 'Unread Offline Messages:\n'
        for alias, count in inbox.items():
            out += f' - {Theme.CYAN}{alias}{Theme.RESET}: {Theme.YELLOW}{count}{Theme.RESET} new message(s)\n'

        return out.strip()

    @staticmethod
    def format_read_messages(data: Dict[str, Any]) -> str:
        """
        Formats unread messages fetched from the inbox.

        Args:
            data (Dict[str, Any]): Raw unread messages data.

        Returns:
            str: The colorized terminal output displaying the messages.
        """
        messages: List[Dict[str, str]] = data.get('messages', [])
        target: str = data.get('target', '')

        if not messages:
            return f"No unread messages from '{target}'."

        out: str = f'{UIPresenter.get_header_string(f"Messages from {Theme.CYAN}{target}{Theme.RESET}")}\n'
        for msg in messages:
            timestamp: str = msg.get('timestamp', '')
            payload: str = msg.get('payload', '')
            prefix: str = f'{Theme.PURPLE}From {target}{Theme.RESET}'
            out += f'[{timestamp}] {prefix}: {payload}\n'

        out += UIPresenter.get_divider_string()
        return out

    @staticmethod
    def format_profiles(data: Dict[str, Any]) -> str:
        """
        Formats the list of isolated profiles.

        Args:
            data (Dict[str, Any]): Raw profile metadata.

        Returns:
            str: Formatted terminal string.
        """
        profiles: List[Dict[str, Any]] = data.get('profiles', [])
        if not profiles:
            return 'No profiles found.'

        lines: List[str] = ['Available profiles:']
        for p in profiles:
            name: str = p.get('name', '')
            is_active: bool = p.get('is_active', False)
            is_remote: bool = p.get('is_remote', False)
            port: Optional[int] = p.get('port')

            marker: str = '*' if is_active else ' '
            tags: List[str] = []

            if is_remote:
                tags.append('REMOTE')
            elif port:
                tags.append(f'PORT:{port}')

            tag_str: str = (
                f' [{Theme.YELLOW}{"|".join(tags)}{Theme.RESET}]' if tags else ''
            )

            if is_active:
                lines.append(f' {Theme.GREEN}{marker} {name}{Theme.RESET}{tag_str}')
            else:
                lines.append(f'   {name}{tag_str}')

        return '\n'.join(lines)
