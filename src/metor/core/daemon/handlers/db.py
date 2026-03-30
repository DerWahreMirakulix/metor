"""
Module defining the DatabaseCommandHandler.
Encapsulates all stateless CRUD operations for Contacts, History, and Messages.
Used by both the active Daemon engine and the HeadlessDaemon to enforce DRY.
"""

from typing import Dict, Any, List, Tuple, Callable, Optional

from metor.core.api import (
    IpcCommand,
    IpcEvent,
    CommandResponseEvent,
    TransCode,
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
)
from metor.data.profile import ProfileManager
from metor.data import ContactManager, HistoryManager, MessageManager


class DatabaseCommandHandler:
    """Processes stateless database commands and generates appropriate IPC responses."""

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
            get_active_onions (Callable): Hook to retrieve currently connected onions.
            broadcast (Callable): Hook to broadcast side-effect events to all clients.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._get_active_onions: Callable[[], List[str]] = get_active_onions
        self._broadcast: Callable[[IpcEvent], None] = broadcast

    def handle(self, cmd: IpcCommand) -> CommandResponseEvent:
        """
        Routes the database command to the respective manager and formats the response.

        Args:
            cmd (IpcCommand): The database-related IPC command.

        Returns:
            CommandResponseEvent: The strictly typed response event.
        """
        if isinstance(cmd, GetContactsListCommand):
            data: Dict[str, Any] = self._cm.get_contacts_data()
            return CommandResponseEvent(action=cmd.action, data=data)

        if isinstance(cmd, AddContactCommand):
            if cmd.onion:
                success, code, params = self._cm.add_contact(cmd.alias, cmd.onion)
            else:
                success, code, params = self._cm.promote_discovered_peer(cmd.alias)

            if 'alias' not in params:
                params['alias'] = cmd.alias

            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
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
            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
            )

        if isinstance(cmd, RenameContactCommand):
            success, code, params = self._cm.rename_contact(
                cmd.old_alias, cmd.new_alias
            )
            if success:
                self._broadcast(
                    RenameSuccessEvent(old_alias=cmd.old_alias, new_alias=cmd.new_alias)
                )
            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
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
            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
            )

        if isinstance(cmd, ClearProfileDbCommand):
            active_onions = self._get_active_onions()
            success_c, _, _, renames, removed = self._cm.clear_contacts(active_onions)
            success_h, _, _ = self._hm.clear_history()
            success_m, _, _ = self._mm.clear_messages()

            success: bool = success_c and success_h and success_m
            code: TransCode = (
                TransCode.DB_CLEARED if success else TransCode.DB_CLEAR_FAILED
            )
            params: Dict[str, Any] = (
                {'profile': self._pm.profile_name} if success else {}
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
                    self._broadcast(ContactRemovedEvent(alias=a))

            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
            )

        if isinstance(cmd, GetHistoryCommand):
            alias, onion, _ = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            rows: List[Tuple[str, str, Optional[str], str]] = self._hm.get_history(
                onion, cmd.limit
            )
            history_data: List[Dict[str, Any]] = [
                {
                    'timestamp': t,
                    'status': s,
                    'onion': o,
                    'reason': r,
                    'alias': self._cm.get_alias_by_onion(o) or 'Unknown'
                    if o
                    else 'Unknown',
                }
                for t, s, o, r in rows
            ]
            return CommandResponseEvent(
                action=cmd.action,
                data={
                    'history': history_data,
                    'target': alias,
                    'profile': self._pm.profile_name,
                },
            )

        if isinstance(cmd, ClearHistoryCommand):
            active_onions = self._get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, code, params = (
                    False,
                    TransCode.PEER_NOT_FOUND,
                    {'target': cmd.target},
                )
            else:
                success, code, params = self._hm.clear_history(onion)

            deleted_aliases: List[str] = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            params['alias'] = alias
            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
            )

        if isinstance(cmd, GetMessagesCommand):
            alias, onion, _ = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            if cmd.target:
                messages: List[Dict[str, Any]] = self._mm.get_chat_history(
                    str(onion), cmd.limit
                )
                return CommandResponseEvent(
                    action=cmd.action, data={'messages': messages, 'target': alias}
                )
            return CommandResponseEvent(
                action=cmd.action,
                success=False,
                code=TransCode.GENERIC_MSG,
                params={'msg': 'No target specified.', 'alias': alias},
            )

        if isinstance(cmd, ClearMessagesCommand):
            active_onions = self._get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, code, params = (
                    False,
                    TransCode.PEER_NOT_FOUND,
                    {'target': cmd.target},
                )
            else:
                success, code, params = self._mm.clear_messages(
                    onion, cmd.non_contacts_only
                )

            deleted_aliases = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._broadcast(ContactRemovedEvent(alias=a))

            params['alias'] = alias
            return CommandResponseEvent(
                action=cmd.action, success=success, code=code, params=params
            )

        if isinstance(cmd, GetInboxCommand):
            counts: Dict[str, int] = self._mm.get_unread_counts()
            inbox_data: Dict[str, int] = {
                self._cm.get_alias_by_onion(o) or o: c for o, c in counts.items()
            }
            return CommandResponseEvent(action=cmd.action, data={'inbox': inbox_data})

        if isinstance(cmd, MarkReadCommand):
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )
            if not exists:
                return CommandResponseEvent(
                    action=cmd.action,
                    success=False,
                    code=TransCode.GENERIC_MSG,
                    params={
                        'msg': f"Peer '{cmd.target}' not found in address book.",
                        'alias': alias,
                    },
                )

            raw_messages: List[Tuple[int, str, str, str]] = self._mm.get_and_read_inbox(
                str(onion)
            )
            messages_list: List[Dict[str, str]] = [
                {'timestamp': str(m[3]), 'payload': str(m[2])} for m in raw_messages
            ]
            return CommandResponseEvent(
                action=cmd.action, data={'messages': messages_list, 'target': alias}
            )

        return CommandResponseEvent(
            action=cmd.action,
            success=False,
            code=TransCode.GENERIC_MSG,
            params={'msg': 'Unknown command.'},
        )
