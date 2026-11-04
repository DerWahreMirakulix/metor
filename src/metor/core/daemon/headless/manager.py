"""Ephemeral daemon manager for offline IPC-only CLI operations."""

import socket
import threading
import types
from contextlib import ExitStack
from functools import cached_property
from typing import Optional, Type

from metor.core.api import EventType, IpcCommand, IpcEvent, create_event
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data import (
    ContactManager,
    HistoryManager,
    MessageManager,
    Settings,
    SqlManager,
)
from metor.data.blob import (
    BlobLifecycle,
    BlobStore,
    EncryptedBlobStore,
    PlaintextBlobStore,
)
from metor.data.profile import ProfileManager, offline_profile_guard
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    ProfileCommandHandler,
    SystemCommandHandler,
)
from metor.core.daemon.headless.dispatch import (
    is_profile_lifecycle_command,
    process_command,
    validate_password,
)
from metor.core.daemon.headless.server import handle_client


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

        self._client: Optional[socket.socket] = None
        self._server: Optional[socket.socket] = None
        self._stop_event: threading.Event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cleanup_failed: threading.Event = threading.Event()
        self._sensitive_state_released = False
        self._runtime_guard: Optional[ExitStack] = None

    @cached_property
    def _cm(self) -> ContactManager:
        """
        Lazily loads the ContactManager.

        Args:
            None

        Returns:
            ContactManager: The active instance.
        """
        return ContactManager(self._pm, self._km.get_database_key())

    @cached_property
    def _hm(self) -> HistoryManager:
        """
        Lazily loads the HistoryManager.

        Args:
            None

        Returns:
            HistoryManager: The active instance.
        """
        return HistoryManager(self._pm, self._km.get_database_key())

    @cached_property
    def _mm(self) -> MessageManager:
        """
        Lazily loads the MessageManager.

        Args:
            None

        Returns:
            MessageManager: The active instance.
        """
        return MessageManager(self._pm, self._km.get_database_key())

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
    def _blobs(self) -> BlobStore:
        """Lazily opens the profile object store for explicit payload cleanup.

        Args:
            None

        Returns:
            BlobStore: The resulting value.
        """
        if self._pm.uses_encrypted_storage():
            return EncryptedBlobStore(
                self._pm.paths.get_persistent_blob_dir(),
                self._pm.paths.get_temporary_blob_dir(),
                self._km.get_blob_key(),
            )
        return PlaintextBlobStore(
            self._pm.paths.get_persistent_blob_dir(),
            self._pm.paths.get_temporary_blob_dir(),
        )

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
            delete_persistent_blob_cb=lambda blob_id: self._blobs.delete(
                blob_id, BlobLifecycle.PERSISTENT
            ),
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

    @cached_property
    def _profile_handler(self) -> ProfileCommandHandler:
        """
        Lazily loads the ProfileCommandHandler.

        Args:
            None

        Returns:
            ProfileCommandHandler: The active instance.
        """
        return ProfileCommandHandler()

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
        """Starts one private connected IPC channel without a listening endpoint.

        The channel is created in the calling process and is never published in
        profile metadata. Possession of its client socket is the authorization
        boundary for operations using the caller's supplied profile password.

        Args:
            None

        Returns:
            None
        """
        if self._thread is not None or self._stop_event.is_set():
            raise RuntimeError('Headless daemon cannot be restarted.')
        try:
            self._server, self._client = socket.socketpair()
            self._server.set_inheritable(False)
            self._client.set_inheritable(False)
            self._thread = threading.Thread(target=self._serve, daemon=True)
            self._thread.start()
        except BaseException:
            self._stop_event.set()
            for endpoint in (self._server, self._client):
                if endpoint is not None:
                    endpoint.close()
            self._server = self._client = None
            self._thread = None
            self._release_sensitive_state()
            raise

    @property
    def client_socket(self) -> socket.socket:
        """Returns the private caller-owned side of this single-command channel.

        Returns:
            socket.socket: Connected non-inheritable endpoint, valid until stop.

        Raises:
            RuntimeError: If the channel has not started or has already stopped.
        """
        if self._client is None or self._stop_event.is_set():
            raise RuntimeError('Headless IPC channel is unavailable.')
        return self._client

    def stop(self) -> None:
        """
        Stops private IPC and confirms worker exit before releasing runtime keys.

        Args:
            None

        Returns:
            None
        """
        self._stop_event.set()
        for endpoint in (self._client, self._server):
            if endpoint is None:
                continue
            try:
                endpoint.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            endpoint.close()
        if self._thread is not None:
            self._thread.join(Constants.HEADLESS_SHUTDOWN_TIMEOUT_SEC)
            if self._thread.is_alive():
                raise RuntimeError('Headless IPC worker did not stop in time.')
        self._client = self._server = None
        self._release_sensitive_state()
        if self._cleanup_failed.is_set():
            raise RuntimeError('Headless runtime cleanup did not complete safely.')

    def _release_sensitive_state(self) -> None:
        """Releases credential references only after command execution has ended."""
        if self._sensitive_state_released:
            return
        self._cleanup_failed.clear()
        try:
            if any(name in self.__dict__ for name in ('_cm', '_hm', '_mm')):
                SqlManager.close_connection(self._pm.paths.get_db_file())
        except Exception:
            self._cleanup_failed.set()
        try:
            if '_blobs' in self.__dict__:
                self._blobs.close()
        except Exception:
            self._cleanup_failed.set()
        try:
            if '_km' in self.__dict__:
                self._km.clear_sensitive_state()
        except Exception:
            self._cleanup_failed.set()
        finally:
            self._password = None
        if not self._cleanup_failed.is_set():
            self._sensitive_state_released = True
            if self._runtime_guard is not None:
                self._runtime_guard.close()
                self._runtime_guard = None

    def _serve(self) -> None:
        """Processes only the preconnected private client and releases its secrets.

        Args:
            None

        Returns:
            None
        """
        try:
            if self._server is not None:
                self._handle_client(self._server)
        finally:
            self._release_sensitive_state()

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
        if is_profile_lifecycle_command(cmd):
            process_command(self, cmd, conn)
            return
        guard = ExitStack()
        offline = guard.enter_context(offline_profile_guard(self._pm.paths))
        self._runtime_guard = guard
        try:
            if not offline or self._pm.is_daemon_running() or not self._pm.exists():
                self._send(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            Settings.validate_integrity()
            self._pm.validate_integrity()
            process_command(self, cmd, conn)
        finally:
            # Failed cleanup retains the gate for a safe retry from stop. Once
            # released, later calls must not close a subsequent runtime's pool.
            self._release_sensitive_state()
