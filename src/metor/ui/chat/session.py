"""
Module managing the active connection states and focus targets for the UI.
"""

from typing import List, Optional


class Session:
    """Maintains active UI state (connections, pending connections, current focus)."""

    def __init__(self) -> None:
        """
        Initializes an empty session state.

        Args:
            None

        Returns:
            None
        """
        self.focused_alias: Optional[str] = None
        self.pending_focus_target: Optional[str] = None
        self.active_connections: List[str] = []

        self.header_active: List[str] = []
        self.header_pending: List[str] = []
        self.header_contacts: List[str] = []

        self.my_onion: str = 'unknown'
