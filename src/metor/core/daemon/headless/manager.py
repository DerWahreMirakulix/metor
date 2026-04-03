"""Ephemeral daemon manager for offline IPC-only CLI operations."""

import socket
import threading
import types
from functools import cached_property
from typing import Optional, Type

from metor.core import KeyManager, TorManager
from metor.core.api import IpcCommand, IpcEvent
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.profile import ProfileManager
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    SystemCommandHandler,
)
from metor.core.daemon.headless.dispatch import process_command, validate_password
from metor.core.daemon.headless.server import handle_client, run_acceptor


class HeadlessDaemon:
    """Lightweight daemon for executing single offline database operations via IPC."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the HeadlessDaemon safely, accepting a password for offline SQLite encryption.
        Defers database instantiation until explicitly required by an incoming command.

        Args:
            pm (ProfileManager): The active profile configuration.
            password (Optional[str]): The master password required to decrypt local data.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._password: Optional[str] = password

        self.port: int = 0
        self._server: Optional[socket.socket] = None
        self._stop_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @cached_property
    def _cm(self) -> ContactManager:
        """
        Lazily loads the ContactManager.

        Args:
            None

        Returns:
            ContactManager: The active instance.
        """
        return ContactManager(self._pm, self._password)

    @cached_property
    def _hm(self) -> HistoryManager:
        """
        Lazily loads the HistoryManager.

        Args:
            None

        Returns:
            HistoryManager: The active instance.
        """
        return HistoryManager(self._pm, self._password)

    @cached_property
    def _mm(self) -> MessageManager:
        """
        Lazily loads the MessageManager.

        Args:
            None

        Returns:
            MessageManager: The active instance.
        """
        return MessageManager(self._pm, self._password)

    @cached_property
    def _km(self) -> KeyManager:
        """
        Lazily loads the KeyManager.

        Args:
            None

        Returns:
            KeyManager: The active instance.
        """
        return KeyManager(self._pm, self._password)

    @cached_property
    def _tm(self) -> TorManager:
        """
        Lazily loads the TorManager.

        Args:
            None

        Returns:
            TorManager: The active instance.
        """
        return TorManager(self._pm, self._km)

    @cached_property
    def _config_handler(self) -> ConfigCommandHandler:
        """
        Lazily loads the ConfigCommandHandler.

        Args:
            None

        Returns:
            ConfigCommandHandler: The active instance.
        """
        return ConfigCommandHandler(self._pm)

    @cached_property
    def _db_handler(self) -> DatabaseCommandHandler:
        """
        Lazily loads the DatabaseCommandHandler.

        Args:
            None

        Returns:
            DatabaseCommandHandler: The active instance.
        """
        return DatabaseCommandHandler(
            self._pm,
            self._cm,
            self._hm,
            self._mm,
            lambda: [],
            lambda e: None,
        )

    @cached_property
    def _sys_handler(self) -> SystemCommandHandler:
        """
        Lazily loads the SystemCommandHandler.

        Args:
            None

        Returns:
            SystemCommandHandler: The active instance.
        """
        return SystemCommandHandler(self._pm, self._tm)

    def __enter__(self) -> 'HeadlessDaemon':
        """
        Context manager entry to start the headless IPC server dynamically.

        Args:
            None

        Returns:
            HeadlessDaemon: The active instance.
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        """
        Context manager exit to ensure safe shutdown and port release.

        Args:
            exc_type (Optional[Type[BaseException]]): Exception type if raised.
            exc_val (Optional[BaseException]): Exception value if raised.
            exc_tb (Optional[types.TracebackType]): Traceback if raised.

        Returns:
            None
        """
        self.stop()

    def start(self) -> None:
        """
        Binds a random local port and starts the background listener thread.

        Args:
            None

        Returns:
            None
        """
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind((Constants.LOCALHOST, 0))
        self._server.listen(Constants.SERVER_BACKLOG_HEADLESS)
        self.port = self._server.getsockname()[1]

        self._thread = threading.Thread(target=self._acceptor, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Signals the listener to stop and closes the ephemeral server socket.

        Args:
            None

        Returns:
            None
        """
        self._stop_event.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass

    def _acceptor(self) -> None:
        """
        Waits for a single client connection, processes it, and shuts down.

        Args:
            None

        Returns:
            None
        """
        run_acceptor(self)

    def _handle_client(self, conn: socket.socket) -> None:
        """
        Reads an IPC command safely from the socket and routes it to the handlers.

        Args:
            conn (socket.socket): The temporary client socket.

        Returns:
            None
        """
        handle_client(self, conn)

    def _send(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Serializes and pushes the command response back to the client UI.

        Args:
            conn (socket.socket): The client socket.
            event (IpcEvent): The event payload.

        Returns:
            None
        """
        try:
            msg: bytes = (event.to_json() + '\n').encode('utf-8')
            conn.sendall(msg)
        except OSError:
            pass

    def _validate_password(self) -> Optional[IpcEvent]:
        """
        Validates the provided master password before opening encrypted databases.

        Args:
            None

        Returns:
            Optional[IpcEvent]: An error event when validation fails, otherwise None.
        """
        return validate_password(self)

    def _process_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Executes offline database or key queries matching the Daemon domain logic.

        Args:
            cmd (IpcCommand): The parsed IPC command DTO.
            conn (socket.socket): The client socket for returning the response.

        Returns:
            None
        """
        process_command(self, cmd, conn)
