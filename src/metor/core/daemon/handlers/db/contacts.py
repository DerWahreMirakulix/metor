"""Contact-specific database command handling."""

from typing import Dict

from metor.core.api import (
    AddContactCommand,
    ClearContactsCommand,
    ContactEntry,
    ContactsDataEvent,
    EventType,
    GetContactsListCommand,
    IpcEvent,
    RemoveContactCommand,
    RenameContactCommand,
    create_event,
)
from metor.data.contact import ContactOperationResult, ContactOperationType

# Local Package Imports
from metor.core.daemon.handlers.db.support import DatabaseCommandHandlerSupportMixin


CONTACT_EVENT_TYPES: dict[ContactOperationType, EventType] = {
    ContactOperationType.ALIAS_IN_USE: EventType.ALIAS_IN_USE,
    ContactOperationType.ALIAS_NOT_FOUND: EventType.ALIAS_NOT_FOUND,
    ContactOperationType.ALIAS_RENAMED: EventType.ALIAS_RENAMED,
    ContactOperationType.ALIAS_SAME: EventType.ALIAS_SAME,
    ContactOperationType.CONTACT_ADDED: EventType.CONTACT_ADDED,
    ContactOperationType.CONTACT_ALREADY_SAVED: EventType.CONTACT_ALREADY_SAVED,
    ContactOperationType.CONTACT_DOWNGRADED: EventType.CONTACT_DOWNGRADED,
    ContactOperationType.CONTACT_REMOVED: EventType.CONTACT_REMOVED,
    ContactOperationType.CONTACT_REMOVED_DOWNGRADED: (
        EventType.CONTACT_REMOVED_DOWNGRADED
    ),
    ContactOperationType.CONTACTS_CLEARED: EventType.CONTACTS_CLEARED,
    ContactOperationType.CONTACTS_CLEAR_FAILED: EventType.CONTACTS_CLEAR_FAILED,
    ContactOperationType.ONION_IN_USE: EventType.ONION_IN_USE,
    ContactOperationType.PEER_ANONYMIZED: EventType.PEER_ANONYMIZED,
    ContactOperationType.PEER_CANT_DELETE_ACTIVE: EventType.PEER_CANT_DELETE_ACTIVE,
    ContactOperationType.PEER_NOT_FOUND: EventType.PEER_NOT_FOUND,
    ContactOperationType.PEER_PROMOTED: EventType.PEER_PROMOTED,
    ContactOperationType.PEER_REMOVED: EventType.PEER_REMOVED,
}


class DatabaseCommandContactsMixin(DatabaseCommandHandlerSupportMixin):
    """Handles address-book and alias database commands."""

    @staticmethod
    def _create_contact_event(result: ContactOperationResult) -> IpcEvent:
        """
        Converts one local contact result into its IPC event DTO.

        Args:
            result (ContactOperationResult): The local contact mutation result.

        Returns:
            IpcEvent: The IPC event DTO.
        """
        return create_event(
            CONTACT_EVENT_TYPES[result.operation_type], dict(result.params)
        )

    def _handle_get_contacts(self, _: GetContactsListCommand) -> IpcEvent:
        """
        Returns the structured saved and discovered contact lists.

        Args:
            _ (GetContactsListCommand): The incoming contacts-list command.

        Returns:
            IpcEvent: The contact list event DTO.
        """
        snapshot = self._cm.get_contacts_data()
        return ContactsDataEvent(
            saved=[
                ContactEntry(alias=entry.alias, onion=entry.onion)
                for entry in snapshot.saved
            ],
            discovered=[
                ContactEntry(alias=entry.alias, onion=entry.onion)
                for entry in snapshot.discovered
            ],
            profile=snapshot.profile,
        )

    def _handle_add_contact(self, cmd: AddContactCommand) -> IpcEvent:
        """
        Adds a saved contact or promotes a discovered peer.

        Args:
            cmd (AddContactCommand): The incoming add-contact command.

        Returns:
            IpcEvent: The resulting IPC event DTO.
        """
        result: ContactOperationResult = (
            self._cm.add_contact(cmd.alias, cmd.onion)
            if cmd.onion
            else self._cm.promote_discovered_peer(cmd.alias)
        )
        params: Dict[str, str] = dict(result.params)
        if not result.success and 'alias' not in params and cmd.alias:
            params['alias'] = cmd.alias
        return create_event(CONTACT_EVENT_TYPES[result.operation_type], params)

    def _handle_remove_contact(self, cmd: RemoveContactCommand) -> IpcEvent:
        """
        Removes or demotes one contact and broadcasts dependent UI side effects.

        Args:
            cmd (RemoveContactCommand): The incoming remove-contact command.

        Returns:
            IpcEvent: The resulting IPC event DTO.
        """
        active_onions = self._get_active_onions()
        result: ContactOperationResult = self._cm.remove_contact(
            cmd.alias,
            active_onions,
        )
        if result.success:
            self._emit_contact_side_effects(result.renames, result.removals)

        self._emit_orphan_cleanup(self._cm.cleanup_orphans(active_onions))
        params: Dict[str, str] = dict(result.params)
        if 'alias' not in params and cmd.alias:
            params['alias'] = cmd.alias
        return create_event(CONTACT_EVENT_TYPES[result.operation_type], params)

    def _handle_rename_contact(self, cmd: RenameContactCommand) -> IpcEvent:
        """
        Renames one contact alias and synchronizes active UIs.

        Args:
            cmd (RenameContactCommand): The incoming rename-contact command.

        Returns:
            IpcEvent: The resulting IPC event DTO.
        """
        result: ContactOperationResult = self._cm.rename_contact(
            cmd.old_alias,
            cmd.new_alias,
        )
        if result.success:
            self._broadcast(
                create_event(
                    EventType.RENAME_SUCCESS,
                    {
                        'old_alias': cmd.old_alias,
                        'new_alias': cmd.new_alias,
                        'onion': str(result.params.get('onion') or '') or None,
                    },
                )
            )
        return self._create_contact_event(result)

    def _handle_clear_contacts(self, _: ClearContactsCommand) -> IpcEvent:
        """
        Clears saved contacts and broadcasts rename/removal side effects.

        Args:
            _ (ClearContactsCommand): The incoming clear-contacts command.

        Returns:
            IpcEvent: The resulting IPC event DTO.
        """
        active_onions = self._get_active_onions()
        result: ContactOperationResult = self._cm.clear_contacts(active_onions)
        if result.success:
            self._emit_contact_side_effects(result.renames, result.removals)

        self._emit_orphan_cleanup(self._cm.cleanup_orphans(active_onions))
        return self._create_contact_event(result)
