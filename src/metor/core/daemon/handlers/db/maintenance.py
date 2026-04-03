"""Maintenance-oriented database command handling."""

from metor.core.api import ClearProfileDbCommand, EventType, IpcEvent, create_event

# Local Package Imports
from metor.core.daemon.handlers.db.support import DatabaseCommandHandlerSupportMixin


class DatabaseCommandMaintenanceMixin(DatabaseCommandHandlerSupportMixin):
    """Handles cross-domain database maintenance commands."""

    def _handle_clear_profile_db(self, _: ClearProfileDbCommand) -> IpcEvent:
        """
        Clears the full profile database across contacts, history, and messages.

        Args:
            _ (ClearProfileDbCommand): The incoming clear-profile-db command.

        Returns:
            IpcEvent: The resulting database maintenance event DTO.
        """
        active_onions = self._get_active_onions()
        history_result = self._hm.clear_history()
        messages_result = self._mm.clear_messages()
        contacts_result = self._cm.clear_contacts(active_onions)

        if contacts_result.success:
            self._emit_contact_side_effects(
                contacts_result.renames,
                contacts_result.removals,
            )

        success: bool = (
            contacts_result.success
            and history_result.success
            and messages_result.success
        )
        if success:
            preserved_peers_raw: str | int = contacts_result.params.get(
                'preserved_peers',
                0,
            )
            return create_event(
                EventType.DB_CLEARED,
                {
                    'profile': self._pm.profile_name,
                    'preserved_peers': int(preserved_peers_raw),
                },
            )
        return create_event(EventType.DB_CLEAR_FAILED)
