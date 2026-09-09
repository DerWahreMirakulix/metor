"""Helpers for chat content, data, and inbox event handling."""

import dataclasses
from typing import Dict, List, Optional

from metor.core.api import (
    AckEvent,
    AutoFallbackQueuedEvent,
    ContactsDataEvent,
    DropFailedEvent,
    DropQueuedEvent,
    Delivery,
    FallbackSuccessEvent,
    HistoryDataEvent,
    HistoryRawDataEvent,
    InboxCountsEvent,
    InboxDataEvent,
    InboxNotificationEvent,
    InitEvent,
    IpcEvent,
    JsonValue,
    MarkReadCommand,
    MessagesDataEvent,
    ProfilesDataEvent,
    ReadReceiptEvent,
    MessageReceivedEvent,
    TransportStateEvent,
    UnreadMessageEntry,
    UnreadMessagesEvent,
)
from metor.ui.terminal import AliasPolicy, StatusTone, UIPresenter

# Local Package Imports
from metor.ui.terminal.chat.models import ChatMessageType
from metor.ui.terminal.chat.event.protocols import EventHandlerProtocol
from metor.ui.terminal.chat.presenter import ChatPresenter


def handle_content_event(handler: EventHandlerProtocol, event: IpcEvent) -> bool:
    """
    Handles data-returning, message, and inbox-related chat events.

    Args:
        handler (EventHandlerProtocol): The owning EventHandler instance.
        event (IpcEvent): The incoming IPC event.

    Returns:
        bool: True when the event was handled.
    """
    if isinstance(event, InitEvent):
        handler._session.my_onion = event.onion or 'unknown'
        handler._init_event.set()
        return True

    if isinstance(
        event,
        (
            ContactsDataEvent,
            HistoryDataEvent,
            HistoryRawDataEvent,
            MessagesDataEvent,
            InboxCountsEvent,
            ProfilesDataEvent,
        ),
    ):
        if isinstance(event, ContactsDataEvent):
            for contact_entry in event.saved:
                handler._remember_peer(contact_entry.alias, contact_entry.onion)
            for discovered_entry in event.discovered:
                handler._remember_peer(
                    discovered_entry.alias,
                    discovered_entry.onion,
                )
        elif isinstance(event, (HistoryDataEvent, HistoryRawDataEvent)):
            for history_entry in event.entries:
                handler._remember_peer(
                    history_entry.alias,
                    history_entry.peer_onion,
                )
        elif isinstance(event, MessagesDataEvent):
            handler._remember_peer(event.alias, event.onion)

        text_fmt: str = UIPresenter.format_response(event, chat_mode=True)
        target_alias: Optional[str] = getattr(event, 'target', None) or getattr(
            event,
            'alias',
            None,
        )
        handler._renderer.print_message(
            text_fmt,
            msg_type=ChatMessageType.STATUS,
            tone=StatusTone.SYSTEM,
            alias=target_alias,
        )
        return True

    if isinstance(event, UnreadMessagesEvent):
        handler._cancel_buffered_notification(event.alias, event.onion)
        if event.messages:
            handler._remember_peer(event.alias, event.onion)
            fresh_messages: List[UnreadMessageEntry] = []
            pushed_msg_ids: List[str] = []
            for message in event.messages:
                if message.msg_id and handler._was_pushed_live_msg_id(message.msg_id):
                    pushed_msg_ids.append(message.msg_id)
                else:
                    fresh_messages.append(message)
            if pushed_msg_ids:
                handler._consume_pushed_live_msg_ids(pushed_msg_ids)
            if fresh_messages:
                messages_data: List[Dict[str, JsonValue]] = [
                    {
                        'id': '',
                        'payload': message.content.text,
                        'timestamp': message.timestamp,
                        'is_drop': message.delivery is Delivery.DROP,
                    }
                    for message in fresh_messages
                ]
                handler._renderer.print_messages_batch(
                    messages_data,
                    event.alias,
                    peer_onion=event.onion,
                    is_live_flush=False,
                )
        return True

    if isinstance(event, (AutoFallbackQueuedEvent, FallbackSuccessEvent)):
        handler._remember_peer(event.alias, event.onion)
        fallback_msg_ids: List[str]
        if isinstance(event, AutoFallbackQueuedEvent):
            fallback_msg_ids = [event.msg_id]
        else:
            fallback_msg_ids = event.msg_ids
        handler._renderer.apply_fallback_to_drop(fallback_msg_ids)
        params_raw = dataclasses.asdict(event)
        params: Dict[str, JsonValue] = {
            key: value
            for key, value in params_raw.items()
            if isinstance(value, (str, int, float, bool, type(None), list, dict))
        }
        handler._print_translated(
            event.event_type,
            params,
            event.alias,
            event.onion,
        )
        return True

    if isinstance(event, MessageReceivedEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias and event.alias == handler._session.focused_alias:
            if event.msg_id:
                handler._remember_pushed_live_msg_id(event.msg_id)
            handler._renderer.print_message(
                event.content.text,
                msg_type=ChatMessageType.REMOTE,
                alias=event.alias,
                peer_onion=event.onion,
                alias_policy=(
                    AliasPolicy.DYNAMIC if event.onion else AliasPolicy.STATIC
                ),
                timestamp=event.timestamp,
                is_drop=False,
            )
            handler._ipc.send_command(MarkReadCommand(target=event.alias))
        else:
            handler._queue_buffered_notification(event.alias, event.onion, 1)
        return True

    if isinstance(event, TransportStateEvent):
        handler._renderer.print_message(
            ChatPresenter.format_transport_state(event),
            msg_type=ChatMessageType.STATUS,
            tone=StatusTone.SYSTEM,
        )
        return True

    if isinstance(event, ReadReceiptEvent):
        handler._renderer.print_message(
            f'{event.alias} read the message.',
            msg_type=ChatMessageType.STATUS,
            tone=StatusTone.SYSTEM,
        )
        return True

    if isinstance(event, AckEvent):
        handler._renderer.mark_acked(
            msg_id=event.msg_id,
            text=None,
            timestamp=event.timestamp,
        )
        return True

    if isinstance(event, DropFailedEvent):
        handler._renderer.mark_failed(msg_id=event.msg_id)
        return True

    if isinstance(event, DropQueuedEvent):
        return True

    if isinstance(event, InboxNotificationEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias and event.alias == handler._session.focused_alias:
            handler._cancel_buffered_notification(event.alias, event.onion)
            handler._ipc.send_command(
                handler._mark_read_command_type(target=event.alias)
            )
        elif event.alias:
            handler._queue_buffered_notification(
                event.alias,
                event.onion,
                event.count,
            )
        return True

    if isinstance(event, InboxDataEvent):
        if event.alias and event.messages:
            handler._remember_peer(event.alias, event.onion)
            messages_data_dict: List[Dict[str, JsonValue]] = [
                {
                    'id': '',
                    'timestamp': message.timestamp,
                    'payload': message.content.text,
                    'is_drop': message.delivery is Delivery.DROP,
                }
                for message in event.messages
            ]
            handler._renderer.print_messages_batch(
                messages_data_dict,
                event.alias,
                peer_onion=event.onion,
                is_live_flush=event.is_live_flush,
            )
        return True

    return False
