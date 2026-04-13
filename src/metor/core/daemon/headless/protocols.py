"""Protocol definitions for the ephemeral headless daemon helpers."""

import socket
import threading
from typing import Optional, Protocol

from metor.core import KeyManager
from metor.core.api import IpcCommand, IpcEvent
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    ProfileCommandHandler,
    SystemCommandHandler,
)
from metor.data.profile import ProfileManager


class HeadlessDaemonProtocol(Protocol):
    """Structural type for the headless daemon helper functions."""

    _server: Optional[socket.socket]
    _stop_event: threading.Event
    _pm: ProfileManager
    _password: Optional[str]

    @property
    def _km(self) -> KeyManager:
        """
        Returns the key manager bound to the ephemeral headless runtime.

        Args:
            None

        Returns:
            KeyManager: The active key manager instance.
        """
        ...

    @property
    def _config_handler(self) -> ConfigCommandHandler:
        """
        Returns the configuration handler used by the headless runtime.

        Args:
            None

        Returns:
            ConfigCommandHandler: The active configuration handler.
        """
        ...

    @property
    def _db_handler(self) -> DatabaseCommandHandler:
        """
        Returns the database handler used for offline IPC requests.

        Args:
            None

        Returns:
            DatabaseCommandHandler: The active database handler.
        """
        ...

    @property
    def _sys_handler(self) -> SystemCommandHandler:
        """
        Returns the system handler used for offline address operations.

        Args:
            None

        Returns:
            SystemCommandHandler: The active system handler.
        """
        ...

    @property
    def _profile_handler(self) -> ProfileCommandHandler:
        """
        Returns the profile handler used for local lifecycle operations.

        Args:
            None

        Returns:
            ProfileCommandHandler: The active profile handler.
        """
        ...

    def _handle_client(self, conn: socket.socket) -> None:
        """
        Processes one accepted headless IPC client socket.

        Args:
            conn (socket.socket): The accepted local IPC socket.

        Returns:
            None
        """
        ...

    def _send(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Sends one IPC event back to the connected headless client.

        Args:
            conn (socket.socket): The connected local IPC socket.
            event (IpcEvent): The event to serialize and send.

        Returns:
            None
        """
        ...

    def _process_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Routes one parsed IPC command within the headless runtime.

        Args:
            cmd (IpcCommand): The parsed IPC command DTO.
            conn (socket.socket): The connected local IPC socket.

        Returns:
            None
        """
        ...
