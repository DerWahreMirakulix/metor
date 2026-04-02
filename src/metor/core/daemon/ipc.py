"""
Module managing the local Inter-Process Communication (IPC) server.
Handles socket connections between the background Daemon and the Chat UI.
Enforces strict timeouts to prevent socket blockades and uses robust UTF-8 decoding to thwart DoS.
"""

import os
import socket
import threading
import json
from typing import List, Callable, Dict, Optional

from metor.core.api import IpcCommand, IpcEvent, JsonValue, EventType, create_event
from metor.data import SettingKey
from metor.data.profile import ProfileManager
from metor.utils import Constants


class IpcServer:
    """Manages the local IPC server socket for UI-Daemon communication."""

    def __init__(
        self,
        pm: ProfileManager,
        command_callback: Callable[[IpcCommand, socket.socket], None],
        disconnect_callback: Optional[Callable[[socket.socket], None]] = None,
    ) -> None:
        """
        Initializes the IPC Server.

        Args:
            pm (ProfileManager): To store and retrieve the active daemon port.
            command_callback (Callable): The function to call when a valid command arrives.
            disconnect_callback (Optional[Callable]): Hook to clean up socket states externally.

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

        self._clients: List[socket.socket] = []
        self._lock: threading.Lock = threading.Lock()
        self._stop_flag: threading.Event = threading.Event()
        self.port: Optional[int] = None
        self._server: Optional[socket.socket] = None

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
            for c in self._clients:
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()

    def broadcast(self, event: IpcEvent) -> None:
        """
        Sends an event payload to all currently connected UI clients.

        Args:
            event (IpcEvent): The DTO event to broadcast.

        Returns:
            None
        """
        msg: bytes = (event.to_json() + '\n').encode('utf-8')
        dead_clients: List[socket.socket] = []

        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(msg)
                except Exception:
                    dead_clients.append(client)
            for dc in dead_clients:
                self._clients.remove(dc)

    def send_to(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Sends an event payload specifically to one connected client.

        Args:
            conn (socket.socket): The target socket connection.
            event (IpcEvent): The DTO event to send.

        Returns:
            None
        """
        try:
            msg: bytes = (event.to_json() + '\n').encode('utf-8')
            conn.sendall(msg)
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

        while not self._stop_flag.is_set():
            try:
                server.settimeout(Constants.THREAD_POLL_TIMEOUT)
                conn, _ = server.accept()
                with self._lock:
                    self._clients.append(conn)
                threading.Thread(
                    target=self._handler, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_flag.is_set():
                    break
                break
            except Exception:
                break

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

                        line: str = line_bytes.decode('utf-8', errors='ignore').strip()
                        if not line:
                            continue
                        try:
                            cmd_dict: Dict[str, JsonValue] = json.loads(line)
                            cmd: IpcCommand = IpcCommand.from_dict(cmd_dict)
                            self._command_callback(cmd, conn)
                        except Exception:
                            self.send_to(conn, create_event(EventType.UNKNOWN_COMMAND))
                except socket.timeout:
                    continue
        except Exception:
            pass
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try:
                conn.close()
            except Exception:
                pass
            if self._disconnect_callback:
                self._disconnect_callback(conn)
