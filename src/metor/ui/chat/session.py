"""
Module managing the active connection states and focus targets for the UI.
"""

from typing import Dict, List, Optional, Set

from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.models import BufferedOutgoingMessage, ChatTransportState


ALIAS_IDENTITY_PREFIX: str = 'alias:'


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
        self._transport_state_by_peer: Dict[str, ChatTransportState] = {}
        self._buffered_outgoing_by_peer: Dict[str, List[BufferedOutgoingMessage]] = {}

        self.header_active: List[str] = []
        self.header_pending: List[str] = []
        self.header_contacts: List[str] = []

        self.my_onion: str = 'unknown'

    @staticmethod
    def _build_alias_identity(alias: str) -> str:
        """
        Builds one local fallback identity for alias-only peers.

        Args:
            alias (str): The peer alias.

        Returns:
            str: The alias-backed fallback identity.
        """
        return f'{ALIAS_IDENTITY_PREFIX}{alias}'

    def _move_peer_state(self, source_identity: str, target_identity: str) -> None:
        """
        Migrates buffered UI state from an alias key to the canonical onion key.

        Args:
            source_identity (str): The temporary source identity.
            target_identity (str): The final canonical identity.

        Returns:
            None
        """
        if source_identity == target_identity:
            return

        transport_state: Optional[ChatTransportState] = (
            self._transport_state_by_peer.pop(source_identity, None)
        )
        if (
            transport_state is not None
            and target_identity not in self._transport_state_by_peer
        ):
            self._transport_state_by_peer[target_identity] = transport_state

        buffered_messages: List[BufferedOutgoingMessage] = (
            self._buffered_outgoing_by_peer.pop(source_identity, [])
        )
        if buffered_messages:
            self._buffered_outgoing_by_peer.setdefault(target_identity, []).extend(
                buffered_messages
            )

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
            return self._build_alias_identity(alias)
        return None

    def set_transport_state(
        self,
        state: ChatTransportState,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """
        Stores the current UI transport state for one peer.

        Args:
            state (ChatTransportState): The prompt/send transport state.
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            None
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return
        self._transport_state_by_peer[identity] = state

    def clear_transport_state(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """
        Clears any explicit UI transport state override for one peer.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            None
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return
        self._transport_state_by_peer.pop(identity, None)

    def get_transport_state(self, alias: Optional[str]) -> ChatTransportState:
        """
        Resolves the current prompt/send transport state for one alias.

        Args:
            alias (Optional[str]): The peer alias.

        Returns:
            ChatTransportState: The effective UI transport state.
        """
        if not alias:
            return ChatTransportState.DROP

        identity: Optional[str] = self._resolve_peer_identity(alias)
        if identity is not None:
            explicit_state: Optional[ChatTransportState] = (
                self._transport_state_by_peer.get(identity)
            )
            if explicit_state is not None:
                return explicit_state

        if self.is_connected(alias):
            return ChatTransportState.LIVE
        return ChatTransportState.DROP

    def should_buffer_outgoing(self, alias: Optional[str]) -> bool:
        """
        Checks whether new outgoing messages should stay local for now.

        Args:
            alias (Optional[str]): The peer alias.

        Returns:
            bool: True if the transport is switching or reconnecting.
        """
        return self.get_transport_state(alias) in (
            ChatTransportState.SWITCHING,
            ChatTransportState.RECONNECTING,
        )

    def buffer_outgoing_message(
        self,
        alias: str,
        text: str,
        msg_id: str,
        onion: Optional[str] = None,
    ) -> None:
        """
        Buffers one outgoing self-message until live transport is usable again.

        Args:
            alias (str): The current peer alias.
            text (str): The outgoing message text.
            msg_id (str): The stable logical message identifier.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return

        self._buffered_outgoing_by_peer.setdefault(identity, []).append(
            BufferedOutgoingMessage(
                alias=alias,
                text=text,
                msg_id=msg_id,
                onion=onion,
            )
        )

    def pop_buffered_outgoing_messages(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> List[BufferedOutgoingMessage]:
        """
        Returns and clears all buffered outgoing messages for one peer.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            List[BufferedOutgoingMessage]: The buffered outgoing messages.
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return []
        return self._buffered_outgoing_by_peer.pop(identity, [])

    def has_buffered_outgoing_messages(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> bool:
        """
        Checks whether buffered outgoing self-messages exist for one peer.

        Args:
            alias (Optional[str]): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            bool: True if at least one outgoing message is buffered.
        """
        identity: Optional[str] = self._resolve_peer_identity(alias, onion)
        if identity is None:
            return False
        return bool(self._buffered_outgoing_by_peer.get(identity))

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
        self._transport_state_by_peer[identity] = ChatTransportState.SWITCHING

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
        if self._transport_state_by_peer.get(identity) is ChatTransportState.SWITCHING:
            self._transport_state_by_peer.pop(identity, None)

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
        return self.get_transport_state(alias) is ChatTransportState.LIVE

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
        self._move_peer_state(self._build_alias_identity(alias), clean_identity)

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
        self._transport_state_by_peer.pop(clean_identity, None)
        self._buffered_outgoing_by_peer.pop(clean_identity, None)
        alias: Optional[str] = self._peer_alias_by_onion.pop(clean_identity, None)
        if alias:
            self._peer_onion_by_alias.pop(alias, None)
            alias_identity: str = self._build_alias_identity(alias)
            self._transport_state_by_peer.pop(alias_identity, None)
            self._buffered_outgoing_by_peer.pop(alias_identity, None)

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
