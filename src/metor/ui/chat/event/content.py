"""Helpers for chat content, data, and inbox event handling."""

import dataclasses
from typing import Dict, List, Optional

from metor.core.api import (
    AckEvent,
    AutoFallbackQueuedEvent,
    ContactsDataEvent,
    DropFailedEvent,
    DropQueuedEvent,
    FallbackSuccessEvent,
    HistoryDataEvent,
    HistoryRawDataEvent,
    InboxCountsEvent,
    InboxDataEvent,
    InboxNotificationEvent,
    InitEvent,
    IpcEvent,
    JsonValue,
    MessagesDataEvent,
    ProfilesDataEvent,
    RemoteMsgEvent,
    UnreadMessagesEvent,
)
from metor.ui import AliasPolicy, StatusTone, UIPresenter

# Local Package Imports
from metor.ui.chat.models import ChatMessageType
from metor.ui.chat.event.protocols import EventHandlerProtocol


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
            messages_data: List[Dict[str, JsonValue]] = [
                {
                    'id': '',
                    'payload': message.payload,
                    'timestamp': message.timestamp,
                    'is_drop': message.is_drop,
                }
                for message in event.messages
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

    if isinstance(event, RemoteMsgEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._renderer.print_message(
            event.text,
            msg_type=ChatMessageType.REMOTE,
            alias=event.alias,
            peer_onion=event.onion,
            alias_policy=(AliasPolicy.DYNAMIC if event.onion else AliasPolicy.STATIC),
            timestamp=event.timestamp,
            is_drop=False,
        )
        return True

    if isinstance(event, AckEvent):
        handler._renderer.mark_acked(
            msg_id=event.msg_id,
            text=event.text,
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
                    'payload': message.payload,
                    'is_drop': message.is_drop,
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
