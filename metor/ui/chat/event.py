"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates.
"""

import threading
from typing import Optional

from metor.ui.chat.renderer import Renderer
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import UIMessageType
from metor.core.api import IpcEvent, EventType, IpcCommand, Action
from metor.ui.theme import Theme
from metor.utils.helper import clean_onion


class EventHandler:
    """Processes incoming strongly-typed IPC events from the daemon."""

    def __init__(
        self,
        ipc: IpcClient,
        session: Session,
        renderer: Renderer,
        init_event: threading.Event,
        conn_event: threading.Event,
    ) -> None:
        """Initializes the EventHandler with dependencies."""
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer
        self._init_event: threading.Event = init_event
        self._conn_event: threading.Event = conn_event

    def handle(self, event: IpcEvent) -> None:
        """
        Routes a single IPC event to the appropriate state-change or rendering logic.

        Args:
            event (IpcEvent): The DTO payload received from the Daemon.
        """
        try:
            if event.type == EventType.INIT:
                self._session.my_onion = event.onion or 'unknown'
                self._init_event.set()

            elif event.type == EventType.INFO:
                self._renderer.print_message(
                    event.text, msg_type=UIMessageType.INFO, alias=event.alias
                )

            elif event.type == EventType.SYSTEM:
                self._renderer.print_message(event.text, msg_type=UIMessageType.SYSTEM)

            elif event.type == EventType.REMOTE_MSG:
                self._renderer.print_message(
                    event.text,
                    msg_type=UIMessageType.REMOTE,
                    alias=event.alias,
                    is_drop=False,
                )

            elif event.type == EventType.ACK:
                if event.msg_id:
                    self._renderer.mark_acked(event.msg_id)

            elif event.type == EventType.CONNECTED:
                if event.alias:
                    if event.alias not in self._session.active_connections:
                        self._session.active_connections.append(event.alias)

                    self._renderer.print_message(
                        event.text, msg_type=UIMessageType.INFO, alias=event.alias
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

            elif event.type == EventType.DISCONNECTED:
                self._renderer.print_message(
                    event.text, msg_type=UIMessageType.INFO, alias=event.alias
                )
                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif event.type == EventType.MSG_FALLBACK_TO_DROP:
                if event.msg_ids:
                    self._renderer.apply_fallback_to_drop(event.msg_ids)

            elif event.type == EventType.INBOX_NOTIFICATION:
                self._renderer.print_message(
                    f'{Theme.CYAN}{event.text}{Theme.RESET}',
                    msg_type=UIMessageType.SYSTEM,
                )

            elif event.type == EventType.INBOX_DATA:
                if event.alias and event.messages:
                    for msg in event.messages:
                        self._renderer.print_message(
                            msg['payload'],
                            msg_type=UIMessageType.REMOTE,
                            alias=event.alias,
                            is_drop=True,
                            is_pending=False,
                        )

            elif event.type == EventType.RENAME_SUCCESS:
                if event.old_alias and event.new_alias:
                    if event.old_alias in self._session.active_connections:
                        self._session.active_connections.remove(event.old_alias)
                        self._session.active_connections.append(event.new_alias)

                    self._renderer.rename_alias_in_history(
                        event.old_alias, event.new_alias
                    )

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

            elif event.type == EventType.CONNECTIONS_STATE:
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

            elif event.type == EventType.CONTACT_LIST:
                self._renderer.print_message(event.text, msg_type=UIMessageType.SYSTEM)

            elif event.type == EventType.SWITCH_SUCCESS:
                self._switch_focus(event.alias)

        except Exception:
            pass

    def _switch_focus(self, alias: Optional[str], hide_message: bool = False) -> None:
        """Helper to safely change the active UI focus and fetch missing drops."""
        old_alias: Optional[str] = self._session.focused_alias
        self._session.focused_alias = alias
        is_live: bool = alias in self._session.active_connections if alias else False

        self._renderer.set_focus(alias, is_live)

        if not hide_message:
            if alias:
                self._renderer.print_message(
                    f"Switched focus to '{alias}'.",
                    alias=alias,
                    msg_type=UIMessageType.INFO,
                )
                self._ipc.send_command(
                    IpcCommand(action=Action.MARK_READ, target=alias)
                )
            else:
                self._renderer.print_message(
                    f"Removed focus from '{old_alias}'.",
                    alias=old_alias,
                    msg_type=UIMessageType.INFO,
                )
