"""
Module providing a headless, ephemeral Daemon instance.
Processes offline CLI queries exclusively via IPC without initializing Tor or Network listeners,
enforcing strict Domain-Driven Design by shielding the UI from direct database access.
"""

import socket
import threading
import json
import types
from typing import Dict, Optional, Type

from metor.core import KeyManager, TorManager
from metor.core.api import (
    JsonValue,
    IpcEvent,
    IpcCommand,
    SystemCode,
    ActionErrorEvent,
    GetContactsListCommand,
    AddContactCommand,
    RemoveContactCommand,
    RenameContactCommand,
    ClearContactsCommand,
    ClearProfileDbCommand,
    GetHistoryCommand,
    ClearHistoryCommand,
    GetMessagesCommand,
    ClearMessagesCommand,
    GetInboxCommand,
    MarkReadCommand,
    GetAddressCommand,
    GenerateAddressCommand,
    SetSettingCommand,
    GetSettingCommand,
    SetConfigCommand,
    GetConfigCommand,
    SyncConfigCommand,
)
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.profile import ProfileManager
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.handlers import (
    DatabaseCommandHandler,
    SystemCommandHandler,
    ConfigCommandHandler,
)


class HeadlessDaemon:
    """Lightweight daemon for executing single offline database operations via IPC."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the HeadlessDaemon safely, accepting a password for offline SQLite encryption.

        Args:
            pm (ProfileManager): The active profile configuration.
            password (Optional[str]): The master password required to decrypt local data.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._cm: ContactManager = ContactManager(pm, password)
        self._hm: HistoryManager = HistoryManager(pm, password)
        self._mm: MessageManager = MessageManager(pm, password)

        self._km: KeyManager = KeyManager(pm, password)
        self._tm: TorManager = TorManager(pm, self._km)

        self._config_handler: ConfigCommandHandler = ConfigCommandHandler(self._pm)
        self._db_handler: DatabaseCommandHandler = DatabaseCommandHandler(
            self._pm, self._cm, self._hm, self._mm, lambda: [], lambda e: None
        )
        self._sys_handler: SystemCommandHandler = SystemCommandHandler(
            self._pm, self._tm
        )

        self.port: int = 0
        self._server: Optional[socket.socket] = None
        self._stop_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None

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
            except Exception:
                pass

    def _acceptor(self) -> None:
        """
        Waits for a single client connection, processes it, and shuts down.

        Args:
            None

        Returns:
            None
        """
        if not self._server:
            return

        try:
            self._server.settimeout(Constants.THREAD_POLL_TIMEOUT)
            while not self._stop_event.is_set():
                try:
                    conn, _ = self._server.accept()
                    self._handle_client(conn)
                    break
                except socket.timeout:
                    pass
        except Exception:
            pass

    def _handle_client(self, conn: socket.socket) -> None:
        """
        Reads an IPC command safely from the socket and routes it to the handlers.

        Args:
            conn (socket.socket): The temporary client socket.

        Returns:
            None
        """
        try:
            daemon_ipc_timeout = self._pm.config.get_float(
                'daemon.ipc_timeout'
            )  # Resolves via fallback safely
            conn.settimeout(daemon_ipc_timeout)
            buffer: str = ''
            while not self._stop_event.is_set():
                try:
                    data: bytes = conn.recv(Constants.TCP_BUFFER_SIZE)
                    if not data:
                        break
                    buffer += data.decode('utf-8', errors='ignore')
                    if '\n' in buffer:
                        line: str = buffer.split('\n')[0].strip()
                        cmd_dict: Dict[str, JsonValue] = json.loads(line)
                        cmd: IpcCommand = IpcCommand.from_dict(cmd_dict)
                        self._process_command(cmd, conn)
                        break
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
        except Exception:
            pass

    def _process_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Executes offline database or key queries matching the Daemon domain logic.

        Args:
            cmd (IpcCommand): The parsed IPC command DTO.
            conn (socket.socket): The client socket for returning the response.

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
            self._send(conn, self._config_handler.handle(cmd))
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
                ClearHistoryCommand,
                GetMessagesCommand,
                ClearMessagesCommand,
                GetInboxCommand,
                MarkReadCommand,
            ),
        ):
            self._send(conn, self._db_handler.handle(cmd))
        elif isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
            self._send(conn, self._sys_handler.handle(cmd))
        else:
            self._send(
                conn,
                ActionErrorEvent(action=cmd.action, code=SystemCode.DAEMON_OFFLINE),
            )
