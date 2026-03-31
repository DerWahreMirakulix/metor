"""
Module defining the DatabaseCommandHandler.
Encapsulates all stateless CRUD operations for Contacts, History, and Messages.
Used by both the active Daemon engine and the HeadlessDaemon. Emits strict DTOs.
"""

from typing import Dict, List, Tuple, Callable, Optional, Union

from metor.core.api import (
    IpcCommand,
    IpcEvent,
    ContactCode,
    DbCode,
    NetworkCode,
    SystemCode,
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
                add_success, add_code, add_params = self._cm.add_contact(
                    cmd.alias, cmd.onion
                )
            else:
                add_success, add_code, add_params = self._cm.promote_discovered_peer(
                    cmd.alias
                )

            alias_res: str = str(add_params.get('alias', cmd.alias))
            if add_success:
                return ContactActionSuccessEvent(
                    action=cmd.action,
                    code=add_code,
                    alias=alias_res,
                    profile=str(add_params.get('profile', '')),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=add_code,
                alias=alias_res,
            )

        if isinstance(cmd, RemoveContactCommand):
            active_onions = self._get_active_onions()
            rm_success, rm_code, rm_params, rm_renames, rm_removed = (
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
                    self._broadcast(ContactRemovedEvent(alias=a))

            self._cm.cleanup_orphans(active_onions)
            rm_alias_res: str = str(rm_params.get('alias', cmd.alias))

            if rm_success:
                return ContactActionSuccessEvent(
                    action=cmd.action,
                    code=rm_code,
                    alias=rm_alias_res,
                    profile=str(rm_params.get('profile', '')),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=rm_code,
                alias=rm_alias_res,
            )

        if isinstance(cmd, RenameContactCommand):
            rn_success, rn_code, rn_params = self._cm.rename_contact(
                cmd.old_alias, cmd.new_alias
            )
            if rn_success:
                self._broadcast(
                    RenameSuccessEvent(old_alias=cmd.old_alias, new_alias=cmd.new_alias)
                )
                return ContactRenamedEvent(
                    action=cmd.action,
                    code=rn_code,
                    old_alias=cmd.old_alias,
                    new_alias=cmd.new_alias,
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=rn_code,
                alias=str(rn_params.get('alias', cmd.old_alias)),
            )

        if isinstance(cmd, ClearContactsCommand):
            active_onions = self._get_active_onions()
            clr_success, clr_code, clr_params, clr_renames, clr_removed = (
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
                    self._broadcast(ContactRemovedEvent(alias=a))

            self._cm.cleanup_orphans(active_onions)

            if clr_success:
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=clr_code,
                    profile=str(clr_params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(action=cmd.action, code=clr_code)

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
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return ActionErrorEvent(
                        action=cmd.action,
                        code=NetworkCode.INVALID_TARGET,
                        target=cmd.target,
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
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return ActionErrorEvent(
                        action=cmd.action,
                        code=ContactCode.PEER_NOT_FOUND,
                        target=cmd.target,
                    )
                alias, onion = resolved

            ch_success, ch_code, ch_params = self._hm.clear_history(onion)

            deleted_aliases: List[str] = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            if ch_success:
                if cmd.target:
                    return TargetActionSuccessEvent(
                        action=cmd.action,
                        code=ch_code,
                        target=str(ch_params.get('target') or alias),
                    )
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=ch_code,
                    profile=str(ch_params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=ch_code,
                target=str(ch_params.get('target', cmd.target)),
            )

        if isinstance(cmd, GetMessagesCommand):
            if not cmd.target:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=NetworkCode.INVALID_TARGET,
                )

            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=NetworkCode.INVALID_TARGET,
                    target=cmd.target,
                )

            alias, onion = resolved
            messages_raw: List[Dict[str, str]] = self._mm.get_chat_history(
                onion, cmd.limit
            )
            messages: List[MessageEntry] = [MessageEntry(**m) for m in messages_raw]
            return MessagesDataEvent(
                messages=messages,
                target=alias,
            )

        if isinstance(cmd, ClearMessagesCommand):
            active_onions = self._get_active_onions()
            alias = None
            onion = None

            if cmd.target:
                resolved = self._cm.resolve_target(cmd.target)
                if not resolved:
                    return ActionErrorEvent(
                        action=cmd.action,
                        code=ContactCode.PEER_NOT_FOUND,
                        target=cmd.target,
                    )
                alias, onion = resolved

            cm_success, cm_code, cm_params = self._mm.clear_messages(
                onion, cmd.non_contacts_only
            )

            deleted_aliases = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            if cm_success:
                if cmd.target:
                    return TargetActionSuccessEvent(
                        action=cmd.action,
                        code=cm_code,
                        target=str(cm_params.get('target') or alias),
                    )
                return ProfileActionSuccessEvent(
                    action=cmd.action,
                    code=cm_code,
                    profile=str(cm_params.get('profile', self._pm.profile_name)),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=cm_code,
                target=str(cm_params.get('target', cmd.target)),
            )

        if isinstance(cmd, GetInboxCommand):
            counts: Dict[str, int] = self._mm.get_unread_counts()
            inbox_data: Dict[str, int] = {
                self._cm.get_alias_by_onion(o) or o: c for o, c in counts.items()
            }
            return InboxCountsEvent(inbox=inbox_data)

        if isinstance(cmd, MarkReadCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=ContactCode.PEER_NOT_FOUND,
                    target=cmd.target,
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
                target=alias,
            )

        return ActionErrorEvent(
            action=cmd.action,
            code=SystemCode.UNKNOWN_COMMAND,
        )
