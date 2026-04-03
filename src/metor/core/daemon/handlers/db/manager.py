"""Thin routing facade for the modular database command handlers."""

from typing import Callable, List

from metor.core.api import (
    AddContactCommand,
    ClearContactsCommand,
    ClearHistoryCommand,
    ClearMessagesCommand,
    ClearProfileDbCommand,
    EventType,
    GetContactsListCommand,
    GetHistoryCommand,
    GetInboxCommand,
    GetMessagesCommand,
    GetRawHistoryCommand,
    IpcCommand,
    IpcEvent,
    MarkReadCommand,
    RemoveContactCommand,
    RenameContactCommand,
    create_event,
)
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.profile import ProfileManager

# Local Package Imports
from metor.core.daemon.handlers.db.contacts import DatabaseCommandContactsMixin
from metor.core.daemon.handlers.db.history import DatabaseCommandHistoryMixin
from metor.core.daemon.handlers.db.maintenance import (
    DatabaseCommandMaintenanceMixin,
)
from metor.core.daemon.handlers.db.messages import DatabaseCommandMessagesMixin


class DatabaseCommandHandler(
    DatabaseCommandContactsMixin,
    DatabaseCommandHistoryMixin,
    DatabaseCommandMessagesMixin,
    DatabaseCommandMaintenanceMixin,
):
    """Routes database commands to focused contact, history, message, and maintenance handlers."""

    def __init__(
        self,
        pm: ProfileManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        get_active_onions: Callable[[], List[str]],
        broadcast: Callable[[IpcEvent], None],
    ) -> None:
        """
        Initializes the DatabaseCommandHandler.

        Args:
            pm (ProfileManager): Profile configuration.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            get_active_onions (Callable[[], List[str]]): Hook to retrieve currently connected onions.
            broadcast (Callable[[IpcEvent], None]): Hook to broadcast side-effect events to all clients.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._get_active_onions: Callable[[], List[str]] = get_active_onions
        self._broadcast: Callable[[IpcEvent], None] = broadcast

    def handle(self, cmd: IpcCommand) -> IpcEvent:
        """
        Routes the database command to the respective manager and formats the strict DTO response.

        Args:
            cmd (IpcCommand): The database-related IPC command.

        Returns:
            IpcEvent: The strictly typed response event DTO.
        """
        if isinstance(cmd, GetContactsListCommand):
            return self._handle_get_contacts(cmd)

        if isinstance(cmd, AddContactCommand):
            return self._handle_add_contact(cmd)

        if isinstance(cmd, RemoveContactCommand):
            return self._handle_remove_contact(cmd)

        if isinstance(cmd, RenameContactCommand):
            return self._handle_rename_contact(cmd)

        if isinstance(cmd, ClearContactsCommand):
            return self._handle_clear_contacts(cmd)

        if isinstance(cmd, ClearProfileDbCommand):
            return self._handle_clear_profile_db(cmd)

        if isinstance(cmd, (GetHistoryCommand, GetRawHistoryCommand)):
            return self._handle_get_history(cmd)

        if isinstance(cmd, ClearHistoryCommand):
            return self._handle_clear_history(cmd)

        if isinstance(cmd, GetMessagesCommand):
            return self._handle_get_messages(cmd)

        if isinstance(cmd, ClearMessagesCommand):
            return self._handle_clear_messages(cmd)

        if isinstance(cmd, GetInboxCommand):
            return self._handle_get_inbox(cmd)

        if isinstance(cmd, MarkReadCommand):
            return self._handle_mark_read(cmd)

        return create_event(EventType.UNKNOWN_COMMAND)
