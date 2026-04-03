"""Socket helpers for the ephemeral headless daemon IPC server."""

import json
import socket
from typing import Any, Dict

from metor.core.api import EventType, IpcCommand, JsonValue, create_event
from metor.data import SettingKey
from metor.utils import Constants


def run_acceptor(daemon: Any) -> None:
    """
    Waits for a single local client and delegates socket processing.

    Args:
        daemon (Any): The owning headless daemon instance.

    Returns:
        None
    """
    if not daemon._server:
        return

    daemon._server.settimeout(Constants.THREAD_POLL_TIMEOUT)
    while not daemon._stop_event.is_set():
        try:
            conn, _ = daemon._server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        daemon._handle_client(conn)
        break


def handle_client(daemon: Any, conn: socket.socket) -> None:
    """
    Reads one newline-delimited IPC frame and routes the parsed command.

    Args:
        daemon (Any): The owning headless daemon instance.
        conn (socket.socket): The connected local IPC socket.

    Returns:
        None
    """
    try:
        daemon_ipc_timeout = daemon._pm.config.get_float(SettingKey.DAEMON_IPC_TIMEOUT)
        conn.settimeout(daemon_ipc_timeout)
        buffer: bytearray = bytearray()
        while not daemon._stop_event.is_set():
            try:
                data: bytes = conn.recv(Constants.TCP_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            if not data:
                break

            buffer.extend(data)
            if len(buffer) > Constants.MAX_IPC_BYTES:
                daemon._send(conn, create_event(EventType.UNKNOWN_COMMAND))
                break

            if b'\n' not in buffer:
                continue

            line_bytes, _, _ = buffer.partition(b'\n')
            line: str = line_bytes.decode('utf-8', errors='ignore').strip()
            try:
                cmd_dict: Dict[str, JsonValue] = json.loads(line)
                cmd: IpcCommand = IpcCommand.from_dict(cmd_dict)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                daemon._send(conn, create_event(EventType.UNKNOWN_COMMAND))
                break

            try:
                daemon._process_command(cmd, conn)
            except Exception:
                daemon._send(conn, create_event(EventType.INTERNAL_ERROR))
            break
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass
