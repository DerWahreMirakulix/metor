"""Message and inbox-specific database command handling."""

import json
from typing import Callable, Dict, List, Optional, Tuple

from metor.core.api import (
    ClearMessagesCommand,
    DeleteMessageCommand,
    EventType,
    GetInboxCommand,
    GetMessagesCommand,
    ListRetainedMessagesCommand,
    InboxCountsEvent,
    IpcEvent,
    MarkReadCommand,
    MessageDirectionCode,
    MessageOperationReason,
    MessageEntry,
    MessageStatusCode,
    MessagesDataEvent,
    RetainedMessageEntry,
    RetainedMessagesEvent,
    RuntimeStateChangedEvent,
    UnreadMessageEntry,
    UnreadMessagesEvent,
    create_event,
    ContentType,
    deserialize_content,
    VoiceContent,
)
from metor.core.api import Delivery
from metor.data import MessageDirection, SettingKey
from metor.data.message import (
    MessageClearOperationType,
    MessageClearResult,
    MessageDeleteOutcome,
)

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

    _send_read_receipt_cb: Optional[Callable[[str, List[str]], None]]
    _release_consumed_voice_cb: Optional[Callable[[str, List[str]], None]]
    _delete_persistent_blob_cb: Optional[Callable[[str], None]]

    def _delete_voice_payloads(self, payloads: List[str]) -> None:
        """Best-effort deletes persistent Voice objects after metadata commits."""
        if self._delete_persistent_blob_cb is None:
            return
        for payload in payloads:
            try:
                content = deserialize_content(ContentType.VOICE, payload)
                if isinstance(content, VoiceContent):
                    self._delete_persistent_blob_cb(content.blob_id)
                metadata = json.loads(payload)
                if isinstance(metadata, dict):
                    chunk_ids = metadata.get('chunk_ids', [])
                    if isinstance(chunk_ids, list):
                        for chunk_id in chunk_ids:
                            if isinstance(chunk_id, str):
                                self._delete_persistent_blob_cb(chunk_id)
            except (KeyError, OSError, TypeError, ValueError):
                continue

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
                direction=MessageDirectionCode(message.direction),
                status=MessageStatusCode(message.status),
                delivery=Delivery.DROP,
                content=deserialize_content(
                    ContentType(message.content_type), message.payload
                ),
                timestamp=message.timestamp,
                msg_id=message.msg_id,
            )
            for message in messages_raw
        ]
        return MessagesDataEvent(messages=messages, alias=alias, onion=onion)

    def _handle_list_retained_messages(
        self, cmd: ListRetainedMessagesCommand
    ) -> IpcEvent:
        """Returns retained identities without reading or consuming payloads."""
        onion: Optional[str] = None
        if cmd.target:
            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                return create_event(EventType.INVALID_TARGET, {'target': cmd.target})
            _, onion = resolved
        direction = (
            MessageDirection(cmd.direction.value) if cmd.direction is not None else None
        )
        try:
            page = self._mm.list_retained_messages(
                contact_onion=onion,
                delivery=cmd.delivery,
                direction=direction,
                cursor=cmd.cursor,
                limit=cmd.limit,
            )
        except ValueError as exc:
            return create_event(
                EventType.RETAINED_MESSAGES_UNAVAILABLE,
                {'reason': str(exc), 'retryable': True},
            )
        entries = [
            RetainedMessageEntry(
                onion=message.peer_onion,
                alias=self._cm.require_alias_by_onion(message.peer_onion),
                direction=MessageDirectionCode(message.direction.value),
                delivery=Delivery(message.delivery),
                status=MessageStatusCode(message.status),
                content_type=ContentType(message.content_type),
                msg_id=message.msg_id,
                finalized=message.finalized,
                size_bytes=message.retained_bytes,
                codec=message.codec,
                duration_ms=message.duration_ms,
            )
            for message in page.messages
        ]
        return RetainedMessagesEvent(
            messages=entries,
            next_cursor=page.next_cursor,
            inventory_version=page.inventory_version,
        )

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

        voice_payloads = self._mm.get_drop_voice_payloads(
            onion=onion,
            non_contacts_only=cmd.non_contacts_only,
        )
        result: MessageClearResult = self._mm.clear_messages(
            onion,
            cmd.non_contacts_only,
        )
        if result.success:
            self._delete_voice_payloads(voice_payloads)
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
        if result.success:
            self._broadcast(RuntimeStateChangedEvent(scope='messages', onion=onion))
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
        raw_messages = self._mm.get_and_read_inbox(onion, cmd.delivery)
        messages_list: List[UnreadMessageEntry] = [
            UnreadMessageEntry(
                timestamp=str(message[3]),
                delivery=Delivery(str(message[1])),
                content=deserialize_content(
                    ContentType(str(message[5])), str(message[2])
                ),
                msg_id=str(message[4]) if message[4] is not None else None,
            )
            for message in raw_messages
        ]
        msg_ids: List[str] = [
            str(message[4]) for message in raw_messages if message[4] is not None
        ]
        voice_msg_ids = [
            str(message[4])
            for message in raw_messages
            if message[4] is not None and str(message[5]) == ContentType.VOICE.value
        ]
        if self._release_consumed_voice_cb is not None and voice_msg_ids:
            self._release_consumed_voice_cb(onion, voice_msg_ids)
        if self._pm.config.get_bool(SettingKey.EPHEMERAL_MESSAGES):
            self._delete_voice_payloads(
                [
                    str(message[2])
                    for message in raw_messages
                    if message[1] == Delivery.DROP.value
                    and message[5] == ContentType.VOICE.value
                ]
            )
        if (
            self._send_read_receipt_cb is not None
            and msg_ids
            and self._pm.config.get_bool(SettingKey.SEND_READ_RECEIPTS)
        ):
            self._send_read_receipt_cb(onion, msg_ids)
        if raw_messages:
            self._broadcast(RuntimeStateChangedEvent(scope='inbox', onion=onion))
        return UnreadMessagesEvent(messages=messages_list, alias=alias, onion=onion)

    def _handle_delete_message(self, cmd: DeleteMessageCommand) -> IpcEvent:
        """Deletes one eligible local DROP payload by stable identity.

        Args:
            cmd (DeleteMessageCommand): Target and stable message identity.

        Returns:
            IpcEvent: Typed success or rejection event.
        """
        resolved = self._cm.resolve_target(cmd.target)
        if not resolved:
            return create_event(EventType.PEER_NOT_FOUND, {'target': cmd.target})
        alias, onion = resolved
        direction = (
            MessageDirection(cmd.direction.value) if cmd.direction is not None else None
        )
        voice_payloads = self._mm.get_drop_voice_payloads(
            onion=onion,
            msg_id=cmd.msg_id,
            direction=direction,
        )
        outcome = self._mm.delete_drop_message(onion, cmd.msg_id, direction)
        if outcome is MessageDeleteOutcome.DELETED:
            self._delete_voice_payloads(voice_payloads)
            self._broadcast(RuntimeStateChangedEvent(scope='messages', onion=onion))
            return create_event(
                EventType.MESSAGE_DELETED,
                {'alias': alias, 'onion': onion, 'msg_id': cmd.msg_id},
            )
        reason_map = {
            MessageDeleteOutcome.NOT_FOUND: MessageOperationReason.NOT_FOUND,
            MessageDeleteOutcome.NOT_DROP: MessageOperationReason.NOT_DROP,
            MessageDeleteOutcome.PENDING_DELIVERY: (
                MessageOperationReason.PENDING_DELIVERY
            ),
            MessageDeleteOutcome.AMBIGUOUS_IDENTITY: (
                MessageOperationReason.AMBIGUOUS_IDENTITY
            ),
        }
        return create_event(
            EventType.MESSAGE_DELETE_REJECTED,
            {
                'target': cmd.target,
                'onion': onion,
                'msg_id': cmd.msg_id,
                'reason': reason_map[outcome].value,
            },
        )
