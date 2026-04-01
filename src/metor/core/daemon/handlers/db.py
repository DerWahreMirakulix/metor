"""
Module defining the DatabaseCommandHandler.
Encapsulates all stateless CRUD operations for Contacts, History, and Messages.
Used by both the active Daemon engine and the HeadlessDaemon. Emits strict DTOs.
"""

from typing import Dict, List, Tuple, Callable, Optional, Union

from metor.core.api import (
    EventType,
    IpcCommand,
    IpcEvent,
    GetContactsListCommand,
    AddContactCommand,
    RemoveContactCommand,
    RenameContactCommand,
    ClearContactsCommand,
    ClearProfileDbCommand,
    GetHistoryCommand,
    ClearHistoryCommand,
    GetMessagesCommand,
    ClearMessagesCommand,
    GetInboxCommand,
    MarkReadCommand,
    RenameSuccessEvent,
    ContactRemovedEvent,
    ContactEntry,
    HistoryEntry,
    MessageEntry,
    UnreadMessageEntry,
    ContactsDataEvent,
    HistoryDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    create_event,
)
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.profile import ProfileManager


class DatabaseCommandHandler:
    """Processes stateless database commands and generates strict DTO IPC responses."""

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
        resolved: Optional[Tuple[str, str]]
        alias: Optional[str]
        onion: Optional[str]
        active_onions: List[str]

        if isinstance(cmd, GetContactsListCommand):
            data: Dict[str, Union[str, List[Tuple[str, str]]]] = (
                self._cm.get_contacts_data()
            )

            saved_raw = data.get('saved', [])
            saved_list: List[Tuple[str, str]] = (
                saved_raw if isinstance(saved_raw, list) else []
            )
            saved_entries: List[ContactEntry] = [
                ContactEntry(alias=str(r[0]), onion=str(r[1])) for r in saved_list
            ]

            discovered_raw = data.get('discovered', [])
            discovered_list: List[Tuple[str, str]] = (
                discovered_raw if isinstance(discovered_raw, list) else []
            )
            discovered_entries: List[ContactEntry] = [
                ContactEntry(alias=str(r[0]), onion=str(r[1])) for r in discovered_list
            ]

            return ContactsDataEvent(
                saved=saved_entries,
                discovered=discovered_entries,
                profile=str(data.get('profile', '')),
            )

        if isinstance(cmd, AddContactCommand):
            if cmd.onion:
                add_success, add_event_type, add_params = self._cm.add_contact(
                    cmd.alias, cmd.onion
                )
            else:
                add_success, add_event_type, add_params = (
                    self._cm.promote_discovered_peer(cmd.alias)
                )

            alias_res: str = str(add_params.get('alias', cmd.alias))
            if not add_success and 'alias' not in add_params and alias_res:
                add_params['alias'] = alias_res
            return create_event(add_event_type, add_params)

        if isinstance(cmd, RemoveContactCommand):
            active_onions = self._get_active_onions()
            rm_success, rm_event_type, rm_params, rm_renames, rm_removed = (
                self._cm.remove_contact(cmd.alias, active_onions)
            )
            if rm_success:
                for old, new, was_saved in rm_renames:
                    self._broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in rm_removed:
                    self._broadcast(
                        ContactRemovedEvent(alias=a, profile=self._pm.profile_name)
                    )

            self._cm.cleanup_orphans(active_onions)
            if 'alias' not in rm_params and cmd.alias:
                rm_params['alias'] = cmd.alias
            return create_event(rm_event_type, rm_params)

        if isinstance(cmd, RenameContactCommand):
            rn_success, rn_event_type, rn_params = self._cm.rename_contact(
                cmd.old_alias, cmd.new_alias
            )
            if rn_success:
                self._broadcast(
                    RenameSuccessEvent(old_alias=cmd.old_alias, new_alias=cmd.new_alias)
                )
            return create_event(rn_event_type, rn_params)

        if isinstance(cmd, ClearContactsCommand):
            active_onions = self._get_active_onions()
            clr_success, clr_event_type, clr_params, clr_renames, clr_removed = (
                self._cm.clear_contacts(active_onions)
            )
            if clr_success:
                for old, new, was_saved in clr_renames:
                    self._broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in clr_removed:
                    self._broadcast(
                        ContactRemovedEvent(alias=a, profile=self._pm.profile_name)
                    )

            self._cm.cleanup_orphans(active_onions)
            return create_event(clr_event_type, clr_params)

        if isinstance(cmd, ClearProfileDbCommand):
            active_onions = self._get_active_onions()
            success_c, _, _, renames, removed = self._cm.clear_contacts(active_onions)
            success_h, _, _ = self._hm.clear_history()
            success_m, _, _ = self._mm.clear_messages()

            success: bool = success_c and success_h and success_m
            event_type: EventType = (
                EventType.DB_CLEARED if success else EventType.DB_CLEAR_FAILED
            )

            if success_c:
                for old, new, was_saved in renames:
                    self._broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in removed:
                    self._broadcast(
                        ContactRemovedEvent(alias=a, profile=self._pm.profile_name)
                    )

            return create_event(event_type, {'profile': self._pm.profile_name})

        if isinstance(cmd, GetHistoryCommand):
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    )
                alias, onion = resolved

            rows: List[Tuple[str, str, Optional[str], str]] = self._hm.get_history(
                onion, cmd.limit
            )
            history_data: List[HistoryEntry] = [
                HistoryEntry(
                    timestamp=t,
                    status=s,
                    onion=o,
                    reason=r,
                    alias=self._cm.require_alias_by_onion(o) if o else None,
                )
                for t, s, o, r in rows
            ]
            return HistoryDataEvent(
                history=history_data,
                profile=self._pm.profile_name,
                alias=alias,
            )

        if isinstance(cmd, ClearHistoryCommand):
            active_onions = self._get_active_onions()
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return create_event(
                        EventType.PEER_NOT_FOUND,
                        {'target': cmd.target},
                    )
                alias, onion = resolved

            ch_success, ch_event_type, ch_params = self._hm.clear_history(onion)
            if ch_success and ch_event_type is EventType.HISTORY_CLEARED and alias:
                ch_params = {'alias': alias}

            deleted_aliases: List[str] = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(
                    ContactRemovedEvent(alias=a, profile=self._pm.profile_name)
                )

            return create_event(ch_event_type, ch_params)

        if isinstance(cmd, GetMessagesCommand):
            if not cmd.target:
                return create_event(EventType.INVALID_TARGET, {'target': ''})

            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                return create_event(
                    EventType.INVALID_TARGET,
                    {'target': cmd.target},
                )

            alias, onion = resolved
            messages_raw: List[Dict[str, str]] = self._mm.get_chat_history(
                onion, cmd.limit
            )
            messages: List[MessageEntry] = [MessageEntry(**m) for m in messages_raw]
            return MessagesDataEvent(
                messages=messages,
                alias=alias,
            )

        if isinstance(cmd, ClearMessagesCommand):
            active_onions = self._get_active_onions()
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return create_event(
                        EventType.PEER_NOT_FOUND,
                        {'target': cmd.target},
                    )
                alias, onion = resolved

            cm_success, cm_event_type, cm_params = self._mm.clear_messages(
                onion, cmd.non_contacts_only
            )
            if cm_success and cm_event_type is EventType.MESSAGES_CLEARED and alias:
                cm_params = {'alias': alias}
            if (
                cm_success
                and cm_event_type is EventType.MESSAGES_CLEARED_NON_CONTACTS
                and alias
            ):
                cm_params = {'alias': alias}

            deleted_aliases = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(
                    ContactRemovedEvent(alias=a, profile=self._pm.profile_name)
                )

            return create_event(cm_event_type, cm_params)

        if isinstance(cmd, GetInboxCommand):
            counts: Dict[str, int] = self._mm.get_unread_counts()
            inbox_data: Dict[str, int] = {
                self._cm.require_alias_by_onion(o): c for o, c in counts.items()
            }
            return InboxCountsEvent(inbox=inbox_data)

        if isinstance(cmd, MarkReadCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                return create_event(
                    EventType.PEER_NOT_FOUND,
                    {'target': cmd.target},
                )
            alias, onion = resolved

            raw_messages: List[Tuple[int, str, str, str]] = self._mm.get_and_read_inbox(
                onion
            )
            messages_list: List[UnreadMessageEntry] = [
                UnreadMessageEntry(timestamp=str(m[3]), payload=str(m[2]))
                for m in raw_messages
            ]
            return UnreadMessagesEvent(
                messages=messages_list,
                alias=alias,
            )

        return create_event(EventType.UNKNOWN_COMMAND)
