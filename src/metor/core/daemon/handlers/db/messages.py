"""Message and inbox-specific database command handling."""

from typing import Dict, List, Optional, Tuple

from metor.core.api import (
    ClearMessagesCommand,
    EventType,
    GetInboxCommand,
    GetMessagesCommand,
    InboxCountsEvent,
    IpcEvent,
    MarkReadCommand,
    MessageEntry,
    MessagesDataEvent,
    UnreadMessageEntry,
    UnreadMessagesEvent,
    create_event,
)
from metor.data import MessageType
from metor.data.message import MessageClearOperationType, MessageClearResult

# Local Package Imports
from metor.core.daemon.handlers.db.support import DatabaseCommandHandlerSupportMixin


MESSAGE_CLEAR_EVENT_TYPES: dict[MessageClearOperationType, EventType] = {
    MessageClearOperationType.ALL_CLEARED: EventType.MESSAGES_CLEARED_ALL,
    MessageClearOperationType.CLEAR_FAILED: EventType.MESSAGES_CLEAR_FAILED,
    MessageClearOperationType.NON_CONTACTS_ALL_CLEARED: (
        EventType.MESSAGES_CLEARED_NON_CONTACTS_ALL
    ),
    MessageClearOperationType.NON_CONTACTS_TARGET_CLEARED: (
        EventType.MESSAGES_CLEARED_NON_CONTACTS
    ),
    MessageClearOperationType.TARGET_CLEARED: EventType.MESSAGES_CLEARED,
}


class DatabaseCommandMessagesMixin(DatabaseCommandHandlerSupportMixin):
    """Handles chat-history, inbox, and clear-message database commands."""

    def _handle_get_messages(self, cmd: GetMessagesCommand) -> IpcEvent:
        """
        Returns stored drop-visible chat history for one peer target.

        Args:
            cmd (GetMessagesCommand): The incoming get-messages command.

        Returns:
            IpcEvent: The resulting messages data event DTO.
        """
        if not cmd.target:
            return create_event(EventType.INVALID_TARGET, {'target': ''})

        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(cmd.target)
        if not resolved:
            return create_event(EventType.INVALID_TARGET, {'target': cmd.target})

        alias, onion = resolved
        messages_raw = self._mm.get_chat_history(onion, cmd.limit)
        messages = [
            MessageEntry(
                direction=message.direction,
                status=message.status,
                payload=message.payload,
                timestamp=message.timestamp,
            )
            for message in messages_raw
        ]
        return MessagesDataEvent(messages=messages, alias=alias, onion=onion)

    def _handle_clear_messages(self, cmd: ClearMessagesCommand) -> IpcEvent:
        """
        Clears stored messages and cleans up orphaned discovered peers.

        Args:
            cmd (ClearMessagesCommand): The incoming clear-messages command.

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

        result: MessageClearResult = self._mm.clear_messages(
            onion,
            cmd.non_contacts_only,
        )
        params: Dict[str, str] = {}
        if (
            result.operation_type
            in {
                MessageClearOperationType.TARGET_CLEARED,
                MessageClearOperationType.NON_CONTACTS_TARGET_CLEARED,
            }
            and alias
        ):
            params = {'alias': alias}
            if onion:
                params['onion'] = onion
        elif result.operation_type in {
            MessageClearOperationType.ALL_CLEARED,
            MessageClearOperationType.NON_CONTACTS_ALL_CLEARED,
        }:
            params = {'profile': result.profile or self._pm.profile_name}

        self._emit_orphan_cleanup(self._cm.cleanup_orphans(active_onions))
        return create_event(MESSAGE_CLEAR_EVENT_TYPES[result.operation_type], params)

    def _handle_get_inbox(self, _: GetInboxCommand) -> IpcEvent:
        """
        Returns unread inbox counts grouped by peer alias.

        Args:
            _ (GetInboxCommand): The incoming inbox command.

        Returns:
            IpcEvent: The resulting inbox-count event DTO.
        """
        counts: Dict[str, int] = self._mm.get_unread_counts()
        inbox_data: Dict[str, int] = {
            self._cm.require_alias_by_onion(onion): count
            for onion, count in counts.items()
        }
        return InboxCountsEvent(inbox=inbox_data)

    def _handle_mark_read(self, cmd: MarkReadCommand) -> IpcEvent:
        """
        Consumes unread messages for one peer target.

        Args:
            cmd (MarkReadCommand): The incoming mark-read command.

        Returns:
            IpcEvent: The resulting unread-messages event DTO.
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(cmd.target)
        if not resolved:
            return create_event(EventType.PEER_NOT_FOUND, {'target': cmd.target})

        alias, onion = resolved
        raw_messages = self._mm.get_and_read_inbox(onion)
        messages_list: List[UnreadMessageEntry] = [
            UnreadMessageEntry(
                timestamp=str(message[3]),
                payload=str(message[2]),
                is_drop=str(message[1]) != MessageType.LIVE_TEXT.value,
            )
            for message in raw_messages
        ]
        return UnreadMessagesEvent(messages=messages_list, alias=alias, onion=onion)
