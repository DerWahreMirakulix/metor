"""Command-dispatch helpers for the ephemeral headless daemon."""

import socket
from typing import Optional

from metor.core.api import (
    AddContactCommand,
    ClearContactsCommand,
    ClearHistoryCommand,
    ClearMessagesCommand,
    ClearProfileDbCommand,
    EventType,
    GenerateAddressCommand,
    GetAddressCommand,
    GetConfigCommand,
    GetContactsListCommand,
    GetHistoryCommand,
    GetInboxCommand,
    GetMessagesCommand,
    GetRawHistoryCommand,
    GetSettingCommand,
    IpcCommand,
    IpcEvent,
    MarkReadCommand,
    RemoveContactCommand,
    RenameContactCommand,
    SetConfigCommand,
    SetSettingCommand,
    SyncConfigCommand,
    create_event,
)
from metor.core.daemon import InvalidMasterPasswordError, verify_master_password
from metor.data import DatabaseCorruptedError

# Local Package Imports
from metor.core.daemon.headless.protocols import HeadlessDaemonProtocol


def validate_password(daemon: HeadlessDaemonProtocol) -> Optional[IpcEvent]:
    """
    Validates the configured master password before opening encrypted storage.

    Args:
        daemon (HeadlessDaemonProtocol): The owning headless daemon instance.

    Returns:
        Optional[IpcEvent]: An error event when validation fails, otherwise None.
    """
    if not daemon._pm.supports_password_auth():
        return None

    if daemon._password is None:
        return create_event(EventType.INVALID_PASSWORD)

    try:
        verify_master_password(daemon._km)
    except InvalidMasterPasswordError:
        return create_event(EventType.INVALID_PASSWORD)

    return None


def process_command(
    daemon: HeadlessDaemonProtocol,
    cmd: IpcCommand,
    conn: socket.socket,
) -> None:
    """
    Routes a parsed headless IPC command to the matching offline handler.

    Args:
        daemon (HeadlessDaemonProtocol): The owning headless daemon instance.
        cmd (IpcCommand): The parsed IPC command DTO.
        conn (socket.socket): The connected local IPC socket.

    Returns:
        None
    """
    if isinstance(
        cmd,
        (
            SetSettingCommand,
            GetSettingCommand,
            SetConfigCommand,
            GetConfigCommand,
            SyncConfigCommand,
        ),
    ):
        daemon._send(conn, daemon._config_handler.handle(cmd))
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
            ClearMessagesCommand,
            GetInboxCommand,
            MarkReadCommand,
        ),
    ):
        password_error: Optional[IpcEvent] = validate_password(daemon)
        if password_error is not None:
            daemon._send(conn, password_error)
            return

        try:
            daemon._send(conn, daemon._db_handler.handle(cmd))
        except DatabaseCorruptedError:
            daemon._send(conn, create_event(EventType.DB_CORRUPTED))
        return

    if isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
        password_error = validate_password(daemon)
        if password_error is not None:
            daemon._send(conn, password_error)
            return

        daemon._send(conn, daemon._sys_handler.handle(cmd))
        return

    daemon._send(conn, create_event(EventType.DAEMON_OFFLINE))
