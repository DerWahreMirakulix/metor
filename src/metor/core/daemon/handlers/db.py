"""
Module defining the DatabaseCommandHandler.
Encapsulates all stateless CRUD operations for Contacts, History, and Messages.
Used by both the active Daemon engine and the HeadlessDaemon. Emits strict DTOs.
"""

from typing import Dict, Any, List, Tuple, Callable, Optional

from metor.core.api import (
    IpcCommand,
    IpcEvent,
    ContactCode,
    DbCode,
    SystemCode,
    NetworkCode,
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
    ActionErrorEvent,
    ContactActionSuccessEvent,
    ContactRenamedEvent,
    ProfileActionSuccessEvent,
    TargetActionSuccessEvent,
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
        if isinstance(cmd, GetContactsListCommand):
            data: Dict[str, Any] = self._cm.get_contacts_data()
            saved_entries: List[ContactEntry] = [
                ContactEntry(alias=str(r[0]), onion=str(r[1]))
                for r in data.get('saved', [])
            ]
            discovered_entries: List[ContactEntry] = [
                ContactEntry(alias=str(r[0]), onion=str(r[1]))
                for r in data.get('discovered', [])
            ]
            return ContactsDataEvent(
                saved=saved_entries,
                discovered=discovered_entries,
                profile=str(data.get('profile', '')),
            )

        if isinstance(cmd, AddContactCommand):
            if cmd.onion:
                success, code, params = self._cm.add_contact(cmd.alias, cmd.onion)
            else:
                success, code, params = self._cm.promote_discovered_peer(cmd.alias)

            alias_res: str = str(params.get('alias', cmd.alias))
            if success:
                return ContactActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    alias=alias_res,
                    profile=str(params.get('profile', '')),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                alias=alias_res,
            )

        if isinstance(cmd, RemoveContactCommand):
            active_onions: List[str] = self._get_active_onions()
            success, code, params, renames, removed = self._cm.remove_contact(
                cmd.alias, active_onions
            )
            if success:
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
                    self._broadcast(ContactRemovedEvent(alias=a))

            self._cm.cleanup_orphans(active_onions)
            alias_res = str(params.get('alias', cmd.alias))

            if success:
                return ContactActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    alias=alias_res,
                    profile=str(params.get('profile', '')),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                alias=alias_res,
            )

        if isinstance(cmd, RenameContactCommand):
            success, code, params = self._cm.rename_contact(
                cmd.old_alias, cmd.new_alias
            )
            if success:
                self._broadcast(
                    RenameSuccessEvent(old_alias=cmd.old_alias, new_alias=cmd.new_alias)
                )
                return ContactRenamedEvent(
                    action=cmd.action,
                    code=code,
                    old_alias=cmd.old_alias,
                    new_alias=cmd.new_alias,
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                alias=str(params.get('alias', cmd.old_alias)),
            )

        if isinstance(cmd, ClearContactsCommand):
            active_onions = self._get_active_onions()
            success, code, params, renames, removed = self._cm.clear_contacts(
                active_onions
            )
            if success:
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
                    self._broadcast(ContactRemovedEvent(alias=a))

            self._cm.cleanup_orphans(active_onions)

            if success:
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    profile=str(params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(action=cmd.action, code=code)

        if isinstance(cmd, ClearProfileDbCommand):
            active_onions = self._get_active_onions()
            success_c, _, _, renames, removed = self._cm.clear_contacts(active_onions)
            success_h, _, _ = self._hm.clear_history()
            success_m, _, _ = self._mm.clear_messages()

            success: bool = success_c and success_h and success_m
            code: DbCode = DbCode.DB_CLEARED if success else DbCode.DB_CLEAR_FAILED

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
                    self._broadcast(ContactRemovedEvent(alias=a))

            if success:
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    profile=self._pm.profile_name,
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                target=self._pm.profile_name,
            )

        if isinstance(cmd, GetHistoryCommand):
            alias, onion, _ = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            rows: List[Tuple[str, str, Optional[str], str]] = self._hm.get_history(
                onion, cmd.limit
            )
            history_data: List[HistoryEntry] = [
                HistoryEntry(
                    timestamp=t,
                    status=s,
                    onion=o,
                    reason=r,
                    alias=self._cm.get_alias_by_onion(o) or 'Unknown'
                    if o
                    else 'Unknown',
                )
                for t, s, o, r in rows
            ]
            return HistoryDataEvent(
                history=history_data,
                profile=self._pm.profile_name,
                target=alias,
            )

        if isinstance(cmd, ClearHistoryCommand):
            active_onions = self._get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, code, params = (
                    False,
                    ContactCode.PEER_NOT_FOUND,
                    {'target': cmd.target},
                )
            else:
                success, code, params = self._hm.clear_history(onion)

            deleted_aliases: List[str] = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            if success:
                if cmd.target:
                    return TargetActionSuccessEvent(
                        action=cmd.action,
                        code=code,
                        target=str(params.get('target') or alias),
                    )
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    profile=str(params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                target=str(params.get('target', cmd.target)),
            )

        if isinstance(cmd, GetMessagesCommand):
            alias, onion, _ = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            if cmd.target:
                messages_raw: List[Dict[str, Any]] = self._mm.get_chat_history(
                    str(onion), cmd.limit
                )
                messages: List[MessageEntry] = [MessageEntry(**m) for m in messages_raw]
                return MessagesDataEvent(
                    messages=messages,
                    target=str(alias),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=NetworkCode.INVALID_TARGET,
                target=cmd.target,
                alias=alias,
            )

        if isinstance(cmd, ClearMessagesCommand):
            active_onions = self._get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, code, params = (
                    False,
                    ContactCode.PEER_NOT_FOUND,
                    {'target': cmd.target},
                )
            else:
                success, code, params = self._mm.clear_messages(
                    onion, cmd.non_contacts_only
                )

            deleted_aliases = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            if success:
                if cmd.target:
                    return TargetActionSuccessEvent(
                        action=cmd.action,
                        code=code,
                        target=str(params.get('target') or alias),
                    )
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=code,
                    profile=str(params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                target=str(params.get('target', cmd.target)),
            )

        if isinstance(cmd, GetInboxCommand):
            counts: Dict[str, int] = self._mm.get_unread_counts()
            inbox_data: Dict[str, int] = {
                self._cm.get_alias_by_onion(o) or o: c for o, c in counts.items()
            }
            return InboxCountsEvent(inbox=inbox_data)

        if isinstance(cmd, MarkReadCommand):
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            if not exists:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=ContactCode.PEER_NOT_FOUND,
                    target=cmd.target,
                    alias=alias,
                )

            raw_messages: List[Tuple[int, str, str, str]] = self._mm.get_and_read_inbox(
                str(onion)
            )
            messages_list: List[UnreadMessageEntry] = [
                UnreadMessageEntry(timestamp=str(m[3]), payload=str(m[2]))
                for m in raw_messages
            ]
            return UnreadMessagesEvent(
                messages=messages_list,
                target=str(alias),
            )

        return ActionErrorEvent(
            action=cmd.action,
            code=SystemCode.UNKNOWN_COMMAND,
        )
