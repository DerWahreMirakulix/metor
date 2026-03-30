"""
Module defining the NetworkCommandHandler.
Encapsulates all logic for initiating and managing Tor connections, Drops, and RAM buffers.
Emits strictly typed Domain Transfer Objects via IPC.
"""

import socket
import threading
from typing import Callable, Optional

from metor.core import TorManager
from metor.core.api import (
    IpcCommand,
    IpcEvent,
    TransCode,
    InitCommand,
    InitEvent,
    GetConnectionsCommand,
    ConnectionsStateEvent,
    ConnectCommand,
    DisconnectCommand,
    AcceptCommand,
    RejectCommand,
    MsgCommand,
    FallbackCommand,
    SendDropCommand,
    SwitchCommand,
    SwitchSuccessEvent,
    RetunnelCommand,
    ActionErrorEvent,
    TargetActionSuccessEvent,
    FallbackSuccessEvent,
)
from metor.core.daemon.network import NetworkManager
from metor.data import (
    HistoryManager,
    HistoryEvent,
    ContactManager,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    Settings,
    SettingKey,
)
from metor.utils import clean_onion


class NetworkCommandHandler:
    """Processes network-related IPC commands from the UI using strict DTOs."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        network: NetworkManager,
        broadcast_cb: Callable[[IpcEvent], None],
        send_to_cb: Callable[[socket.socket, IpcEvent], None],
    ) -> None:
        """
        Initializes the NetworkCommandHandler.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event logging.
            mm (MessageManager): Offline messages storage.
            network (NetworkManager): The core network orchestrator.
            broadcast_cb (Callable[[IpcEvent], None]): Hook to broadcast IPC events.
            send_to_cb (Callable[[socket.socket, IpcEvent], None]): Hook to send an IPC event to a specific client.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._network: NetworkManager = network
        self._broadcast: Callable[[IpcEvent], None] = broadcast_cb
        self._send_to: Callable[[socket.socket, IpcEvent], None] = send_to_cb

    def _is_self_target(self, target: str) -> bool:
        """
        Safely checks if a target (alias or onion) points to our own identity.

        Args:
            target (str): The alias or onion to check.

        Returns:
            bool: True if it matches our own onion, False otherwise.
        """
        if not target or not self._tm.onion:
            return False

        if clean_onion(target) == clean_onion(self._tm.onion):
            return True

        onion_by_alias: Optional[str] = self._cm.get_onion_by_alias(target)
        if onion_by_alias and onion_by_alias == self._tm.onion:
            return True

        return False

    def handle(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Routes the network command to the NetworkManager or MessageManager and returns DTOs.

        Args:
            cmd (IpcCommand): The network-related IPC command.
            conn (socket.socket): The IPC client connection to respond to.

        Returns:
            None
        """
        if isinstance(cmd, InitCommand):
            self._send_to(conn, InitEvent(onion=self._tm.onion))
            for active_onion in self._network.get_active_onions():
                self._network.flush_ram_buffer(active_onion)

        elif isinstance(cmd, GetConnectionsCommand):
            self._send_to(
                conn,
                ConnectionsStateEvent(
                    active=self._network.get_active_aliases(),
                    pending=self._network.get_pending_aliases(),
                    contacts=self._cm.get_all_contacts(),
                    is_header=cmd.is_header,
                ),
            )
            for active_onion in self._network.get_active_onions():
                self._network.flush_ram_buffer(active_onion)

        elif isinstance(cmd, ConnectCommand):
            if self._is_self_target(cmd.target):
                self._send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=TransCode.CANNOT_CONNECT_SELF,
                    ),
                )
                return

            alias, _, exists = self._cm.resolve_target(cmd.target, auto_create=True)
            if not exists:
                self._send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=TransCode.INVALID_TARGET,
                        target=cmd.target,
                    ),
                )
                return

            threading.Thread(
                target=self._network.connect_to, args=(cmd.target,), daemon=True
            ).start()

        elif isinstance(cmd, DisconnectCommand):
            self._network.disconnect(cmd.target, initiated_by_self=True)

        elif isinstance(cmd, AcceptCommand):
            self._network.accept(cmd.target)

        elif isinstance(cmd, RejectCommand):
            self._network.reject(cmd.target, initiated_by_self=True)

        elif isinstance(cmd, MsgCommand):
            self._network.send_message(cmd.target, cmd.text, cmd.msg_id)

        elif isinstance(cmd, FallbackCommand):
            success, code, params = self._network.force_fallback(cmd.target)
            if success:
                self._send_to(
                    conn,
                    FallbackSuccessEvent(
                        action=cmd.action,
                        code=code,
                        alias=str(params.get('alias', '')),
                        count=int(params.get('count', 0)),
                    ),
                )
            else:
                self._send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=code,
                        alias=str(params.get('alias', '')),
                        target=str(params.get('target', '')),
                    ),
                )

        elif isinstance(cmd, RetunnelCommand):
            threading.Thread(
                target=self._network.retunnel, args=(cmd.target,), daemon=True
            ).start()

        elif isinstance(cmd, SendDropCommand):
            if not Settings.get(SettingKey.ALLOW_DROPS):
                self._send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=TransCode.DROPS_DISABLED,
                    ),
                )
                return

            if self._is_self_target(cmd.target):
                self._send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=TransCode.CANNOT_DROP_SELF,
                    ),
                )
                return

            alias, onion, exists = self._cm.resolve_target(cmd.target, auto_create=True)

            if exists:
                self._mm.queue_message(
                    contact_onion=str(onion),
                    direction=MessageDirection.OUT,
                    msg_type=MessageType.TEXT,
                    payload=cmd.text,
                    status=MessageStatus.PENDING,
                )
                if Settings.get(SettingKey.RECORD_DROP_EVENTS):
                    self._hm.log_event(HistoryEvent.DROP_QUEUED, onion)

                if cmd.cli_mode:
                    self._send_to(
                        conn,
                        TargetActionSuccessEvent(
                            action=cmd.action,
                            code=TransCode.DROP_QUEUED,
                            target=alias,
                        ),
                    )
            else:
                if cmd.cli_mode:
                    self._send_to(
                        conn,
                        ActionErrorEvent(
                            action=cmd.action,
                            code=TransCode.INVALID_TARGET,
                            target=cmd.target,
                        ),
                    )

        elif isinstance(cmd, SwitchCommand):
            if cmd.target is None or cmd.target == '..':
                self._send_to(conn, SwitchSuccessEvent(alias=None))
            else:
                if self._is_self_target(cmd.target):
                    self._send_to(
                        conn,
                        ActionErrorEvent(
                            action=cmd.action,
                            code=TransCode.CANNOT_SWITCH_SELF,
                        ),
                    )
                    return

                alias, _, exists = self._cm.resolve_target(cmd.target)
                if not exists:
                    self._send_to(
                        conn,
                        ActionErrorEvent(
                            action=cmd.action,
                            code=TransCode.INVALID_TARGET,
                            target=cmd.target,
                        ),
                    )
                    return

                self._send_to(conn, SwitchSuccessEvent(alias=alias))
