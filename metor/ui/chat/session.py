"""
Module managing the active connection states and focus targets for the UI.
"""

from typing import List, Optional

from metor.ui.theme import Theme


class Session:
    """Maintains active UI state (connections, pending connections, current focus)."""

    def __init__(self) -> None:
        """Initializes an empty session state."""
        self.focused_alias: Optional[str] = None
        self.pending_focus_target: Optional[str] = None
        self.active_connections: List[str] = []

        self.header_active: List[str] = []
        self.header_pending: List[str] = []
        self.header_contacts: List[str] = []

        self.my_onion: str = 'unknown'

    def show(self, is_header_mode: bool = False) -> str:
        """
        Returns a formatted string representing active and pending connections.

        Args:
            is_header_mode (bool): If True, formats without UI system decorators.

        Returns:
            str: The colorized multi-line state string.
        """
        active: List[str] = (
            self.header_active if is_header_mode else self.active_connections
        )
        pending: List[str] = (
            self.header_pending if is_header_mode else []
        )  # We don't track live pending outside header currently
        contacts: List[str] = self.header_contacts

        if not active and not pending and not is_header_mode:
            return 'No active or pending connections.'

        lines: List[str] = []
        if active:
            lines.append('Active session:')
            for alias in active:
                color: str = Theme.GREEN if alias in contacts else Theme.DARK_GREY
                marker: str = '*' if alias == self.focused_alias else ' '
                lines.append(f' {color}{marker} {alias}{Theme.RESET}')
            if pending:
                lines.append('')

        if pending:
            lines.append('Pending session:')
            for p in pending:
                lines.append(f'   {Theme.DARK_GREY}{p}{Theme.RESET}')

        return '\n'.join(lines)
