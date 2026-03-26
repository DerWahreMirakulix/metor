"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates.
"""

import threading
from typing import Optional

from metor.core.api import (
    IpcEvent,
    MarkReadCommand,
    InitEvent,
    InfoEvent,
    SystemEvent,
    RemoteMsgEvent,
    AckEvent,
    ConnectedEvent,
    DisconnectedEvent,
    MsgFallbackToDropEvent,
    InboxNotificationEvent,
    InboxDataEvent,
    RenameSuccessEvent,
    ConnectionsStateEvent,
    ContactListEvent,
    SwitchSuccessEvent,
)
from metor.utils.helper import clean_onion

# Local Package Imports
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import UIMessageType


class EventHandler:
    """Processes incoming strictly-typed IPC events from the daemon."""

    def __init__(
        self,
        ipc: IpcClient,
        session: Session,
        renderer: Renderer,
        init_event: threading.Event,
        conn_event: threading.Event,
    ) -> None:
        """
        Initializes the EventHandler with dependencies.

        Args:
            ipc (IpcClient): The IPC client.
            session (Session): The current chat session state.
            renderer (Renderer): The terminal UI renderer.
            init_event (threading.Event): Event to signal successful initialization.
            conn_event (threading.Event): Event to signal connection state updates.

        Returns:
            None
        """
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer
        self._init_event: threading.Event = init_event
        self._conn_event: threading.Event = conn_event

    def handle(self, event: IpcEvent) -> None:
        """
        Routes a single IPC event to the appropriate state-change or rendering logic.

        Args:
            event (IpcEvent): The strongly-typed event received from the Daemon.

        Returns:
            None
        """
        try:
            if isinstance(event, InitEvent):
                self._session.my_onion = event.onion or 'unknown'
                self._init_event.set()

            elif isinstance(event, InfoEvent):
                self._renderer.print_message(
                    event.text, msg_type=UIMessageType.INFO, alias=event.alias
                )

            elif isinstance(event, SystemEvent):
                self._renderer.print_message(event.text, msg_type=UIMessageType.SYSTEM)

            elif isinstance(event, RemoteMsgEvent):
                self._renderer.print_message(
                    event.text,
                    msg_type=UIMessageType.REMOTE,
                    alias=event.alias,
                    is_drop=False,
                )

            elif isinstance(event, AckEvent):
                self._renderer.mark_acked(event.msg_id)

            elif isinstance(event, ConnectedEvent):
                if event.alias not in self._session.active_connections:
                    self._session.active_connections.append(event.alias)

                self._renderer.print_message(
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    'Connected.',
                    msg_type=UIMessageType.INFO,
                    alias=event.alias,
                )

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=True)

                if self._session.pending_focus_target and (
                    self._session.pending_focus_target == event.alias
                    or self._session.pending_focus_target == event.onion
                    or self._session.pending_focus_target
                    == clean_onion(event.onion or '')
                ):
                    self._switch_focus(event.alias)
                    self._session.pending_focus_target = None

            elif isinstance(event, DisconnectedEvent):
                self._renderer.print_message(
                    event.text, msg_type=UIMessageType.INFO, alias=event.alias
                )
                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif isinstance(event, MsgFallbackToDropEvent):
                self._renderer.apply_fallback_to_drop(event.msg_ids)

            elif isinstance(event, InboxNotificationEvent):
                self._renderer.print_message(
                    event.text,
                    msg_type=UIMessageType.INFO,
                    alias=event.alias,
                )

            elif isinstance(event, InboxDataEvent):
                if event.alias and event.messages:
                    for msg in event.messages:
                        self._renderer.print_message(
                            msg['payload'],
                            msg_type=UIMessageType.REMOTE,
                            alias=event.alias,
                            is_drop=True,
                            is_pending=False,
                        )

            elif isinstance(event, RenameSuccessEvent):
                if event.old_alias in self._session.active_connections:
                    self._session.active_connections.remove(event.old_alias)
                    self._session.active_connections.append(event.new_alias)

                self._renderer.rename_alias_in_history(event.old_alias, event.new_alias)

                if self._session.focused_alias == event.old_alias:
                    self._switch_focus(event.new_alias, hide_message=True)

                if event.is_demotion:
                    self._renderer.print_message(
                        f"Contact '{event.old_alias}' removed. Session downgraded to '{event.new_alias}'.",
                        msg_type=UIMessageType.SYSTEM,
                    )
                else:
                    self._renderer.print_message(
                        f"Renamed '{event.old_alias}' to '{event.new_alias}'.",
                        msg_type=UIMessageType.SYSTEM,
                    )

            elif isinstance(event, ConnectionsStateEvent):
                self._session.active_connections = event.active
                if event.is_header:
                    self._session.header_active = event.active
                    self._session.header_pending = event.pending
                    self._session.header_contacts = event.contacts
                    self._conn_event.set()
                else:
                    self._renderer.print_message(
                        self._session.show(is_header_mode=False),
                        msg_type=UIMessageType.SYSTEM,
                    )

            elif isinstance(event, ContactListEvent):
                self._renderer.print_message(event.text, msg_type=UIMessageType.SYSTEM)

            elif isinstance(event, SwitchSuccessEvent):
                self._switch_focus(event.alias)

        except Exception:
            pass

    def _switch_focus(self, alias: Optional[str], hide_message: bool = False) -> None:
        """
        Helper to safely change the active UI focus and fetch missing drops.

        Args:
            alias (Optional[str]): The target alias.
            hide_message (bool): Flag to skip printing the focus message.

        Returns:
            None
        """
        old_alias: Optional[str] = self._session.focused_alias

        if old_alias == alias:
            if alias:
                self._renderer.print_message(
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    "Already focused on '{alias}'.",
                    alias=alias,
                    msg_type=UIMessageType.INFO,
                )
            else:
                self._renderer.print_message(
                    'No active focus.',
                    msg_type=UIMessageType.SYSTEM,
                )
            return

        self._session.focused_alias = alias
        is_live: bool = alias in self._session.active_connections if alias else False

        self._renderer.set_focus(alias, is_live)

        if not hide_message:
            if alias:
                self._renderer.print_message(
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    "Switched focus to '{alias}'.",
                    alias=alias,
                    msg_type=UIMessageType.INFO,
                )
                self._ipc.send_command(MarkReadCommand(target=alias))
            elif old_alias:
                self._renderer.print_message(
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    "Removed focus from '{alias}'.",
                    alias=old_alias,
                    msg_type=UIMessageType.INFO,
                )
