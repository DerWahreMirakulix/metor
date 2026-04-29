"""History persistence and projection service backed by the centralized SQL ledger."""

from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Dict, List, Optional

from metor.utils import Constants, clean_onion

from metor.data.history.codes import (
    HistoryActor,
    HistoryEvent,
    HistoryFamily,
    HistoryReasonCode,
    HistoryTrigger,
)
from metor.data.history.models import (
    HistoryClearOperationType,
    HistoryClearResult,
    HistoryLedgerEntry,
    HistorySummaryEntry,
)
from metor.data.history.projector import HistoryProjector
from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey
from metor.data.sql import HistoryRepository, SqlManager


class HistoryManager:
    """Manages raw history persistence and projected summary retrieval."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the history manager and its underlying SQL connection.

        Args:
            pm (ProfileManager): The active profile manager.
            password (Optional[str]): Optional SQLCipher password.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = self._pm.paths.get_db_file()
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)
        self._history: HistoryRepository = self._sql.history
        self._active_live_flow_ids: Dict[str, str] = {}

    def _create_flow_id(self) -> str:
        """
        Creates one opaque correlation identifier for history rows.

        Args:
            None

        Returns:
            str: The generated flow identifier.
        """
        return secrets.token_hex(Constants.UUID_MSG_BYTES)

    def _resolve_live_flow_id(
        self,
        peer_onion: Optional[str],
        event_code: HistoryEvent,
        explicit_flow_id: Optional[str],
    ) -> str:
        """
        Resolves one best-effort live-flow identifier for a persisted row.

        Args:
            peer_onion (Optional[str]): The peer onion identity.
            event_code (HistoryEvent): The raw event code being persisted.
            explicit_flow_id (Optional[str]): An explicitly supplied flow identifier.

        Returns:
            str: The resolved live-flow identifier.
        """
        if explicit_flow_id:
            if peer_onion:
                self._active_live_flow_ids[peer_onion] = explicit_flow_id
            return explicit_flow_id

        key: str = peer_onion or '__global__'
        if event_code in {
            HistoryEvent.REQUESTED,
            HistoryEvent.RETUNNEL_INITIATED,
        }:
            new_flow_id: str = self._create_flow_id()
            self._active_live_flow_ids[key] = new_flow_id
            return new_flow_id

        flow_id: Optional[str] = self._active_live_flow_ids.get(key)
        if flow_id is None:
            flow_id = self._create_flow_id()
            self._active_live_flow_ids[key] = flow_id

        if event_code in {
            HistoryEvent.REJECTED,
            HistoryEvent.DISCONNECTED,
            HistoryEvent.CONNECTION_LOST,
            HistoryEvent.RETUNNEL_SUCCEEDED,
        }:
            self._active_live_flow_ids.pop(key, None)

        assert flow_id is not None
        return flow_id

    def _resolve_flow_id(
        self,
        event_code: HistoryEvent,
        peer_onion: Optional[str],
        explicit_flow_id: Optional[str],
    ) -> str:
        """
        Resolves one persisted flow identifier for a raw history row.

        Args:
            event_code (HistoryEvent): The raw event code being persisted.
            peer_onion (Optional[str]): The peer onion identity.
            explicit_flow_id (Optional[str]): An explicitly supplied flow identifier.

        Returns:
            str: The flow identifier for the row.
        """
        if event_code.family is HistoryFamily.DROP:
            return explicit_flow_id or self._create_flow_id()
        return self._resolve_live_flow_id(peer_onion, event_code, explicit_flow_id)

    def log_event(
        self,
        event_code: HistoryEvent,
        peer_onion: Optional[str],
        *,
        actor: HistoryActor,
        detail_text: str = '',
        trigger: Optional[str | HistoryTrigger] = None,
        detail_code: Optional[HistoryReasonCode] = None,
        flow_id: Optional[str] = None,
    ) -> None:
        """
        Persists one raw transport history row when retention is enabled.

        Args:
            event_code (HistoryEvent): The raw event code to persist.
            peer_onion (Optional[str]): The associated peer onion identity.
            actor (HistoryActor): The direct actor causing the transition.
            detail_text (str): Optional diagnostic detail.
            trigger (Optional[str | HistoryTrigger]): Optional machine-readable trigger.
            detail_code (Optional[HistoryReasonCode]): Optional machine-readable detail code.
            flow_id (Optional[str]): Optional externally supplied flow identifier.

        Returns:
            None
        """
        if event_code.family is HistoryFamily.DROP:
            if not self._pm.config.get_bool(SettingKey.RECORD_DROP_HISTORY):
                return
        else:
            if not self._pm.config.get_bool(SettingKey.RECORD_LIVE_HISTORY):
                return

        normalized_onion: Optional[str] = (
            clean_onion(peer_onion) if peer_onion else None
        )
        trigger_value: Optional[str] = (
            trigger.value if isinstance(trigger, HistoryTrigger) else trigger
        )
        timestamp: str = datetime.now(timezone.utc).isoformat()
        resolved_flow_id: str = self._resolve_flow_id(
            event_code,
            normalized_onion,
            flow_id,
        )
        self._history.log_entry(
            timestamp=timestamp,
            family=event_code.family,
            event_code=event_code,
            peer_onion=normalized_onion,
            actor=actor,
            trigger=trigger_value,
            detail_code=detail_code,
            detail_text=detail_text,
            flow_id=resolved_flow_id,
        )

    def get_raw_history(
        self,
        filter_onion: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[HistoryLedgerEntry]:
        """
        Retrieves raw transport history ledger rows.

        Args:
            filter_onion (Optional[str]): Optional peer onion filter.
            limit (Optional[int]): Optional result limit.

        Returns:
            List[HistoryLedgerEntry]: Raw history rows ordered newest-first.
        """
        actual_limit: int = (
            limit
            if limit is not None
            else self._pm.config.get_int(SettingKey.HISTORY_LIMIT)
        )
        return self._history.get_entries(filter_onion, actual_limit)

    def get_history(
        self,
        filter_onion: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[HistorySummaryEntry]:
        """
        Retrieves projected user-facing summary history rows.

        Args:
            filter_onion (Optional[str]): Optional peer onion filter.
            limit (Optional[int]): Optional projected result limit.

        Returns:
            List[HistorySummaryEntry]: Projected summary rows ordered newest-first.
        """
        actual_limit: int = (
            limit
            if limit is not None
            else self._pm.config.get_int(SettingKey.HISTORY_LIMIT)
        )
        raw_entries: List[HistoryLedgerEntry] = self._history.get_entries(
            filter_onion,
            None,
        )
        return HistoryProjector.project(raw_entries)[:actual_limit]

    def clear_history(
        self,
        filter_onion: Optional[str] = None,
    ) -> HistoryClearResult:
        """
        Clears persisted history rows.

        Args:
            filter_onion (Optional[str]): Optional peer onion filter.

        Returns:
            HistoryClearResult: The typed clear-history result.
        """
        try:
            self._history.clear(filter_onion)
            if filter_onion:
                return HistoryClearResult(
                    True,
                    HistoryClearOperationType.TARGET_CLEARED,
                    target_onion=filter_onion,
                )

            return HistoryClearResult(
                True,
                HistoryClearOperationType.ALL_CLEARED,
                profile=self._pm.profile_name,
            )
        except Exception:
            return HistoryClearResult(
                False,
                HistoryClearOperationType.CLEAR_FAILED,
            )
