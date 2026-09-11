"""Runtime and startup state projection for network IPC."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from metor.core.api import (
    ChatStartupStateEvent,
    ConnectionOrigin,
    ContactEntry,
    DropConversationSummaryEntry,
    EventType,
    IpcEvent,
    JsonValue,
    LiveContextEntry,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    RuntimeSnapshotEvent,
    TransportStateEvent,
    UnreadInboxSummaryEntry,
    create_event,
)
from metor.core.daemon.managed.models import SessionState, TunnelState
from metor.core.daemon.managed.network.state import PendingConnectionSnapshot
from metor.data import SettingKey
from metor.utils import Constants

if TYPE_CHECKING:
    from metor.core.tor import TorManager
    from metor.core.daemon.managed.network import NetworkManager
    from metor.data import ContactManager, MessageManager
    from metor.data.profile import Config


class RuntimeSnapshotProjectionMixin:
    """Builds race-validated aggregate and transport state projections."""

    _tm: 'TorManager'
    _cm: 'ContactManager'
    _mm: 'MessageManager'
    _network: 'NetworkManager'
    _config: 'Config'
    _current_revision: Callable[[], int]

    @staticmethod
    def _format_pending_expiry(expires_at: Optional[float]) -> Optional[str]:
        """
        Converts one pending expiry timestamp to ISO UTC text for IPC transport.

        Args:
            expires_at (Optional[float]): The UNIX expiry timestamp.

        Returns:
            Optional[str]: The ISO UTC timestamp, if available.
        """
        if expires_at is None:
            return None

        return datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    def _build_pending_startup_entries(self) -> List[PendingConnectionEntry]:
        """
        Builds typed retained pending-request entries for chat startup rendering.

        Args:
            None

        Returns:
            List[PendingConnectionEntry]: Pending startup entries.
        """
        entries: List[PendingConnectionEntry] = []
        snapshot: PendingConnectionSnapshot
        for snapshot in self._network.get_pending_connection_snapshots():
            alias: Optional[str] = self._cm.ensure_alias_for_onion(snapshot.onion)
            if alias is None:
                continue

            entries.append(
                PendingConnectionEntry(
                    alias=alias,
                    onion=snapshot.onion,
                    origin=(snapshot.origin or ConnectionOrigin.INCOMING),
                    reason=PendingConnectionReasonCode(
                        snapshot.reason.value
                        if snapshot.reason is not None
                        else PendingConnectionReasonCode.USER_ACCEPT.value
                    ),
                    expires_at=self._format_pending_expiry(snapshot.expires_at),
                )
            )

        return entries

    def _build_unread_startup_entries(self) -> List[UnreadInboxSummaryEntry]:
        """
        Builds typed unread-summary entries for chat startup rendering.

        Args:
            None

        Returns:
            List[UnreadInboxSummaryEntry]: Unread startup entries.
        """
        entries: List[UnreadInboxSummaryEntry] = []
        for summary in self._mm.get_unread_inbox_summaries():
            alias: Optional[str] = self._cm.ensure_alias_for_onion(
                summary.contact_onion
            )
            if alias is None:
                continue

            entries.append(
                UnreadInboxSummaryEntry(
                    alias=alias,
                    onion=summary.contact_onion,
                    total_unread=summary.total_unread,
                    drop_unread=summary.drop_unread,
                    live_unread=summary.live_unread,
                )
            )

        return entries

    def _build_chat_startup_state(self) -> ChatStartupStateEvent:
        """
        Builds the typed first-attach chat startup snapshot.

        Args:
            None

        Returns:
            ChatStartupStateEvent: The startup snapshot event.
        """
        return ChatStartupStateEvent(
            active=self._network.get_active_aliases(),
            contacts=self._cm.get_all_contacts(),
            pending=self._build_pending_startup_entries(),
            unread=self._build_unread_startup_entries(),
        )

    def _build_runtime_snapshot(self) -> IpcEvent:
        """Builds one authoritative content-free aggregate runtime projection.

        Args:
            None

        Returns:
            IpcEvent: Snapshot, or a typed retryable unavailable result.
        """
        for _ in range(Constants.RUNTIME_SNAPSHOT_MAX_RETRIES):
            revision = self._current_revision()
            state_token = self._network.get_snapshot_token()
            snapshot = self._compose_runtime_snapshot()
            if (
                self._current_revision() == revision
                and self._network.get_snapshot_token() == state_token
            ):
                snapshot.revision = revision
                return snapshot
        return create_event(
            EventType.RUNTIME_SNAPSHOT_UNAVAILABLE,
            {'retryable': True},
        )

    def _compose_runtime_snapshot(self) -> RuntimeSnapshotEvent:
        """Reads one candidate aggregate projection for revision validation."""
        contact_snapshot = self._cm.get_contacts_data()
        saved_onions = {contact.onion for contact in contact_snapshot.saved}
        contacts = [
            ContactEntry(contact.alias, contact.onion, True)
            for contact in contact_snapshot.saved
        ] + [
            ContactEntry(contact.alias, contact.onion, False)
            for contact in contact_snapshot.discovered
        ]
        conversations = [
            DropConversationSummaryEntry(
                alias=self._cm.ensure_alias_for_onion(onion) or onion,
                onion=onion,
                unread_count=unread_count,
            )
            for onion, unread_count in self._mm.get_drop_conversation_summaries()
        ]
        unread_by_onion = {
            summary.contact_onion: summary
            for summary in self._mm.get_unread_inbox_summaries()
        }
        relevant_onions = set(self._network.get_relevant_live_onions())
        relevant_onions.update(
            summary.contact_onion
            for summary in unread_by_onion.values()
            if summary.live_unread > 0
        )
        relevant_onions.update(
            record.peer_onion for record in self._mm.get_pending_live_outbox()
        )
        live_contexts = []
        for onion in sorted(relevant_onions):
            summary = unread_by_onion.get(onion)
            disconnect_reason = self._network.get_last_disconnect_reason(onion)
            disconnect_actor = self._network.get_last_disconnect_actor(onion)
            session_state = self._network.get_live_state(onion)
            live_contexts.append(
                LiveContextEntry(
                    alias=self._cm.ensure_alias_for_onion(onion) or onion,
                    onion=onion,
                    saved=onion in saved_onions,
                    session_state=session_state.value,
                    unseen_count=summary.live_unread if summary else 0,
                    pending_outbound_count=len(self._mm.get_pending_live_outbox(onion)),
                    recovery_eligible=session_state
                    in {
                        SessionState.CONNECTED,
                        SessionState.CONNECTING,
                        SessionState.PENDING,
                        SessionState.RETUNNELING,
                        SessionState.RECONNECT_GRACE,
                        SessionState.RECONNECT_SCHEDULED,
                    },
                    disconnect_actor=disconnect_actor,
                    disconnect_reason=disconnect_reason,
                )
            )
        return RuntimeSnapshotEvent(
            profile=self._config._paths.profile_name,
            onion=self._tm.onion or '',
            contacts=contacts,
            conversations=conversations,
            live_contexts=live_contexts,
            pending=self._build_pending_startup_entries(),
            settings_version=hashlib.sha256(
                repr(self._config.get_setting_snapshots()).encode('utf-8')
            ).hexdigest(),
        )

    def _build_transport_state_events(
        self,
        peer: Optional[str],
    ) -> List[TransportStateEvent]:
        """
        Builds typed transport-state events for one requested peer or all active sessions.

        Args:
            peer (Optional[str]): The requested alias or onion, or None for every
                active session.

        Returns:
            List[TransportStateEvent]: One event per resolved peer; a single
                empty event when no peer was resolved or no session is active.
        """
        if peer:
            resolved: Optional[Tuple[str, str]] = (
                self._cm.resolve_target_for_interaction(peer)
            )
            if not resolved:
                return [
                    TransportStateEvent(
                        peer=peer,
                        session_state=SessionState.DISCONNECTED.value,
                    )
                ]

            alias, onion = resolved
            return [self._build_transport_state_event(alias, onion)]

        active_onions: List[str] = self._network.get_active_onions()
        if not active_onions:
            return [
                TransportStateEvent(
                    peer='',
                    session_state=SessionState.DISCONNECTED.value,
                )
            ]

        events: List[TransportStateEvent] = []
        for onion in active_onions:
            alias = self._cm.ensure_alias_for_onion(onion) or onion
            events.append(self._build_transport_state_event(alias, onion))
        return events

    def _build_transport_state_event(
        self,
        peer: str,
        onion: str,
    ) -> TransportStateEvent:
        """
        Builds one typed transport-state event for a resolved peer.

        Args:
            peer (str): The display alias for the peer.
            onion (str): The strict peer onion identity.

        Returns:
            TransportStateEvent: The typed transport-state DTO.
        """
        live_state: SessionState = self._network.get_live_state(onion)

        drop_tunnel_state: Optional[TunnelState] = self._network.get_drop_tunnel_state(
            onion
        )
        drop_tunnel: Optional[Dict[str, JsonValue]] = None
        if drop_tunnel_state is not None:
            drop_tunnel = {
                'cached': True,
                'opened_at': datetime.fromtimestamp(
                    drop_tunnel_state.opened_at,
                    tz=timezone.utc,
                ).isoformat(),
                'last_used_at': datetime.fromtimestamp(
                    drop_tunnel_state.last_used_at,
                    tz=timezone.utc,
                ).isoformat(),
                'idle_timeout': self._config.get_float(
                    SettingKey.DROP_TUNNEL_IDLE_TIMEOUT
                ),
            }

        auto_accept: bool = (
            peer in self._cm.get_all_contacts()
            and self._config.get_bool(SettingKey.AUTO_ACCEPT_CONTACTS)
        )

        return TransportStateEvent(
            peer=peer,
            session_state=live_state.value,
            onion=onion,
            drop_tunnel=drop_tunnel,
            focus_count=self._network.get_focus_count(onion),
            pending_live_count=len(self._mm.get_pending_live_outbox(onion)),
            auto_accept=auto_accept,
        )
