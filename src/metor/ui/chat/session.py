"""
Module managing the active connection states and focus targets for the UI.
"""

from typing import Dict, List, Optional, Set

from metor.utils import clean_onion


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
        self.pending_accept_focus_target: Optional[str] = None
        self.active_connections: List[str] = []
        self.pending_connections: List[str] = []
        self._peer_alias_by_onion: Dict[str, str] = {}
        self._peer_onion_by_alias: Dict[str, str] = {}
        self._retunneling_onions: Set[str] = set()

        self.header_active: List[str] = []
        self.header_pending: List[str] = []
        self.header_contacts: List[str] = []

        self.my_onion: str = 'unknown'

    def is_connected(self, alias: Optional[str]) -> bool:
        """
        Checks whether the UI currently treats a peer as live-connected.

        Args:
            alias (Optional[str]): The peer alias.

        Returns:
            bool: True if the alias is in the active live set.
        """
        return alias in self.active_connections if alias else False

    def _resolve_peer_identity(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> Optional[str]:
        """
        Resolves one stable peer identity for retunnel state tracking.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            Optional[str]: The canonical peer identity, if known.
        """
        if onion:
            return clean_onion(onion)
        if alias:
            mapped_onion: Optional[str] = self._peer_onion_by_alias.get(alias)
            if mapped_onion:
                return mapped_onion
        return None

    def mark_retunneling(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """
        Marks one peer as currently inside the retunnel window.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            None
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return
        self._retunneling_onions.add(identity)

    def clear_retunneling(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """
        Clears the retunnel marker for one peer.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            None
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return
        self._retunneling_onions.discard(identity)

    def is_retunneling(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> bool:
        """
        Checks whether one peer is currently retunneling.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            bool: True if the peer is marked as retunneling.
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return False
        return identity in self._retunneling_onions

    def is_live_transport_available(self, alias: Optional[str]) -> bool:
        """
        Checks whether one peer currently has live transport available for sends.

        Args:
            alias (Optional[str]): The peer alias.

        Returns:
            bool: True if the peer is connected and not currently retunneling.
        """
        return self.is_connected(alias) and not self.is_retunneling(alias)

    def remember_peer(self, alias: Optional[str], onion: Optional[str]) -> None:
        """
        Stores the current alias binding for one peer onion.

        Args:
            alias (Optional[str]): The current peer alias.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        if not alias or not onion:
            return

        clean_identity: str = clean_onion(onion)
        previous_alias: Optional[str] = self._peer_alias_by_onion.get(clean_identity)
        if previous_alias and previous_alias != alias:
            self._peer_onion_by_alias.pop(previous_alias, None)

        previous_onion: Optional[str] = self._peer_onion_by_alias.get(alias)
        if previous_onion and previous_onion != clean_identity:
            self._peer_alias_by_onion.pop(previous_onion, None)

        self._peer_alias_by_onion[clean_identity] = alias
        self._peer_onion_by_alias[alias] = clean_identity

    def forget_peer(self, onion: Optional[str]) -> None:
        """
        Removes the current alias binding for one peer onion.

        Args:
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        if not onion:
            return

        clean_identity: str = clean_onion(onion)
        self._retunneling_onions.discard(clean_identity)
        alias: Optional[str] = self._peer_alias_by_onion.pop(clean_identity, None)
        if alias:
            self._peer_onion_by_alias.pop(alias, None)

    def get_peer_alias(
        self,
        onion: Optional[str],
        fallback_alias: Optional[str] = None,
    ) -> Optional[str]:
        """
        Resolves the latest known alias for a peer onion.

        Args:
            onion (Optional[str]): The stable peer onion identity.
            fallback_alias (Optional[str]): Fallback alias when no binding exists.

        Returns:
            Optional[str]: The latest known alias or the fallback.
        """
        if not onion:
            return fallback_alias

        return self._peer_alias_by_onion.get(clean_onion(onion), fallback_alias)

    def get_peer_onion(self, alias: Optional[str]) -> Optional[str]:
        """
        Resolves the stable onion identity for a current alias.

        Args:
            alias (Optional[str]): The current peer alias.

        Returns:
            Optional[str]: The peer onion if known.
        """
        if not alias:
            return None

        return self._peer_onion_by_alias.get(alias)
