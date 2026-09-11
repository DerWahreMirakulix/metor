"""
Module managing the local Inter-Process Communication (IPC) server.
Handles socket connections between the background Daemon and the Chat UI.
Enforces strict timeouts to prevent socket blockades and uses robust UTF-8 decoding to thwart DoS.
"""

import os
import socket
import threading
import json
import secrets
from typing import List, Callable, Dict, Optional, Iterable

from metor.core.api import (
    EventType,
    IpcCommand,
    IpcEvent,
    JsonValue,
    create_event,
    request_context,
    stamp_request_id,
)
from metor.data import SettingKey
from metor.data.profile import ProfileManager
from metor.utils import Constants
from metor.core.daemon.managed.writer import BoundedSocketWriter, FrameQueueFull


class IpcServer:
    """Manages the local IPC server socket for UI-Daemon communication."""

    @staticmethod
    def _extract_request_id(payload: JsonValue) -> Optional[str]:
        """
        Extracts one request correlation identifier from a raw JSON payload.

        Args:
            payload (JsonValue): The decoded JSON payload.

        Returns:
            Optional[str]: The request identifier when present and well-typed.
        """
        if not isinstance(payload, dict):
            return None

        request_id: JsonValue = payload.get('request_id')
        return request_id if isinstance(request_id, str) else None

    @staticmethod
    def _build_client_limit_event(max_clients: int) -> IpcEvent:
        """
        Creates one IPC saturation event for a newly rejected client socket.

        Args:
            max_clients (int): The configured daemon IPC client ceiling.

        Returns:
            IpcEvent: The typed rejection event.
        """
        return create_event(
            EventType.IPC_CLIENT_LIMIT_REACHED,
            {'max_clients': max_clients},
        )

    def __init__(
        self,
        pm: ProfileManager,
        command_callback: Callable[[IpcCommand, socket.socket], None],
        disconnect_callback: Optional[Callable[[socket.socket], None]] = None,
        error_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Initializes the IPC Server.

        Args:
            pm (ProfileManager): To store and retrieve the active daemon port.
            command_callback (Callable): The function to call when a valid command arrives.
            disconnect_callback (Optional[Callable]): Hook to clean up socket states externally.
            error_callback (Optional[Callable[[str], None]]): Hook to surface
                unexpected runtime errors without terminating the acceptor.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._command_callback: Callable[[IpcCommand, socket.socket], None] = (
            command_callback
        )
        self._disconnect_callback: Optional[Callable[[socket.socket], None]] = (
            disconnect_callback
        )
        self._error_callback: Optional[Callable[[str], None]] = error_callback

        self._clients: List[socket.socket] = []
        self._lock: threading.Lock = threading.Lock()
        self._client_write_locks: Dict[socket.socket, threading.Lock] = {}
        self._client_writers: Dict[socket.socket, BoundedSocketWriter] = {}
        self._revision_lock: threading.Lock = threading.Lock()
        self._state_revision: int = 0
        self._epoch: str = secrets.token_hex(Constants.UUID_MSG_BYTES)
        self._stop_flag: threading.Event = threading.Event()
        self.port: Optional[int] = None
        self._server: Optional[socket.socket] = None

    def _report_internal_error(self, message: str) -> None:
        """
        Emits one best-effort runtime error callback.

        Args:
            message (str): The console-safe runtime error message.

        Returns:
            None
        """
        if self._error_callback is None:
            return

        try:
            self._error_callback(message)
        except Exception:
            pass

    def has_active_clients(self) -> bool:
        """
        Checks if there are currently active UI clients connected to the daemon.

        Args:
            None

        Returns:
            bool: True if headful (clients > 0), False if headless.
        """
        with self._lock:
            return len(self._clients) > 0

    def active_clients(self) -> set[socket.socket]:
        """Returns a lock-safe snapshot of attached IPC sockets."""
        with self._lock:
            return set(self._clients)

    def start(self) -> None:
        """
        Starts the local IPC server in a background thread.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.clear()
        server: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        static_port: Optional[int] = self._pm.get_static_port()
        bind_port: int = static_port if static_port else 0

        server.bind((Constants.LOCALHOST, bind_port))
        server.listen(Constants.SERVER_BACKLOG)

        self._server = server
        self.port = server.getsockname()[1]
        self._pm.set_daemon_port(self.port, os.getpid())

        threading.Thread(target=self._acceptor, daemon=True).start()

    def stop(self) -> None:
        """
        Stops the IPC server and gracefully disconnects all active UIs.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        with self._lock:
            clients: List[socket.socket] = list(self._clients)
            self._clients.clear()
            self._client_write_locks.clear()
            writers = list(self._client_writers.values())
            self._client_writers.clear()
        for writer in writers:
            writer.close()
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    def broadcast(self, event: IpcEvent) -> None:
        """
        Sends an event payload to all currently connected UI clients.

        Args:
            event (IpcEvent): The DTO event to broadcast.

        Returns:
            None
        """
        self.broadcast_to(event)

    def broadcast_to(
        self,
        event: IpcEvent,
        recipients: Optional[Iterable[socket.socket]] = None,
    ) -> None:
        """
        Sends one event payload to a subset of currently connected UI clients.

        Args:
            event (IpcEvent): The DTO event to broadcast.
            recipients (Optional[Iterable[socket.socket]]): Optional recipient subset.

        Returns:
            None
        """
        stamp_request_id(event)
        self._stamp_revision(event)
        msg: bytes = (event.to_json() + '\n').encode('utf-8')
        with self._lock:
            clients: List[socket.socket] = list(self._clients)

        if recipients is not None:
            allowed_clients: set[socket.socket] = set(recipients)
            clients = [client for client in clients if client in allowed_clients]

        for client in clients:
            try:
                self._enqueue_client_frame(client, msg)
            except (ConnectionError, FrameQueueFull):
                self._drop_client(client)

    def send_to(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Sends an event payload specifically to one connected client.

        Args:
            conn (socket.socket): The target socket connection.
            event (IpcEvent): The DTO event to send.

        Returns:
            None
        """
        stamp_request_id(event)
        self._stamp_revision(event)
        msg: bytes = (event.to_json() + '\n').encode('utf-8')
        try:
            self._enqueue_client_frame(conn, msg)
        except (ConnectionError, FrameQueueFull):
            self._drop_client(conn)

    def _enqueue_client_frame(self, conn: socket.socket, msg: bytes) -> None:
        """Queues one client frame without holding daemon state across I/O."""
        if not isinstance(conn, socket.socket):
            with self._lock:
                write_lock = self._client_write_locks.setdefault(conn, threading.Lock())
            with write_lock:
                conn.sendall(msg)
            return
        with self._lock:
            writer = self._client_writers.get(conn)
            if writer is None:
                writer = BoundedSocketWriter(
                    conn,
                    capacity=Constants.IPC_WRITER_QUEUE_FRAMES,
                    on_failure=lambda failed, _exc: self._drop_client(failed),
                    on_exit=lambda exited: self._writer_exited(conn, exited),
                )
                self._client_writers[conn] = writer
        writer.enqueue(msg)

    def _writer_exited(self, conn: socket.socket, writer: BoundedSocketWriter) -> None:
        """Releases an idle IPC writer from the bounded inventory."""
        with self._lock:
            if self._client_writers.get(conn) is writer:
                self._client_writers.pop(conn, None)

    def _drop_client(self, conn: socket.socket) -> None:
        """Disconnects one failed or saturated client and releases its writer."""
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
            self._client_write_locks.pop(conn, None)
            writer = self._client_writers.pop(conn, None)
        if writer is not None:
            writer.close()
        else:
            try:
                conn.close()
            except Exception:
                pass

    def _stamp_revision(self, event: IpcEvent) -> None:
        """Assigns one monotonic daemon event revision exactly once.

        Args:
            event (IpcEvent): Event entering the IPC stream.

        Returns:
            None
        """
        with self._revision_lock:
            if getattr(event, 'revision', None) is None:
                self._state_revision += 1
                event.revision = self._state_revision
            if getattr(event, 'epoch', None) is None and hasattr(event, 'epoch'):
                event.epoch = self._epoch

    def current_epoch(self) -> str:
        """Returns the unguessable sequence epoch for this daemon process.

        Args:
            None

        Returns:
            str: Stable epoch for the current IPC server lifetime.
        """
        return self._epoch

    def current_revision(self) -> int:
        """Returns the latest assigned daemon event revision.

        Args:
            None

        Returns:
            int: Monotonic event revision.
        """
        with self._revision_lock:
            return self._state_revision

    def _reject_client_limit(self, conn: socket.socket, max_clients: int) -> None:
        """
        Rejects one freshly accepted IPC socket when the daemon is already saturated.

        Args:
            conn (socket.socket): The newly accepted socket.
            max_clients (int): The configured daemon IPC client ceiling.

        Returns:
            None
        """
        event = self._build_client_limit_event(max_clients)
        stamp_request_id(event)
        self._stamp_revision(event)
        try:
            conn.sendall((event.to_json() + '\n').encode('utf-8'))
            conn.close()
        except Exception:
            pass

    def _acceptor(self) -> None:
        """
        Target loop for accepting new incoming UI connections.

        Args:
            None

        Returns:
            None
        """
        server: Optional[socket.socket] = self._server
        if not server:
            return

        daemon_ipc_timeout: float = self._pm.config.get_float(
            SettingKey.DAEMON_IPC_TIMEOUT
        )

        while not self._stop_flag.is_set():
            try:
                server.settimeout(Constants.THREAD_POLL_TIMEOUT)
                conn, _ = server.accept()
                conn.settimeout(daemon_ipc_timeout)
                max_clients: int = self._pm.config.get_int(SettingKey.MAX_IPC_CLIENTS)

                with self._lock:
                    if len(self._clients) >= max_clients:
                        reject_conn: Optional[socket.socket] = conn
                    else:
                        reject_conn = None

                if reject_conn is not None:
                    self._reject_client_limit(reject_conn, max_clients)
                    continue

                try:
                    handler_thread: threading.Thread = threading.Thread(
                        target=self._handler,
                        args=(conn,),
                        daemon=True,
                    )
                    with self._lock:
                        self._clients.append(conn)
                    handler_thread.start()
                except Exception:
                    with self._lock:
                        if conn in self._clients:
                            self._clients.remove(conn)
                        self._client_write_locks.pop(conn, None)
                        writer = self._client_writers.pop(conn, None)
                    if writer is not None:
                        writer.close()
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._report_internal_error(
                        'IPC acceptor failed to start a client handler thread. Continuing.'
                    )
                    continue
            except socket.timeout:
                continue
            except OSError:
                if self._stop_flag.is_set() or self._server is None:
                    break
                self._report_internal_error(
                    'IPC acceptor hit an OS-level runtime error. Continuing.'
                )
                continue
            except Exception:
                self._report_internal_error(
                    'IPC acceptor hit an unexpected runtime error. Continuing.'
                )
                continue

    def _handler(self, conn: socket.socket) -> None:
        """
        Target loop for receiving and parsing commands from a specific UI.
        Enforces read timeouts to prevent hanging threads if the UI crashes abruptly.
        Utilizes byte buffering to prevent UTF-8 fragmentation DoS.

        Args:
            conn (socket.socket): The established client socket connection.

        Returns:
            None
        """
        daemon_ipc_timeout = self._pm.config.get_float(SettingKey.DAEMON_IPC_TIMEOUT)
        conn.settimeout(daemon_ipc_timeout)
        buffer: bytearray = bytearray()
        try:
            while not self._stop_flag.is_set():
                try:
                    data: bytes = conn.recv(Constants.TCP_BUFFER_SIZE)
                    if not data:
                        break

                    buffer.extend(data)

                    if len(buffer) > Constants.MAX_IPC_BYTES:
                        self.send_to(conn, create_event(EventType.UNKNOWN_COMMAND))
                        break

                    while b'\n' in buffer:
                        line_bytes, _, rest = buffer.partition(b'\n')
                        buffer = bytearray(rest)
                        request_id: Optional[str] = None

                        try:
                            line: str = line_bytes.decode('utf-8').strip()
                        except UnicodeDecodeError:
                            self.send_to(conn, create_event(EventType.UNKNOWN_COMMAND))
                            continue

                        if not line:
                            continue
                        try:
                            cmd_dict: Dict[str, JsonValue] = json.loads(line)
                            request_id = self._extract_request_id(cmd_dict)
                            cmd: IpcCommand = IpcCommand.from_dict(cmd_dict)
                        except Exception:
                            self.send_to(
                                conn,
                                create_event(
                                    EventType.UNKNOWN_COMMAND,
                                    {'request_id': request_id}
                                    if request_id is not None
                                    else None,
                                ),
                            )
                            continue

                        try:
                            with request_context(cmd.request_id):
                                self._command_callback(cmd, conn)
                        except Exception:
                            self.send_to(
                                conn,
                                create_event(
                                    EventType.INTERNAL_ERROR,
                                    {'request_id': cmd.request_id}
                                    if cmd.request_id is not None
                                    else None,
                                ),
                            )
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
                self._client_write_locks.pop(conn, None)
                writer = self._client_writers.pop(conn, None)
            if writer is not None:
                writer.close()
            else:
                try:
                    conn.close()
                except Exception:
                    pass
            if self._disconnect_callback:
                self._disconnect_callback(conn)
