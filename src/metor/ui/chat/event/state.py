"""Helpers for chat UI state mutation events."""

from typing import Optional

from metor.core.api import (
    ConnectionsStateEvent,
    ContactRemovedEvent,
    IpcEvent,
    RenameSuccessEvent,
    SwitchSuccessEvent,
)
from metor.ui import StatusTone

# Local Package Imports
from metor.ui.chat.event.protocols import EventHandlerProtocol
from metor.ui.chat.models import ChatMessageType
from metor.ui.chat.presenter import ChatPresenter


def _replace_alias_in_list(entries: list[str], old_alias: str, new_alias: str) -> None:
    """
    Replaces one alias in-place while preserving the existing list order.

    Args:
        entries (list[str]): The list to update.
        old_alias (str): The previous alias.
        new_alias (str): The new alias.

    Returns:
        None
    """
    for index, value in enumerate(entries):
        if value == old_alias:
            entries[index] = new_alias


def handle_state_event(handler: EventHandlerProtocol, event: IpcEvent) -> bool:
    """
    Handles alias, contact, and focus state mutation events.

    Args:
        handler (EventHandlerProtocol): The owning EventHandler instance.
        event (IpcEvent): The incoming IPC event.

    Returns:
        bool: True when the event was handled.
    """
    if isinstance(event, RenameSuccessEvent):
        rename_onion: Optional[str] = event.onion or handler._session.get_peer_onion(
            event.old_alias
        )
        handler._remember_peer(event.new_alias, rename_onion)
        _replace_alias_in_list(
            handler._session.active_connections,
            event.old_alias,
            event.new_alias,
        )
        _replace_alias_in_list(
            handler._session.pending_connections,
            event.old_alias,
            event.new_alias,
        )
        _replace_alias_in_list(
            handler._session.header_active,
            event.old_alias,
            event.new_alias,
        )
        _replace_alias_in_list(
            handler._session.header_pending,
            event.old_alias,
            event.new_alias,
        )
        _replace_alias_in_list(
            handler._session.header_contacts,
            event.old_alias,
            event.new_alias,
        )
        if handler._session.pending_focus_target == event.old_alias:
            handler._session.pending_focus_target = event.new_alias
        if handler._session.pending_accept_focus_target == event.old_alias:
            handler._session.pending_accept_focus_target = event.new_alias

        if handler._session.focused_alias == event.old_alias:
            handler._switch_focus(event.new_alias, hide_message=True)
        else:
            handler._renderer.refresh_alias_bindings()
        return True

    if isinstance(event, ContactRemovedEvent):
        handler._cancel_buffered_notification(event.alias, event.onion)
        handler._session.forget_peer(event.onion)
        if event.alias in handler._session.active_connections:
            handler._session.active_connections.remove(event.alias)
        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_focus_target = None
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
        handler._renderer.refresh_alias_bindings()
        if handler._session.focused_alias == event.alias:
            handler._switch_focus(None, hide_message=True, sync_daemon=True)
        return True

    if isinstance(event, ConnectionsStateEvent):
        handler._session.active_connections = event.active
        handler._session.pending_connections = event.pending
        if event.is_header:
            handler._session.header_active = event.active
            handler._session.header_pending = event.pending
            handler._session.header_contacts = event.contacts
            handler._conn_event.set()
        else:
            formatted_state: str = ChatPresenter.format_session_state(
                handler._session.active_connections,
                handler._session.pending_connections,
                handler._session.header_contacts,
                handler._session.focused_alias,
                is_header_mode=False,
            )
            handler._renderer.print_message(
                formatted_state,
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.SYSTEM,
            )
        return True

    if isinstance(event, SwitchSuccessEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._switch_focus(event.alias)
        return True

    return False
