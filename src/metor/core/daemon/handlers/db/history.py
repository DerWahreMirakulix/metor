"""History-specific database command handling."""

from typing import Dict, Optional, Tuple

from metor.core.api import (
    ClearHistoryCommand,
    EventType,
    GetHistoryCommand,
    GetRawHistoryCommand,
    HistoryDataEvent,
    HistoryRawDataEvent,
    IpcEvent,
    create_event,
)
from metor.data.history import HistoryClearOperationType, HistoryClearResult

# Local Package Imports
from metor.core.daemon.handlers.db.support import DatabaseCommandHandlerSupportMixin


HISTORY_CLEAR_EVENT_TYPES: dict[HistoryClearOperationType, EventType] = {
    HistoryClearOperationType.ALL_CLEARED: EventType.HISTORY_CLEARED_ALL,
    HistoryClearOperationType.CLEAR_FAILED: EventType.HISTORY_CLEAR_FAILED,
    HistoryClearOperationType.TARGET_CLEARED: EventType.HISTORY_CLEARED,
}


class DatabaseCommandHistoryMixin(DatabaseCommandHandlerSupportMixin):
    """Handles persisted history queries and clear operations."""

    def _handle_get_history(
        self,
        cmd: GetHistoryCommand | GetRawHistoryCommand,
    ) -> IpcEvent:
        """
        Returns projected or raw transport history for one optional peer target.

        Args:
            cmd (GetHistoryCommand | GetRawHistoryCommand): The incoming history command.

        Returns:
            IpcEvent: The resulting history data event DTO.
        """
        alias: Optional[str] = None
        onion: Optional[str] = None

        if cmd.target:
            resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(cmd.target)
            if not resolved:
                return create_event(EventType.INVALID_TARGET, {'target': cmd.target})
            alias, onion = resolved

        entries = (
            self._hm.get_raw_history(onion, cmd.limit)
            if isinstance(cmd, GetRawHistoryCommand)
            else self._hm.get_history(onion, cmd.limit)
        )
        history_entries = [self._build_history_entry(entry) for entry in entries]
        history_event_cls = (
            HistoryRawDataEvent
            if isinstance(cmd, GetRawHistoryCommand)
            else HistoryDataEvent
        )
        return history_event_cls(
            entries=history_entries,
            profile=self._pm.profile_name,
            alias=alias,
            peer_onion=onion,
        )

    def _handle_clear_history(self, cmd: ClearHistoryCommand) -> IpcEvent:
        """
        Clears raw history rows and cleans up orphaned discovered peers.

        Args:
            cmd (ClearHistoryCommand): The incoming clear-history command.

        Returns:
            IpcEvent: The resulting IPC event DTO.
        """
        active_onions = self._get_active_onions()
        alias: Optional[str] = None
        onion: Optional[str] = None

        if cmd.target:
            resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(cmd.target)
            if not resolved:
                return create_event(EventType.PEER_NOT_FOUND, {'target': cmd.target})
            alias, onion = resolved

        result: HistoryClearResult = self._hm.clear_history(onion)
        params: Dict[str, str] = {}
        if result.operation_type is HistoryClearOperationType.TARGET_CLEARED and alias:
            params = {'alias': alias}
            if onion:
                params['onion'] = onion
        elif result.operation_type is HistoryClearOperationType.ALL_CLEARED:
            params = {'profile': result.profile or self._pm.profile_name}

        self._emit_orphan_cleanup(self._cm.cleanup_orphans(active_onions))
        return create_event(HISTORY_CLEAR_EVENT_TYPES[result.operation_type], params)
