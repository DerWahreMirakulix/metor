"""Typed IPC command-family dispatch to installed daemon handlers."""

import socket
from typing import Callable, Optional

from metor.core.api import (
    AcceptCommand,
    AddContactCommand,
    ClearContactsCommand,
    ClearHistoryCommand,
    ClearMessagesCommand,
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    CommitVoiceCommand,
    CancelVoiceCommand,
    DeleteMessageCommand,
    DismissLiveContextCommand,
    ClearProfileDbCommand,
    ConnectCommand,
    DisconnectCommand,
    EventType,
    FallbackCommand,
    FinalizeVoiceCommand,
    GenerateAddressCommand,
    GetAddressCommand,
    GetChatStartupStateCommand,
    GetRuntimeSnapshotCommand,
    GetVoiceChunkCommand,
    GetConfigCommand,
    GetConfigListCommand,
    GetConnectionsCommand,
    GetContactsListCommand,
    GetHistoryCommand,
    GetInboxCommand,
    GetMessagesCommand,
    ListRetainedMessagesCommand,
    GetRawHistoryCommand,
    GetSettingCommand,
    GetSettingsListCommand,
    GetTransportStateCommand,
    InitCommand,
    IpcCommand,
    IpcEvent,
    MarkReadCommand,
    RegisterLiveConsumerCommand,
    ReleaseVoiceCommand,
    RejectCommand,
    RemoveContactCommand,
    RenameContactCommand,
    RetunnelCommand,
    SendMessageCommand,
    SetConfigCommand,
    SetSettingCommand,
    SwitchCommand,
    SyncConfigCommand,
    create_event,
)
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    SystemCommandHandler,
)

# Local Package Imports
from ..handlers import NetworkCommandHandler


class DaemonCommandDispatcher:
    """Routes authorized commands without owning daemon lifecycle or transport."""

    def __init__(
        self,
        config_handler: ConfigCommandHandler,
        send_callback: Callable[[socket.socket, IpcEvent], None],
    ) -> None:
        """Initializes dispatch with its always-available config handler.

        Args:
            config_handler (ConfigCommandHandler): Profile configuration handler.
            send_callback (Callable[[socket.socket, IpcEvent], None]): IPC sender.

        Returns:
            None
        """
        self._config_handler: ConfigCommandHandler = config_handler
        self._send: Callable[[socket.socket, IpcEvent], None] = send_callback
        self._network_handler: Optional[NetworkCommandHandler] = None
        self._database_handler: Optional[DatabaseCommandHandler] = None
        self._system_handler: Optional[SystemCommandHandler] = None

    def install_runtime_handlers(
        self,
        network: NetworkCommandHandler,
        database: DatabaseCommandHandler,
        system: SystemCommandHandler,
    ) -> None:
        """Installs handlers backed by the active unlocked runtime.

        Args:
            network (NetworkCommandHandler): Network command adapter.
            database (DatabaseCommandHandler): Persistence command adapter.
            system (SystemCommandHandler): System command adapter.

        Returns:
            None
        """
        self._network_handler = network
        self._database_handler = database
        self._system_handler = system

    def clear_runtime_handlers(self) -> None:
        """Drops all handlers backed by a locked profile runtime.

        Args:
            None

        Returns:
            None
        """
        self._network_handler = None
        self._database_handler = None
        self._system_handler = None

    def clear_client_focus(self, conn: socket.socket) -> None:
        """Clears network focus owned by a disconnected IPC client.

        Args:
            conn (socket.socket): The disconnected client socket.

        Returns:
            None
        """
        if self._network_handler is not None:
            self._network_handler.clear_client_focus(conn)

    def clear_all_focus(self) -> None:
        """Clears all focus owned by attached IPC clients.

        Args:
            None

        Returns:
            None
        """
        if self._network_handler is not None:
            self._network_handler.clear_all_focus()

    def dispatch(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """Routes one authorized command to its owning handler.

        Args:
            cmd (IpcCommand): The typed command.
            conn (socket.socket): The requesting IPC socket.

        Returns:
            None
        """
        if isinstance(
            cmd,
            (
                SetSettingCommand,
                GetSettingCommand,
                GetSettingsListCommand,
                SetConfigCommand,
                GetConfigCommand,
                GetConfigListCommand,
                SyncConfigCommand,
            ),
        ):
            self._send(conn, self._config_handler.handle(cmd))
            return

        if isinstance(
            cmd,
            (
                InitCommand,
                GetChatStartupStateCommand,
                GetRuntimeSnapshotCommand,
                GetConnectionsCommand,
                ConnectCommand,
                DisconnectCommand,
                AcceptCommand,
                RejectCommand,
                SendMessageCommand,
                RegisterLiveConsumerCommand,
                FallbackCommand,
                BeginVoiceCommand,
                CommitVoiceCommand,
                CancelVoiceCommand,
                AppendVoiceChunkCommand,
                FinalizeVoiceCommand,
                GetVoiceChunkCommand,
                ReleaseVoiceCommand,
                DismissLiveContextCommand,
                SwitchCommand,
                RetunnelCommand,
                GetTransportStateCommand,
            ),
        ):
            if self._network_handler is None:
                self._send(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._network_handler.handle(cmd, conn)
            return

        if isinstance(
            cmd,
            (
                GetContactsListCommand,
                AddContactCommand,
                RemoveContactCommand,
                RenameContactCommand,
                ClearContactsCommand,
                ClearProfileDbCommand,
                GetHistoryCommand,
                GetRawHistoryCommand,
                ClearHistoryCommand,
                GetMessagesCommand,
                ListRetainedMessagesCommand,
                ClearMessagesCommand,
                DeleteMessageCommand,
                GetInboxCommand,
                MarkReadCommand,
            ),
        ):
            if self._database_handler is None:
                self._send(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._send(conn, self._database_handler.handle(cmd))
            return

        if isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
            if self._system_handler is None:
                self._send(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._send(conn, self._system_handler.handle(cmd))
