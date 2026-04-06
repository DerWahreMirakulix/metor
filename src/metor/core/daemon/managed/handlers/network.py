"""
Module defining the NetworkCommandHandler.
Encapsulates all logic for initiating and managing Tor connections, Drops, and RAM buffers.
Emits strictly typed Domain Transfer Objects via IPC.
"""

import socket
import threading
from typing import Callable, Dict, Optional, Tuple, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    EventType,
    IpcCommand,
    IpcEvent,
    create_event,
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
    RegisterLiveConsumerCommand,
    SendDropCommand,
    SwitchCommand,
    SwitchSuccessEvent,
    RetunnelCommand,
)
from metor.core.daemon.managed.network import NetworkManager
from metor.data import (
    HistoryManager,
    HistoryActor,
    HistoryEvent,
    ContactManager,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    SettingKey,
)
from metor.utils import clean_onion

# Local Package Imports
from metor.core.daemon.managed.outbox import OutboxWorker

if TYPE_CHECKING:
    from metor.data.profile.config import Config


class NetworkCommandHandler:
    """Processes network-related IPC commands from the UI using strict DTOs."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        network: NetworkManager,
        outbox: OutboxWorker,
        broadcast_cb: Callable[[IpcEvent], None],
        send_to_cb: Callable[[socket.socket, IpcEvent], None],
        register_live_consumer_cb: Callable[[socket.socket], None],
        config: 'Config',
    ) -> None:
        """
        Initializes the NetworkCommandHandler.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event logging.
            mm (MessageManager): Offline messages storage.
            network (NetworkManager): The core network orchestrator.
            outbox (OutboxWorker): The offline drop tunnel worker.
            broadcast_cb (Callable[[IpcEvent], None]): Hook to broadcast IPC events.
            send_to_cb (Callable[[socket.socket, IpcEvent], None]): Hook to send an IPC event to a specific client.
            register_live_consumer_cb (Callable[[socket.socket], None]): Hook to mark one IPC session as an interactive live consumer.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._network: NetworkManager = network
        self._outbox: OutboxWorker = outbox
        self._broadcast: Callable[[IpcEvent], None] = broadcast_cb
        self._send_to: Callable[[socket.socket, IpcEvent], None] = send_to_cb
        self._register_live_consumer: Callable[[socket.socket], None] = (
            register_live_consumer_cb
        )
        self._config: 'Config' = config
        self._client_focuses: Dict[socket.socket, str] = {}
        self._focus_lock: threading.Lock = threading.Lock()

    def _set_client_focus(self, conn: socket.socket, onion: Optional[str]) -> None:
        """
        Synchronizes one IPC client's active peer focus with the daemon state.

        Args:
            conn (socket.socket): The IPC client socket.
            onion (Optional[str]): The newly focused onion or None to clear focus.

        Returns:
            None
        """
        with self._focus_lock:
            previous_onion: Optional[str] = self._client_focuses.get(conn)

            if previous_onion and previous_onion != onion:
                self._network.remove_ui_focus(previous_onion)

            if onion is None:
                self._client_focuses.pop(conn, None)
                return

            if previous_onion != onion:
                self._network.add_ui_focus(onion)

            self._client_focuses[conn] = onion

    def clear_client_focus(self, conn: socket.socket) -> None:
        """
        Removes any tracked focus for a disconnected IPC client.

        Args:
            conn (socket.socket): The disconnected IPC client socket.

        Returns:
            None
        """
        self._set_client_focus(conn, None)

    def _retunnel_target(self, alias: str, onion: str) -> None:
        """
        Routes retunnel requests to the live controller or the drop tunnel worker.

        Args:
            alias (str): The strict alias resolved for the peer.
            onion (str): The strict onion identity.

        Returns:
            None
        """
        if self._network.is_connected_or_pending(onion):
            self._outbox.reset_tunnel(onion)
            self._network.retunnel(onion)
            return

        if not self._network.has_drop_tunnel(onion):
            self._broadcast(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error': 'No cached drop tunnel exists',
                    },
                )
            )
            return

        self._outbox.retunnel(onion, alias)

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
        resolved: Optional[Tuple[str, str]]

        if isinstance(cmd, InitCommand):
            self._send_to(conn, InitEvent(onion=self._tm.onion))

        elif isinstance(cmd, RegisterLiveConsumerCommand):
            self._register_live_consumer(conn)

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

        elif isinstance(cmd, ConnectCommand):
            if self._is_self_target(cmd.target):
                self._send_to(conn, create_event(EventType.CANNOT_CONNECT_SELF))
                return

            resolved = self._cm.resolve_target_for_interaction(cmd.target)
            if not resolved:
                self._send_to(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
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
            _, event_type, params = self._network.force_fallback(cmd.target)
            self._send_to(conn, create_event(event_type, params))

        elif isinstance(cmd, RetunnelCommand):
            resolved = self._cm.resolve_target_for_interaction(cmd.target)
            if not resolved:
                self._send_to(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )
                return

            alias, onion = resolved
            threading.Thread(
                target=self._retunnel_target,
                args=(alias, onion),
                daemon=True,
            ).start()

        elif isinstance(cmd, SendDropCommand):
            if not self._config.get_bool(SettingKey.ALLOW_DROPS):
                self._send_to(conn, create_event(EventType.DROPS_DISABLED))
                return

            if self._is_self_target(cmd.target):
                self._send_to(conn, create_event(EventType.CANNOT_DROP_SELF))
                return

            resolved = self._cm.resolve_target_for_interaction(cmd.target)

            if resolved:
                alias, onion = resolved
                self._mm.queue_message(
                    contact_onion=str(onion),
                    direction=MessageDirection.OUT,
                    msg_type=MessageType.DROP_TEXT,
                    payload=cmd.text,
                    status=MessageStatus.PENDING,
                    msg_id=cmd.msg_id,
                )
                if self._config.get_bool(SettingKey.RECORD_DROP_HISTORY):
                    self._hm.log_event(
                        HistoryEvent.QUEUED,
                        onion,
                        actor=HistoryActor.LOCAL,
                    )

                self._send_to(
                    conn,
                    create_event(
                        EventType.DROP_QUEUED,
                        {'alias': alias, 'onion': onion},
                    ),
                )
            else:
                self._send_to(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )

        elif isinstance(cmd, SwitchCommand):
            if cmd.target is None or cmd.target == '..':
                self._set_client_focus(conn, None)
                self._send_to(conn, SwitchSuccessEvent(alias=None))
            else:
                if self._is_self_target(cmd.target):
                    self._send_to(
                        conn,
                        create_event(EventType.CANNOT_SWITCH_SELF),
                    )
                    return

                resolved = self._cm.resolve_target_for_interaction(cmd.target)
                if not resolved:
                    self._send_to(
                        conn,
                        create_event(
                            EventType.INVALID_TARGET,
                            {'target': cmd.target},
                        ),
                    )
                    return

                alias, onion = resolved
                self._set_client_focus(conn, onion)
                self._send_to(conn, SwitchSuccessEvent(alias=alias, onion=onion))
