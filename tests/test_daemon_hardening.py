"""Targeted regression tests for daemon hardening around IPC and live transport."""

# ruff: noqa: E402

import base64
import hashlib
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from typing import Any, Optional, cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import nacl.bindings

from metor.core.api import (
    AckEvent,
    AutoFallbackQueuedEvent,
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionConnectingEvent,
    ConnectionOrigin,
    ConnectedEvent,
    EventType,
    FallbackSuccessEvent,
    InitCommand,
    IpcEvent,
    RuntimeErrorCode,
    SendDropCommand,
    SelfDestructCommand,
    UnlockCommand,
    create_event,
    request_context,
)
from metor.core import TorManager
from metor.core.key import KeyManager
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.factory import (
    PlaintextLockedDaemonError,
    create_managed_daemon,
)
from metor.core.daemon.managed.handlers import NetworkCommandHandler
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.daemon.managed.status import DaemonStatus
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.network.controller.retunnel import (
    ConnectionControllerRetunnelMixin,
)
from metor.core.daemon.managed.network.listener import InboundListener
from metor.core.daemon.managed.network.controller.session.connect import (
    connect_to as connect_to_helper,
)
from metor.core.daemon.managed.network.controller.session.manager import (
    ConnectionControllerSessionMixin,
)
from metor.core.daemon.managed.network.controller.session.protocols import (
    ConnectControllerProtocol,
)
from metor.core.daemon.managed.network.controller.session.terminate import (
    disconnect as disconnect_helper,
)
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.receiver import StreamReceiver
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.state import (
    PendingConnectionReason,
    StateTracker,
)
from metor.core.daemon.managed.outbox import OutboxWorker
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.data import (
    ContactManager,
    HistoryEvent,
    HistoryManager,
    MessageManager,
    MessageType,
    SettingKey,
)
from metor.data.profile import ProfileManager
from metor.data.profile.config import Config
from metor.ui.chat.ipc import IpcClient
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.theme import Theme
from metor.utils import Constants


class _DummyConfig:
    """
    Provides a dummy config test double.
    """

    def get_bool(self, _key: Any) -> bool:
        """
        Returns bool for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            bool: The computed return value.
        """

        return True

    def get_int(self, _key: Any) -> int:
        """
        Returns int for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            int: The computed return value.
        """

        return 1

    def get_float(self, _key: Any) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            float: The computed return value.
        """

        return 0.2


class _DropQuotaConfig(_DummyConfig):
    """
    Provides a drop quota config helper for test scenarios.
    """

    def __init__(self, unread_drop_limit: int) -> None:
        """
        Initializes the drop quota config helper.

        Args:
            unread_drop_limit (int): The unread drop limit.

        Returns:
            None
        """

        self._unread_drop_limit: int = unread_drop_limit

    def get_int(self, key: Any) -> int:
        """
        Returns int for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            int: The computed return value.
        """

        if key is SettingKey.MAX_UNSEEN_DROP_MSGS:
            return self._unread_drop_limit
        return super().get_int(key)


class _DummyProfileManager:
    """
    Provides a dummy profile manager test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy profile manager helper.

        Args:
            None

        Returns:
            None
        """

        self.config: _DummyConfig = _DummyConfig()
        self.initialized: bool = False

    def initialize(self) -> None:
        """
        Executes initialize for the test scenario.

        Args:
            None

        Returns:
            None
        """

        self.initialized = True

    def uses_plaintext_storage(self) -> bool:
        """
        Reports whether the helper uses plaintext storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False

    def uses_encrypted_storage(self) -> bool:
        """
        Reports whether the helper uses encrypted storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return True

    def get_static_port(self) -> None:
        """
        Returns static port for the test scenario.

        Args:
            None

        Returns:
            None
        """

        return None

    def set_daemon_port(self, _port: int, _pid: int) -> None:
        """
        Stores daemon port for the test scenario.

        Args:
            _port (int): The port.
            _pid (int): The PID.

        Returns:
            None
        """

        return None


class _PlaintextProfileManager(_DummyProfileManager):
    """
    Provides a plaintext profile manager helper for test scenarios.
    """

    def uses_plaintext_storage(self) -> bool:
        """
        Reports whether the helper uses plaintext storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return True

    def uses_encrypted_storage(self) -> bool:
        """
        Reports whether the helper uses encrypted storage.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


class _DummyEvent:
    """
    Provides a dummy event test double.
    """

    def to_json(self) -> str:
        """
        Serializes the helper payload to JSON.

        Args:
            None

        Returns:
            str: The computed return value.
        """

        return json.dumps({'event_type': 'test'})


class _InspectingSocket:
    """
    Provides a inspecting socket helper for test scenarios.
    """

    def __init__(self, server: IpcServer) -> None:
        """
        Initializes the inspecting socket helper.

        Args:
            server (IpcServer): The server.

        Returns:
            None
        """

        self._server: IpcServer = server
        self.lock_was_held: Optional[bool] = None
        self.payloads: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.lock_was_held = self._server._lock.locked()
        self.payloads.append(payload)

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        return None


class _QueueResult:
    """
    Provides a queue result helper for test scenarios.
    """

    def __init__(self, was_duplicate: bool = False) -> None:
        """
        Initializes the queue result helper.

        Args:
            was_duplicate (bool): The was duplicate.

        Returns:
            None
        """

        self.was_duplicate: bool = was_duplicate


class _DummyContactManager:
    """
    Provides a dummy contact manager test double.
    """

    def ensure_alias_for_onion(self, _onion: str) -> str:
        """
        Ensures alias for onion for the test scenario.

        Args:
            _onion (str): The onion.

        Returns:
            str: The computed return value.
        """

        return 'peer'

    def resolve_target(self, _target: str) -> Optional[tuple[str, str]]:
        """
        Resolves target for the test scenario.

        Args:
            _target (str): The target.

        Returns:
            Optional[tuple[str, str]]: The computed return value.
        """

        return None


class _DummyHistoryManager:
    """
    Provides a dummy history manager test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy history manager helper.

        Args:
            None

        Returns:
            None
        """

        self.events: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def log_event(self, *args: Any, **kwargs: Any) -> None:
        """
        Records event for later assertions.

        Args:
            *args (Any): Extra args values.
            **kwargs (Any): Extra kwargs values.

        Returns:
            None
        """

        self.events.append((args, kwargs))


class _DummyMessageManager:
    """
    Provides a dummy message manager test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy message manager helper.

        Args:
            None

        Returns:
            None
        """

        self.queued: list[dict[str, Any]] = []
        self.unread_drop_count: int = 0

    def queue_message(self, **kwargs: Any) -> _QueueResult:
        """
        Queues message for later assertions.

        Args:
            **kwargs (Any): Extra kwargs values.

        Returns:
            _QueueResult: The computed return value.
        """

        self.queued.append(kwargs)
        return _QueueResult()

    def has_inbound_message(self, _onion: str, _msg_id: str) -> bool:
        """
        Reports whether the helper has inbound message.

        Args:
            _onion (str): The onion.
            _msg_id (str): The msg ID.

        Returns:
            bool: The computed return value.
        """

        return False

    def get_unread_live_count(self, _onion: str) -> int:
        """
        Returns unread live count for the test scenario.

        Args:
            _onion (str): The onion.

        Returns:
            int: The computed return value.
        """

        return 0

    def get_unread_drop_count(self, _onion: str) -> int:
        """
        Returns unread drop count for the test scenario.

        Args:
            _onion (str): The onion.

        Returns:
            int: The computed return value.
        """

        return self.unread_drop_count


class _DummyConn:
    """
    Provides a dummy conn test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy conn helper.

        Args:
            None

        Returns:
            None
        """

        self.sent: list[bytes] = []
        self.closed: bool = False

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.sent.append(payload)

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        self.closed = True


class _NetworkSocket:
    """
    Provides a network socket helper for test scenarios.
    """

    def __init__(self) -> None:
        """
        Initializes the network socket helper.

        Args:
            None

        Returns:
            None
        """

        self.closed: bool = False
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.sent.append(payload)

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        self.closed = True


class _AcceptedClientSocket:
    """
    Provides a accepted client socket helper for test scenarios.
    """

    def __init__(self) -> None:
        """
        Initializes the accepted client socket helper.

        Args:
            None

        Returns:
            None
        """

        self.closed: bool = False
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.sent.append(payload)

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        self.closed = True


class _AcceptorSocket:
    """
    Provides a acceptor socket helper for test scenarios.
    """

    def __init__(self, accepted_connections: list[_AcceptedClientSocket]) -> None:
        """
        Initializes the acceptor socket helper.

        Args:
            accepted_connections (list[_AcceptedClientSocket]): The accepted connections.

        Returns:
            None
        """

        self._accepted_connections: list[_AcceptedClientSocket] = accepted_connections
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def accept(self) -> tuple[_AcceptedClientSocket, tuple[str, int]]:
        """
        Returns the next queued accepted client socket.

        Args:
            None

        Returns:
            tuple[_AcceptedClientSocket, tuple[str, int]]: The computed return value.
        """

        conn = self._accepted_connections.pop(0)
        return conn, ('127.0.0.1', 0)


class _StopAfterRejectSocket:
    """
    Provides a stop after reject socket helper for test scenarios.
    """

    def __init__(self, server: IpcServer, conn: _AcceptedClientSocket) -> None:
        """
        Initializes the stop after reject socket helper.

        Args:
            server (IpcServer): The server.
            conn (_AcceptedClientSocket): The conn.

        Returns:
            None
        """

        self._server: IpcServer = server
        self._conn: _AcceptedClientSocket = conn
        self._accepted: bool = False
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def accept(self) -> tuple[_AcceptedClientSocket, tuple[str, int]]:
        """
        Returns the next queued accepted client socket.

        Args:
            None

        Returns:
            tuple[_AcceptedClientSocket, tuple[str, int]]: The computed return value.
        """

        if not self._accepted:
            self._accepted = True
            return self._conn, ('127.0.0.1', 0)

        self._server._stop_flag.set()
        raise OSError('stop accept loop')


class _ThreadStartHandle:
    """
    Provides a thread start handle helper for test scenarios.
    """

    def __init__(self, index: int, server: IpcServer) -> None:
        """
        Initializes the thread start handle helper.

        Args:
            index (int): The index.
            server (IpcServer): The server.

        Returns:
            None
        """

        self._index: int = index
        self._server: IpcServer = server

    def start(self) -> None:
        """
        Marks the helper as started.

        Args:
            None

        Returns:
            None
        """

        if self._index == 1:
            raise RuntimeError('thread start failed')
        self._server._stop_flag.set()


class _ThreadStartFactory:
    """
    Provides a thread start factory helper for test scenarios.
    """

    def __init__(self, server: IpcServer) -> None:
        """
        Initializes the thread start factory helper.

        Args:
            server (IpcServer): The server.

        Returns:
            None
        """

        self._server: IpcServer = server
        self.calls: int = 0

    def __call__(self, *args: Any, **kwargs: Any) -> _ThreadStartHandle:
        """
        Invokes the helper callable for the test scenario.

        Args:
            *args (Any): Extra args values.
            **kwargs (Any): Extra kwargs values.

        Returns:
            _ThreadStartHandle: The computed return value.
        """

        del args, kwargs
        self.calls += 1
        return _ThreadStartHandle(self.calls, self._server)


class _PassiveThread:
    """
    Provides a passive thread helper for test scenarios.
    """

    def start(self) -> None:
        """
        Marks the helper as started.

        Args:
            None

        Returns:
            None
        """

        return None

    def is_alive(self) -> bool:
        """
        Reports whether the helper is alive.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


class _ImmediateListenerThread:
    """
    Provides a immediate listener thread helper for test scenarios.
    """

    def __init__(self, target: Any) -> None:
        """
        Initializes the immediate listener thread helper.

        Args:
            target (Any): The target.

        Returns:
            None
        """

        self._target = target

    def start(self) -> None:
        """
        Marks the helper as started.

        Args:
            None

        Returns:
            None
        """

        self._target()


class _ImmediateListenerThreadFactory:
    """
    Provides a immediate listener thread factory helper for test scenarios.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> _ImmediateListenerThread:
        """
        Invokes the helper callable for the test scenario.

        Args:
            *args (Any): Extra args values.
            **kwargs (Any): Extra kwargs values.

        Returns:
            _ImmediateListenerThread: The computed return value.
        """

        del args
        return _ImmediateListenerThread(kwargs['target'])


class _FakeChatIpcSocket:
    """
    Provides a fake chat IPC socket test double.
    """

    def __init__(self, recv_items: list[object]) -> None:
        """
        Initializes the fake chat IPC socket helper.

        Args:
            recv_items (list[object]): The recv items.

        Returns:
            None
        """

        self._recv_items: list[object] = recv_items
        self.connected_to: Optional[tuple[str, int]] = None
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []
        self.closed: bool = False
        self.shutdown_called: bool = False

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def connect(self, address: tuple[str, int]) -> None:
        """
        Captures the requested connection target.

        Args:
            address (tuple[str, int]): The address.

        Returns:
            None
        """

        self.connected_to = address

    def recv(self, _size: int) -> bytes:
        """
        Returns the next buffered payload chunk.

        Args:
            _size (int): The size.

        Returns:
            bytes: The computed return value.
        """

        item = self._recv_items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return cast(bytes, item)

    def sendall(self, payload: bytes) -> None:
        """
        Captures one outgoing payload for assertions.

        Args:
            payload (bytes): The payload.

        Returns:
            None
        """

        self.sent.append(payload)

    def shutdown(self, _how: int) -> None:
        """
        Executes shutdown for the test scenario.

        Args:
            _how (int): The how.

        Returns:
            None
        """

        self.shutdown_called = True

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        self.closed = True


class _FaultingOutboxMessageManager:
    """
    Provides a faulting outbox message manager helper for test scenarios.
    """

    def __init__(self, stop_flag: threading.Event) -> None:
        """
        Initializes the faulting outbox message manager helper.

        Args:
            stop_flag (threading.Event): The stop flag.

        Returns:
            None
        """

        self._stop_flag: threading.Event = stop_flag
        self.calls: int = 0

    def get_pending_outbox(self) -> list[tuple[int, str, str, str, str, str]]:
        """
        Returns pending outbox for the test scenario.

        Args:
            None

        Returns:
            list[tuple[int, str, str, str, str, str]]: The computed return value.
        """

        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('boom')

        self._stop_flag.set()
        return []


class _DummyKeyManager:
    """
    Provides a dummy key manager test double.
    """

    def __init__(self, secret_key: bytes) -> None:
        """
        Initializes the dummy key manager helper.

        Args:
            secret_key (bytes): The secret key.

        Returns:
            None
        """

        self._secret_key: bytes = secret_key

    def get_metor_key(self) -> bytes:
        """
        Returns metor key for the test scenario.

        Args:
            None

        Returns:
            bytes: The computed return value.
        """

        return self._secret_key


class _FakeStream:
    """
    Provides a fake stream test double.
    """

    def __init__(self, messages: list[Optional[str]]) -> None:
        """
        Initializes the fake stream helper.

        Args:
            messages (list[Optional[str]]): The messages.

        Returns:
            None
        """

        self._messages: list[Optional[str]] = messages
        self._index: int = 0

    def read_line(self) -> Optional[str]:
        """
        Reads line from the helper stream.

        Args:
            None

        Returns:
            Optional[str]: The computed return value.
        """

        if self._index >= len(self._messages):
            return None

        message: Optional[str] = self._messages[self._index]
        self._index += 1
        return message


class _DummyReceiverConfig:
    """
    Provides a dummy receiver config test double.
    """

    def get_float(self, _key: Any) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            float: The computed return value.
        """

        return 0.2


class _DummyState:
    """
    Provides a dummy state test double.
    """

    def consume_outbound_connected_origin(self, _onion: str) -> None:
        """
        Consumes outbound connected origin from the helper state.

        Args:
            _onion (str): The onion.

        Returns:
            None
        """

        return None

    def add_active_connection(self, _onion: str, _conn: socket.socket) -> None:
        """
        Adds active connection to the helper state.

        Args:
            _onion (str): The onion.
            _conn (socket.socket): The conn.

        Returns:
            None
        """

        return None

    def consume_retunnel_reconnect(self, _onion: str) -> bool:
        """
        Consumes retunnel reconnect from the helper state.

        Args:
            _onion (str): The onion.

        Returns:
            bool: The computed return value.
        """

        return False

    def clear_retunnel_flow(self, _onion: str) -> None:
        """
        Clears retunnel flow from the helper state.

        Args:
            _onion (str): The onion.

        Returns:
            None
        """

        return None

    def is_known_socket(self, _onion: str, _conn: socket.socket) -> bool:
        """
        Reports whether the helper is known socket.

        Args:
            _onion (str): The onion.
            _conn (socket.socket): The conn.

        Returns:
            bool: The computed return value.
        """

        return True


class _DummyContactManagerReceiver:
    """
    Provides a dummy contact manager receiver test double.
    """

    def ensure_alias_for_onion(self, _onion: str) -> str:
        """
        Ensures alias for onion for the test scenario.

        Args:
            _onion (str): The onion.

        Returns:
            str: The computed return value.
        """

        return 'peer'


class _DummyHistoryManagerReceiver:
    """
    Provides a dummy history manager receiver test double.
    """

    def log_event(self, *args: Any, **kwargs: Any) -> None:
        """
        Records event for later assertions.

        Args:
            *args (Any): Extra args values.
            **kwargs (Any): Extra kwargs values.

        Returns:
            None
        """

        return None


class _DummyRouterReceiver:
    """
    Provides a dummy router receiver test double.
    """

    def process_incoming_ack(self, _onion: str, _msg_id: str) -> None:
        """
        Executes process incoming ack for the test scenario.

        Args:
            _onion (str): The onion.
            _msg_id (str): The msg ID.

        Returns:
            None
        """

        return None

    def process_incoming_msg(
        self,
        _conn: socket.socket,
        _onion: str,
        _payload_id: str,
        _b64_payload: str,
    ) -> bool:
        """
        Executes process incoming msg for the test scenario.

        Args:
            _conn (socket.socket): The conn.
            _onion (str): The onion.
            _payload_id (str): The payload ID.
            _b64_payload (str): The b64 payload.

        Returns:
            bool: The computed return value.
        """

        return False

    def replay_unacked_messages(self, _onion: str) -> list[str]:
        """
        Executes replay unacked messages for the test scenario.

        Args:
            _onion (str): The onion.

        Returns:
            list[str]: The computed return value.
        """

        return []


class _DummyReceiverSocket:
    """
    Provides a dummy receiver socket test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy receiver socket helper.

        Args:
            None

        Returns:
            None
        """

        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        """
        Captures one timeout value for assertions.

        Args:
            timeout (float): The timeout.

        Returns:
            None
        """

        self.timeouts.append(timeout)

    def close(self) -> None:
        """
        Closes the helper resource.

        Args:
            None

        Returns:
            None
        """

        return None


class _ListenerTestConfig:
    """
    Provides a listener test config helper for test scenarios.
    """

    def __init__(self, *, allow_headless_live_backlog: bool = True) -> None:
        """
        Initializes the listener test config helper.

        Args:
            allow_headless_live_backlog (bool): The allow headless live backlog.

        Returns:
            None
        """

        self._allow_headless_live_backlog: bool = allow_headless_live_backlog

    def get_bool(self, key: Any) -> bool:
        """
        Returns bool for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            bool: The computed return value.
        """

        if key is SettingKey.AUTO_ACCEPT_CONTACTS:
            return False
        return False

    def get_int(self, key: Any) -> int:
        """
        Returns int for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            int: The computed return value.
        """

        if key is SettingKey.MAX_UNSEEN_LIVE_MSGS:
            return 1 if self._allow_headless_live_backlog else 0
        return 0

    def get_float(self, _key: Any) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            float: The computed return value.
        """

        return 0.2


class _ListenerStream:
    """
    Provides a listener stream helper for test scenarios.
    """

    def __init__(self, buffer: bytes = b'') -> None:
        """
        Initializes the listener stream helper.

        Args:
            buffer (bytes): The buffer.

        Returns:
            None
        """

        self._buffer: bytes = buffer

    def get_buffer(self) -> bytes:
        """
        Returns buffer for the test scenario.

        Args:
            None

        Returns:
            bytes: The computed return value.
        """

        return self._buffer


class _ConnectTestConfig:
    """
    Provides a connect test config helper for test scenarios.
    """

    def __init__(
        self,
        max_connections: int,
        max_retries: int = 0,
        live_reconnect_delay: int = 0,
    ) -> None:
        """
        Initializes the connect test config helper.

        Args:
            max_connections (int): The max connections.
            max_retries (int): The max retries.
            live_reconnect_delay (int): The live reconnect delay.

        Returns:
            None
        """

        self._max_connections: int = max_connections
        self._max_retries: int = max_retries
        self._live_reconnect_delay: int = live_reconnect_delay

    def get_int(self, key: Any) -> int:
        """
        Returns int for the test scenario.

        Args:
            key (Any): The key.

        Returns:
            int: The computed return value.
        """

        if key is SettingKey.MAX_CONCURRENT_CONNECTIONS:
            return self._max_connections
        if key is SettingKey.MAX_CONNECT_RETRIES:
            return self._max_retries
        if key is SettingKey.LIVE_RECONNECT_DELAY:
            return self._live_reconnect_delay
        if key is SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT:
            return 1
        return 0

    def get_float(self, _key: Any) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (Any): The key.

        Returns:
            float: The computed return value.
        """

        return 0.0


class _ConnectControllerHarness:
    """
    Provides a connect controller harness helper for test scenarios.
    """

    def __init__(
        self,
        state: StateTracker,
        config: _ConnectTestConfig,
        connect_side_effect: Optional[BaseException] = None,
    ) -> None:
        """
        Initializes the connect controller harness helper.

        Args:
            state (StateTracker): The state.
            config (_ConnectTestConfig): The config.
            connect_side_effect (Optional[BaseException]): The connect side effect.

        Returns:
            None
        """

        self.contact_manager_mock = Mock()
        self.contact_manager_mock.resolve_target_for_interaction = Mock(
            return_value=('peer', 'peer-onion')
        )
        self._cm = cast(ContactManager, self.contact_manager_mock)
        self.tor_manager_mock = Mock()
        self.tor_manager_mock.onion = 'self-onion'
        self.tor_manager_mock.connect = Mock(side_effect=connect_side_effect)
        self._tm = cast(TorManager, self.tor_manager_mock)
        self._state: StateTracker = state
        self._config = cast(Config, config)
        self.broadcast_mock = Mock()
        self._broadcast = cast(Any, self.broadcast_mock)
        self._stop_flag = threading.Event()
        self._crypto = cast(Crypto, Mock())
        self._hm = cast(HistoryManager, Mock())
        self._mm = cast(MessageManager, Mock())
        self._receiver: Any = None
        self.enqueued_live_reconnects: list[str] = []

    def accept(
        self,
        _target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Returns the next queued accepted client socket.

        Args:
            _target (str): The target.
            origin (ConnectionOrigin): The origin.

        Returns:
            None
        """

        del origin

    def _get_local_connection_actor(self, _origin: ConnectionOrigin) -> Any:
        """
        Returns local connection actor for the test scenario.

        Args:
            _origin (ConnectionOrigin): The origin.

        Returns:
            Any: The computed return value.
        """

        return None

    def _get_local_history_actor(self, _origin: ConnectionOrigin) -> Any:
        """
        Returns local history actor for the test scenario.

        Args:
            _origin (ConnectionOrigin): The origin.

        Returns:
            Any: The computed return value.
        """

        return None

    def _sleep_connect_retry_backoff(self) -> None:
        """
        Skips connect retry backoff delays for the test scenario.

        Args:
            None

        Returns:
            None
        """

        return None

    def _broadcast_retunnel_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts retunnel failure for the test scenario.

        Args:
            alias (str): The alias.
            onion (str): The onion.
            error (Optional[str]): The error.

        Returns:
            None
        """

        self._state.clear_retunnel_flow(onion)
        self._broadcast(
            create_event(
                EventType.DISCONNECTED,
                {
                    'alias': alias,
                    'onion': onion,
                    'actor': ConnectionActor.SYSTEM,
                    'origin': ConnectionOrigin.RETUNNEL,
                },
            )
        )
        params: dict[str, Any] = {
            'alias': alias,
            'onion': onion,
            'error_code': RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED,
        }
        if error is not None:
            params['error_detail'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))
        self._state.mark_live_reconnect_grace(onion, 1.0)
        if self._config.get_int(SettingKey.LIVE_RECONNECT_DELAY) > 0:
            self._state.mark_scheduled_auto_reconnect(onion)
            if self._enqueue_live_reconnect(onion):
                self._broadcast(
                    AutoReconnectScheduledEvent(
                        alias=alias,
                        onion=onion,
                        origin=ConnectionOrigin.AUTO_RECONNECT,
                        actor=ConnectionActor.SYSTEM,
                    )
                )
            return

        self._state.mark_live_reconnect_grace(onion, 1.0)

    def _broadcast_retunnel_preserved_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts retunnel preserved failure for the test scenario.

        Args:
            alias (str): The alias.
            onion (str): The onion.
            error (Optional[str]): The error.

        Returns:
            None
        """

        self._state.mark_live_reconnect_grace(onion, 0.0)
        self._state.clear_retunnel_flow(onion)
        params: dict[str, Any] = {'alias': alias, 'onion': onion}
        if error is not None:
            params['error'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Enqueues live reconnect for later assertions.

        Args:
            onion (str): The onion.

        Returns:
            bool: The computed return value.
        """

        self.enqueued_live_reconnects.append(onion)
        return True

    def _convert_unacked_live_to_drops(
        self,
        alias: str,
        onion: str,
        emit_event: bool = True,
    ) -> bool:
        """
        Converts retained unacked live messages for the test scenario.

        Args:
            alias (str): The alias.
            onion (str): The onion.
            emit_event (bool): Whether to emit a fallback-success event.

        Returns:
            bool: True if any messages were converted.
        """

        unacked = self._state.pop_unacked_messages(onion)
        if not unacked:
            return False
        if emit_event:
            self._broadcast(
                FallbackSuccessEvent(
                    alias=alias,
                    onion=onion,
                    count=len(unacked),
                    msg_ids=list(unacked.keys()),
                )
            )
        return True


class _RetunnelControllerHarness(ConnectionControllerRetunnelMixin):
    """
    Provides a retunnel controller harness helper for test scenarios.
    """

    def __init__(self) -> None:
        """
        Initializes the retunnel controller harness helper.

        Args:
            None

        Returns:
            None
        """

        self.contact_manager_mock = Mock()
        self.contact_manager_mock.resolve_target = Mock(
            return_value=('peer', 'peer-onion')
        )
        self._cm = cast(ContactManager, self.contact_manager_mock)
        self.state_mock = Mock()
        self.state_mock.is_connected_or_pending.side_effect = [True, False]
        self.state_mock.is_retunneling.return_value = True
        self._state = cast(StateTracker, self.state_mock)
        self.broadcast_mock = Mock()
        self._broadcast = cast(Any, self.broadcast_mock)
        self.history_manager_mock = Mock()
        self._hm = cast(HistoryManager, self.history_manager_mock)
        self.tor_manager_mock = Mock()
        self.tor_manager_mock.rotate_circuits.return_value = (True, None, {})
        self._tm = cast(TorManager, self.tor_manager_mock)
        self._config = cast(Config, _ConnectTestConfig(max_connections=10))
        self._stop_flag = threading.Event()
        self.connect_to_mock = Mock()
        self.disconnect_mock = Mock()

    def connect_to(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Executes connect to for the test scenario.

        Args:
            target (str): The target.
            origin (ConnectionOrigin): The origin.

        Returns:
            None
        """

        self.connect_to_mock(target, origin=origin)

    def disconnect(self, *args: Any, **kwargs: Any) -> None:
        """
        Executes disconnect for the test scenario.

        Args:
            *args (Any): Extra args values.
            **kwargs (Any): Extra kwargs values.

        Returns:
            None
        """

        self.disconnect_mock(*args, **kwargs)


class _DisconnectControllerHarness(ConnectionControllerSessionMixin):
    """
    Provides a disconnect controller harness helper for test scenarios.
    """

    def __init__(self, state: StateTracker, config: Config) -> None:
        """
        Initializes the disconnect controller harness helper.

        Args:
            state (StateTracker): The transport state.
            config (Config): The profile configuration.

        Returns:
            None
        """

        contact_manager_mock = Mock()
        contact_manager_mock.resolve_target.return_value = ('peer', 'peer-onion')
        contact_manager_mock.cleanup_orphans.return_value = []
        self._cm = cast(ContactManager, contact_manager_mock)
        self._state = state
        self._config = config
        self._broadcast = cast(Any, Mock())
        self._stop_flag = threading.Event()
        self._tm = cast(TorManager, Mock(onion='self-onion'))
        self._hm = cast(HistoryManager, _DummyHistoryManager())
        self._mm = cast(MessageManager, _DummyMessageManager())
        self._crypto = cast(Crypto, Mock())
        self._receiver = None
        self.enqueued_live_reconnects: list[str] = []

    def _broadcast_retunnel_preserved_failure(
        self,
        _alias: str,
        _onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Stubbed preserved retunnel failure hook for the test harness.

        Args:
            _alias (str): The peer alias.
            _onion (str): The peer onion identity.
            error (Optional[str]): Optional error detail.

        Returns:
            None
        """

        del error

    def _schedule_retunnel_recovery_retry(
        self,
        _alias: str,
        _onion: str,
        _error: str,
    ) -> bool:
        """
        Stubbed retunnel recovery hook for the test harness.

        Args:
            _alias (str): The peer alias.
            _onion (str): The peer onion identity.
            _error (str): The retry error detail.

        Returns:
            bool: Always False for the test harness.
        """

        return False

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Records delayed reconnect scheduling for later assertions.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: Always True for the test harness.
        """

        self.enqueued_live_reconnects.append(onion)
        return True


class DaemonHardeningTests(unittest.TestCase):
    """
    Covers daemon hardening regression scenarios.
    """

    @staticmethod
    def _build_daemon(
        start_locked: bool = False,
        require_session_auth: bool = False,
    ) -> Daemon:
        """
        Builds daemon for the surrounding tests.

        Args:
            start_locked (bool): The start locked.
            require_session_auth (bool): The require session auth.

        Returns:
            Daemon: The computed return value.
        """

        with (
            patch('metor.core.daemon.managed.engine.atexit.register'),
            patch('metor.core.daemon.managed.engine.signal.signal'),
        ):
            return Daemon(
                cast(ProfileManager, _DummyProfileManager()),
                require_session_auth=require_session_auth,
                start_locked=start_locked,
            )

    @staticmethod
    def _build_v3_onion(public_key: bytes, checksum: bytes, version: bytes) -> str:
        """
        Builds v3 onion for the surrounding tests.

        Args:
            public_key (bytes): The public key.
            checksum (bytes): The checksum.
            version (bytes): The version.

        Returns:
            str: The computed return value.
        """

        return (
            base64.b32encode(public_key + checksum + version)
            .decode('ascii')
            .lower()
            .rstrip('=')
        )

    @staticmethod
    def _build_v3_checksum(public_key: bytes, version: bytes) -> bytes:
        """
        Builds v3 checksum for the surrounding tests.

        Args:
            public_key (bytes): The public key.
            version (bytes): The version.

        Returns:
            bytes: The computed return value.
        """

        return hashlib.sha3_256(b'.onion checksum' + public_key + version).digest()[
            : Constants.TOR_V3_CHECKSUM_BYTES
        ]

    @staticmethod
    def _build_live_listener(
        state: StateTracker,
        *,
        allow_headless_live_backlog: bool = True,
        has_live_consumers: bool = False,
    ) -> tuple[InboundListener, Mock]:
        """
        Builds live listener for the surrounding tests.

        Args:
            state (StateTracker): The state.
            allow_headless_live_backlog (bool): The allow headless live backlog.
            has_live_consumers (bool): The has live consumers.

        Returns:
            tuple[InboundListener, Mock]: The computed return value.
        """

        receiver_mock = Mock()
        contact_manager_mock = Mock()
        contact_manager_mock.ensure_alias_for_onion.return_value = 'peer'
        contact_manager_mock.get_all_contacts.return_value = []

        listener = InboundListener(
            tm=cast(TorManager, Mock(onion='self-onion')),
            cm=cast(ContactManager, contact_manager_mock),
            hm=cast(HistoryManager, Mock()),
            crypto=cast(Crypto, Mock()),
            state=state,
            router=cast(MessageRouter, Mock()),
            receiver=cast(StreamReceiver, receiver_mock),
            broadcast_callback=Mock(),
            has_live_consumers_callback=lambda: has_live_consumers,
            enqueue_live_reconnect_callback=lambda _onion: True,
            stop_flag=threading.Event(),
            config=cast(
                Config,
                _ListenerTestConfig(
                    allow_headless_live_backlog=allow_headless_live_backlog
                ),
            ),
        )
        return listener, receiver_mock

    def test_ipc_broadcast_sends_without_holding_lock(self) -> None:
        """
        Verifies that IPC broadcast sends without holding lock.

        Args:
            None

        Returns:
            None
        """

        server = IpcServer(
            cast(ProfileManager, _DummyProfileManager()),
            lambda _cmd, _conn: None,
        )
        client = _InspectingSocket(server)
        server._clients = cast(list[socket.socket], [cast(socket.socket, client)])

        server.broadcast(cast(IpcEvent, _DummyEvent()))

        self.assertEqual(client.payloads, [b'{"event_type": "test"}\n'])
        self.assertFalse(client.lock_was_held)

    def test_daemon_broadcast_targets_only_authenticated_clients(self) -> None:
        """
        Verifies that daemon broadcast targets only authenticated clients.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._ipc = Mock()
        authenticated_conn, peer = socket.socketpair()

        try:
            with daemon._client_state_lock:
                daemon._authenticated_clients.add(authenticated_conn)

            event = create_event(EventType.INTERNAL_ERROR)
            with patch.object(Daemon, '_requires_session_auth', return_value=True):
                daemon._broadcast_ipc_event(event)

            daemon._ipc.broadcast_to.assert_called_once_with(
                event,
                {authenticated_conn},
            )
            daemon._ipc.broadcast.assert_not_called()
        finally:
            authenticated_conn.close()
            peer.close()

    def test_runtime_internal_error_uses_daemon_status_callback(self) -> None:
        """
        Verifies that runtime internal error uses daemon status callback.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._ipc = Mock()
        status_cb = Mock()
        daemon._status_cb = status_cb

        daemon._on_runtime_internal_error('Outbox worker recovered from an error.')

        status_cb.assert_called_once_with(
            DaemonStatus.RUNTIME_ERROR,
            {'message': 'Outbox worker recovered from an error.'},
        )
        daemon._ipc.broadcast.assert_not_called()
        daemon._ipc.broadcast_to.assert_not_called()

    def test_session_auth_requirement_is_frozen_at_daemon_start(self) -> None:
        """
        Verifies that session auth requirement is frozen at daemon start.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon(require_session_auth=False)
        daemon._local_auth.install_context(create_session_auth_context('secret'))

        self.assertFalse(daemon._requires_session_auth())

    def test_create_managed_daemon_rejects_plaintext_locked_mode(self) -> None:
        """
        Verifies that create managed daemon rejects plaintext locked mode.

        Args:
            None

        Returns:
            None
        """

        with self.assertRaises(PlaintextLockedDaemonError):
            create_managed_daemon(
                cast(ProfileManager, _PlaintextProfileManager()),
                start_locked=True,
            )

    def test_runtime_error_status_formats_daemon_log_prefix(self) -> None:
        """
        Verifies that runtime error status formats daemon log prefix.

        Args:
            None

        Returns:
            None
        """

        formatted = CommandHandlers._format_daemon_status(
            DaemonStatus.RUNTIME_ERROR,
            {'message': 'IPC acceptor recovered cleanly.'},
        )

        self.assertEqual(
            formatted,
            f'{Theme.CYAN}[DAEMON-LOG]{Theme.RESET} IPC acceptor recovered cleanly.',
        )

    def test_inbound_listener_start_listener_raises_when_bind_fails(self) -> None:
        """
        Verifies that inbound listener start listener raises when bind fails.

        Args:
            None

        Returns:
            None
        """

        history_manager_mock = Mock()
        broadcast_mock = Mock()
        listener = InboundListener(
            tm=cast(TorManager, Mock(incoming_port=43123)),
            cm=cast(ContactManager, Mock()),
            hm=cast(HistoryManager, history_manager_mock),
            crypto=cast(Crypto, Mock()),
            state=cast(StateTracker, Mock()),
            router=cast(MessageRouter, Mock()),
            receiver=cast(StreamReceiver, Mock()),
            broadcast_callback=broadcast_mock,
            has_live_consumers_callback=lambda: False,
            enqueue_live_reconnect_callback=lambda _onion: True,
            stop_flag=threading.Event(),
            config=cast(Config, _DummyConfig()),
        )
        socket_mock = Mock()
        socket_mock.bind.side_effect = OSError('bind failed')

        with (
            patch(
                'metor.core.daemon.managed.network.listener.threading.Thread',
                new=_ImmediateListenerThreadFactory(),
            ),
            patch(
                'metor.core.daemon.managed.network.listener.socket.socket',
                return_value=socket_mock,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, 'bind failed'):
                listener.start_listener()

        history_manager_mock.log_event.assert_called_once()
        broadcast_mock.assert_called_once()

    def test_start_subsystems_aborts_when_listener_readiness_fails(self) -> None:
        """
        Verifies that start subsystems aborts when listener readiness fails.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._tm = Mock()
        daemon._tm.start.return_value = (True, None, {})
        daemon._tm.onion = 'peeronion'
        daemon._network = Mock()
        daemon._network.start_listener.side_effect = RuntimeError('listener failed')
        daemon._outbox = Mock()
        daemon._ipc = Mock(port=43111)
        status_cb = Mock()
        daemon._status_cb = status_cb

        with (
            patch.object(daemon._pm, 'initialize') as initialize_mock,
            patch.object(daemon, 'stop') as stop_mock,
        ):
            result = daemon._start_subsystems()

        self.assertFalse(result)
        initialize_mock.assert_called_once()
        stop_mock.assert_called_once()
        daemon._outbox.start.assert_not_called()
        status_cb.assert_called_once_with(
            DaemonStatus.RUNTIME_ERROR,
            {'message': 'listener failed'},
        )

    def test_locked_daemon_rejects_self_destruct_command(self) -> None:
        """
        Verifies that locked daemon rejects self destruct command.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon(start_locked=True)
        daemon._ipc = Mock()
        conn, peer = socket.socketpair()

        try:
            with patch(
                'metor.core.daemon.managed.engine.threading.Thread'
            ) as thread_cls:
                daemon._process_ui_command(SelfDestructCommand(), conn)

            thread_cls.assert_not_called()
            daemon._ipc.send_to.assert_called_once()
            sent_event = daemon._ipc.send_to.call_args.args[1]
            self.assertIs(sent_event.event_type, EventType.DAEMON_LOCKED)
        finally:
            conn.close()
            peer.close()

    def test_unauthenticated_self_destruct_requires_session_auth(self) -> None:
        """
        Verifies that unauthenticated self destruct requires session auth.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._ipc = Mock()
        conn, peer = socket.socketpair()

        try:
            with (
                patch.object(Daemon, '_requires_session_auth', return_value=True),
                patch.object(
                    daemon._local_auth,
                    'issue_session_challenge',
                    return_value=object(),
                ),
                patch.object(
                    daemon,
                    '_build_session_auth_event',
                    return_value=create_event(EventType.AUTH_REQUIRED),
                ) as build_auth_event,
                patch(
                    'metor.core.daemon.managed.engine.threading.Thread'
                ) as thread_cls,
            ):
                daemon._process_ui_command(SelfDestructCommand(), conn)

            thread_cls.assert_not_called()
            build_auth_event.assert_called_once()
            daemon._ipc.send_to.assert_called_once()
            sent_event = daemon._ipc.send_to.call_args.args[1]
            self.assertIs(sent_event.event_type, EventType.AUTH_REQUIRED)
        finally:
            conn.close()
            peer.close()

    def test_unauthenticated_init_requires_session_auth(self) -> None:
        """
        Verifies that unauthenticated init requires session auth.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._ipc = Mock()
        daemon._network_handler = Mock()
        conn, peer = socket.socketpair()

        try:
            with (
                patch.object(Daemon, '_requires_session_auth', return_value=True),
                patch.object(
                    daemon._local_auth,
                    'issue_session_challenge',
                    return_value=object(),
                ),
                patch.object(
                    daemon,
                    '_build_session_auth_event',
                    return_value=create_event(EventType.AUTH_REQUIRED),
                ) as build_auth_event,
            ):
                daemon._process_ui_command(InitCommand(), conn)

            build_auth_event.assert_called_once()
            daemon._network_handler.handle.assert_not_called()
            daemon._ipc.send_to.assert_called_once()
            sent_event = daemon._ipc.send_to.call_args.args[1]
            self.assertIs(sent_event.event_type, EventType.AUTH_REQUIRED)
        finally:
            conn.close()
            peer.close()

    def test_unauthenticated_unlock_requires_session_auth_when_already_unlocked(
        self,
    ) -> None:
        """
        Verifies that unauthenticated unlock requires session auth when already unlocked.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon()
        daemon._ipc = Mock()
        conn, peer = socket.socketpair()

        try:
            with (
                patch.object(Daemon, '_requires_session_auth', return_value=True),
                patch.object(
                    daemon._local_auth,
                    'issue_session_challenge',
                    return_value=object(),
                ),
                patch.object(
                    daemon,
                    '_build_session_auth_event',
                    return_value=create_event(EventType.AUTH_REQUIRED),
                ) as build_auth_event,
            ):
                daemon._process_ui_command(UnlockCommand(password='secret'), conn)

            build_auth_event.assert_called_once()
            daemon._ipc.send_to.assert_called_once()
            sent_event = daemon._ipc.send_to.call_args.args[1]
            self.assertIs(sent_event.event_type, EventType.AUTH_REQUIRED)
        finally:
            conn.close()
            peer.close()

    def test_ipc_acceptor_recovers_after_handler_thread_start_failure(self) -> None:
        """
        Verifies that IPC acceptor recovers after handler thread start failure.

        Args:
            None

        Returns:
            None
        """

        errors: list[str] = []
        server = IpcServer(
            cast(ProfileManager, _DummyProfileManager()),
            lambda _cmd, _conn: None,
            error_callback=lambda message: errors.append(message),
        )
        first_conn = _AcceptedClientSocket()
        second_conn = _AcceptedClientSocket()
        server._server = cast(
            socket.socket,
            _AcceptorSocket([first_conn, second_conn]),
        )
        thread_factory = _ThreadStartFactory(server)

        with patch(
            'metor.core.daemon.managed.ipc.threading.Thread',
            side_effect=thread_factory,
        ):
            server._acceptor()

        self.assertEqual(
            errors,
            ['IPC acceptor failed to start a client handler thread. Continuing.'],
        )
        self.assertEqual(thread_factory.calls, 2)
        self.assertTrue(first_conn.closed)
        self.assertNotIn(first_conn, server._clients)
        self.assertIn(second_conn, server._clients)

    def test_ipc_acceptor_rejects_clients_over_limit(self) -> None:
        """
        Verifies that IPC acceptor rejects clients over limit.

        Args:
            None

        Returns:
            None
        """

        server = IpcServer(
            cast(ProfileManager, _DummyProfileManager()),
            lambda _cmd, _conn: None,
        )
        existing_client = cast(socket.socket, _DummyConn())
        limited_conn = _AcceptedClientSocket()
        server._clients = [existing_client]
        server._server = cast(
            socket.socket,
            _StopAfterRejectSocket(server, limited_conn),
        )

        with patch('metor.core.daemon.managed.ipc.threading.Thread') as thread_cls:
            server._acceptor()

        thread_cls.assert_not_called()
        self.assertTrue(limited_conn.closed)
        self.assertEqual(len(limited_conn.sent), 1)
        event = IpcEvent.from_dict(json.loads(limited_conn.sent[0].decode('utf-8')))
        self.assertIs(event.event_type, EventType.IPC_CLIENT_LIMIT_REACHED)
        self.assertEqual(getattr(event, 'max_clients'), 1)

    def test_daemon_reports_local_auth_rate_limit_during_locked_startup(self) -> None:
        """
        Verifies that daemon reports local auth rate limit during locked startup.

        Args:
            None

        Returns:
            None
        """

        daemon = self._build_daemon(start_locked=True)
        daemon._ipc = Mock()
        conn, peer = socket.socketpair()

        try:
            with patch.object(
                daemon._local_auth,
                'get_retry_after_seconds',
                return_value=12,
            ):
                daemon._process_ui_command(InitCommand(), conn)

            daemon._ipc.send_to.assert_called_once()
            sent_event = daemon._ipc.send_to.call_args.args[1]
            self.assertIs(sent_event.event_type, EventType.LOCAL_AUTH_RATE_LIMITED)
            self.assertEqual(sent_event.retry_after, 12)
        finally:
            conn.close()
            peer.close()

    def test_outbox_worker_reports_unexpected_loop_error_without_history_noise(
        self,
    ) -> None:
        """
        Verifies that outbox worker reports unexpected loop error without history noise.

        Args:
            None

        Returns:
            None
        """

        stop_flag = threading.Event()
        history_manager = _DummyHistoryManager()
        message_manager = _FaultingOutboxMessageManager(stop_flag)
        errors: list[str] = []
        worker = OutboxWorker(
            tm=cast(TorManager, object()),
            mm=cast(MessageManager, message_manager),
            hm=cast(HistoryManager, history_manager),
            crypto=cast(Crypto, object()),
            broadcast_callback=lambda _event: None,
            stop_flag=stop_flag,
            config=cast(Config, _DummyConfig()),
            error_callback=lambda message: errors.append(message),
        )

        with patch('metor.core.daemon.managed.outbox.time.sleep', return_value=None):
            worker._loop()

        self.assertEqual(
            errors,
            ['Outbox worker loop recovered from an unexpected runtime error.'],
        )
        self.assertEqual(message_manager.calls, 2)
        self.assertEqual(history_manager.events, [])

    def test_outbox_worker_requires_exact_ack_frames(self) -> None:
        """
        Verifies that outbox worker requires exact ack frames.

        Args:
            None

        Returns:
            None
        """

        self.assertTrue(OutboxWorker._is_expected_ack_line('msg-1', '/ack msg-1'))
        self.assertFalse(
            OutboxWorker._is_expected_ack_line('msg-1', '/ack msg-1 extra')
        )
        self.assertFalse(OutboxWorker._is_expected_ack_line('msg-1', '/ack other'))
        self.assertFalse(
            OutboxWorker._is_expected_ack_line('msg-1', 'prefix /ack msg-1')
        )

    def test_chat_ipc_client_applies_timeout_and_ignores_read_timeouts(self) -> None:
        """
        Verifies that chat IPC client applies timeout and ignores read timeouts.

        Args:
            None

        Returns:
            None
        """

        disconnect_mock = Mock()
        fake_socket = _FakeChatIpcSocket([socket.timeout(), b''])
        client = IpcClient(
            port=4312,
            timeout=2.5,
            on_event=lambda _event: None,
            on_disconnect=disconnect_mock,
        )

        with (
            patch('metor.ui.chat.ipc.socket.socket', return_value=fake_socket),
            patch('metor.ui.chat.ipc.threading.Thread', return_value=_PassiveThread()),
        ):
            self.assertTrue(client.connect())

        self.assertEqual(fake_socket.timeouts, [2.5])
        client._listener_thread_main()
        disconnect_mock.assert_called_once()

    def test_retunnel_disconnects_existing_live_connection_before_replacement(
        self,
    ) -> None:
        """
        Verifies that retunnel disconnects existing live connection before replacement.

        Args:
            None

        Returns:
            None
        """

        controller = _RetunnelControllerHarness()

        controller.retunnel('peer')

        controller.disconnect_mock.assert_called_once_with(
            'peer-onion',
            initiated_by_self=True,
            suppress_events=True,
            origin=ConnectionOrigin.RETUNNEL,
        )
        controller.state_mock.mark_retunnel_started.assert_called_once_with(
            'peer-onion'
        )
        controller.state_mock.mark_retunnel_reconnect.assert_called_once_with(
            'peer-onion'
        )
        controller.connect_to_mock.assert_called_once_with(
            'peer-onion',
            origin=ConnectionOrigin.RETUNNEL,
        )

    def test_state_allows_pending_replacement_during_retunnel(self) -> None:
        """
        Verifies that state allows pending replacement during retunnel.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        active_conn, active_peer = socket.socketpair()
        pending_conn, pending_peer = socket.socketpair()
        try:
            state.add_active_connection('peer', active_conn)
            state.mark_retunnel_started('peer')

            added = state.add_pending_connection(
                'peer',
                pending_conn,
                b'',
                reason=PendingConnectionReason.USER_ACCEPT,
                origin=ConnectionOrigin.RETUNNEL,
            )

            self.assertTrue(added)
            self.assertIn('peer', state.get_pending_connections_keys())
        finally:
            active_peer.close()
            pending_peer.close()
            conn = state.pop_any_connection('peer')
            if conn is not None and conn.fileno() != -1:
                conn.close()

    def test_state_allows_pending_replacement_for_remote_auto_reconnect(self) -> None:
        """
        Verifies that state allows pending replacement for remote auto reconnect.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        active_conn, active_peer = socket.socketpair()
        pending_conn, pending_peer = socket.socketpair()
        try:
            state.add_active_connection('peer', active_conn)

            added = state.add_pending_connection(
                'peer',
                pending_conn,
                b'',
                reason=PendingConnectionReason.CONSUMER_ABSENT,
                origin=ConnectionOrigin.AUTO_RECONNECT,
            )

            self.assertTrue(added)
            self.assertIn('peer', state.get_pending_connections_keys())
        finally:
            active_peer.close()
            pending_peer.close()
            conn = state.pop_any_connection('peer')
            if conn is not None and conn.fileno() != -1:
                conn.close()

    def test_connect_limit_counts_unauthenticated_sockets(self) -> None:
        """
        Verifies that connect limit counts unauthenticated sockets.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        unauth_conn, unauth_peer = socket.socketpair()
        state.add_unauthenticated_connection(unauth_conn)
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=1),
        )
        try:
            connect_to_helper(
                cast(ConnectControllerProtocol, controller),
                'peer',
                origin=ConnectionOrigin.MANUAL,
            )

            self.assertEqual(controller.broadcast_mock.call_count, 1)
            event = controller.broadcast_mock.call_args.args[0]
            self.assertIs(event.event_type, EventType.MAX_CONNECTIONS_REACHED)
            controller.tor_manager_mock.connect.assert_not_called()
        finally:
            state.remove_unauthenticated_connection(unauth_conn)
            unauth_conn.close()
            unauth_peer.close()

    def test_retunnel_connect_failure_preserves_current_live_connection(self) -> None:
        """
        Verifies that retunnel connect failure preserves current live connection.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        active_conn, active_peer = socket.socketpair()
        state.add_active_connection('peer-onion', active_conn)
        state.mark_retunnel_started('peer-onion')
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=1, max_retries=0),
            connect_side_effect=ConnectionError('no route'),
        )
        try:
            connect_to_helper(
                cast(ConnectControllerProtocol, controller),
                'peer',
                origin=ConnectionOrigin.RETUNNEL,
            )

            self.assertIs(state.get_connection('peer-onion'), active_conn)
            events = [
                call.args[0].event_type
                for call in controller.broadcast_mock.call_args_list
            ]
            self.assertEqual(events[-1], EventType.RETUNNEL_FAILED)
            self.assertNotIn(EventType.DISCONNECTED, events)
        finally:
            conn = state.pop_any_connection('peer-onion')
            if conn is not None and conn.fileno() != -1:
                conn.close()
            active_peer.close()

    def test_retunnel_final_connect_failure_schedules_auto_reconnect(
        self,
    ) -> None:
        """
        Verifies that retunnel final connect failure schedules auto reconnect.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        state.mark_retunnel_started('peer-onion')
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(
                max_connections=1,
                max_retries=0,
                live_reconnect_delay=15,
            ),
            connect_side_effect=ConnectionError('no route'),
        )
        try:
            connect_to_helper(
                cast(ConnectControllerProtocol, controller),
                'peer',
                origin=ConnectionOrigin.RETUNNEL,
            )

            events = [
                call.args[0].event_type
                for call in controller.broadcast_mock.call_args_list
            ]

            self.assertIn(EventType.DISCONNECTED, events)
            self.assertIn(EventType.RETUNNEL_FAILED, events)
            self.assertIn(EventType.AUTO_RECONNECT_SCHEDULED, events)
            self.assertFalse(state.is_retunneling('peer-onion'))
            self.assertTrue(state.has_scheduled_auto_reconnect('peer-onion'))
            self.assertTrue(state.has_live_reconnect_grace('peer-onion'))
            self.assertEqual(controller.enqueued_live_reconnects, ['peer-onion'])
        finally:
            state.clear_scheduled_auto_reconnect('peer-onion')

    def test_connect_helper_tags_retunnel_auth_frames(self) -> None:
        """
        Verifies that connect helper tags retunnel auth frames.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=10, max_retries=0),
        )
        controller._receiver = Mock()
        conn = _NetworkSocket()
        controller.tor_manager_mock.connect = Mock(return_value=conn)

        class _ChallengeStream:
            """
            Provides a challenge stream helper for test scenarios.
            """

            def __init__(self, _conn: Any) -> None:
                """
                Initializes the challenge stream helper.

                Args:
                    _conn (Any): The conn.

                Returns:
                    None
                """

                return None

            def read_line(self) -> str:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    str: The computed return value.
                """

                return f'/challenge {"ab" * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES}'

            def get_buffer(self) -> bytes:
                """
                Returns buffer for the test scenario.

                Args:
                    None

                Returns:
                    bytes: The computed return value.
                """

                return b''

        with (
            patch.object(
                controller._crypto,
                'sign_challenge',
                return_value='signature',
            ),
            patch(
                'metor.core.daemon.managed.network.controller.session.connect.TcpStreamReader',
                _ChallengeStream,
            ),
        ):
            connect_to_helper(
                cast(ConnectControllerProtocol, controller),
                'peer',
                origin=ConnectionOrigin.RETUNNEL,
            )

        self.assertEqual(
            conn.sent,
            [b'/auth self-onion signature RECOVER\n'],
        )

    def test_connect_helper_closes_socket_after_handshake_failure(self) -> None:
        """
        Verifies that connect helper closes socket after handshake failure.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=10, max_retries=0),
        )
        conn = _NetworkSocket()
        controller.tor_manager_mock.connect = Mock(return_value=conn)

        class _InvalidChallengeStream:
            """
            Provides a invalid challenge stream helper for test scenarios.
            """

            def __init__(self, _conn: Any) -> None:
                """
                Initializes the invalid challenge stream helper.

                Args:
                    _conn (Any): The conn.

                Returns:
                    None
                """

                return None

            def read_line(self) -> str:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    str: The computed return value.
                """

                return '/msg invalid'

        with patch(
            'metor.core.daemon.managed.network.controller.session.connect.TcpStreamReader',
            _InvalidChallengeStream,
        ):
            connect_to_helper(
                cast(ConnectControllerProtocol, controller),
                'peer',
                origin=ConnectionOrigin.MANUAL,
            )

        self.assertTrue(conn.closed)
        self.assertEqual(state.get_tracked_live_socket_count(), 0)

    def test_async_drop_skips_invalid_payload_and_processes_next_message(self) -> None:
        """
        Verifies that async drop skips invalid payload and processes next message.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=cast(StateTracker, object()),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )
        payload_text = json.dumps(
            {'id': 'msg-1', 'text': 'hello', 'timestamp': '2026-04-04T12:00:00+00:00'}
        )
        payload_b64 = base64.b64encode(payload_text.encode('utf-8')).decode('utf-8')
        stream = _FakeStream(
            [
                '/drop bad not-base64!!!',
                f'/drop transport-id {payload_b64}',
                None,
            ]
        )
        conn = _DummyConn()

        router.process_async_drop(
            cast(socket.socket, conn),
            cast(TcpStreamReader, stream),
            'peer-onion',
        )

        self.assertEqual(len(message_manager.queued), 1)
        self.assertEqual(message_manager.queued[0]['msg_id'], 'msg-1')
        self.assertEqual(message_manager.queued[0]['payload'], 'hello')
        self.assertEqual(conn.sent, [b'/ack msg-1\n'])
        self.assertTrue(conn.closed)

    def test_async_drop_stops_without_ack_when_drop_backlog_limit_is_reached(
        self,
    ) -> None:
        """
        Verifies that async drop stops without ack when drop backlog limit is reached.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        message_manager.unread_drop_count = 1
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=cast(StateTracker, object()),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DropQuotaConfig(unread_drop_limit=1)),
        )
        payload_text = json.dumps(
            {'id': 'msg-2', 'text': 'blocked', 'timestamp': '2026-04-04T12:05:00+00:00'}
        )
        payload_b64 = base64.b64encode(payload_text.encode('utf-8')).decode('utf-8')
        stream = _FakeStream([f'/drop transport-id {payload_b64}', None])
        conn = _DummyConn()

        router.process_async_drop(
            cast(socket.socket, conn),
            cast(TcpStreamReader, stream),
            'peer-onion',
        )

        self.assertEqual(message_manager.queued, [])
        self.assertEqual(conn.sent, [])
        self.assertTrue(conn.closed)
        self.assertEqual(history_manager.events[0][0][0], HistoryEvent.FAILED)

    def test_live_router_disconnects_on_invalid_payload_without_ack(self) -> None:
        """
        Verifies that live router disconnects on invalid payload without ack.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=cast(StateTracker, object()),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )
        conn = _DummyConn()

        should_disconnect = router.process_incoming_msg(
            cast(socket.socket, conn),
            'peer-onion',
            'transport-id',
            'not-base64!!!',
        )

        self.assertTrue(should_disconnect)
        self.assertEqual(conn.sent, [])
        self.assertEqual(message_manager.queued, [])
        self.assertEqual(history_manager.events[0][0][0], HistoryEvent.STREAM_CORRUPTED)

    def test_send_message_without_live_connection_emits_auto_fallback_queued_event(
        self,
    ) -> None:
        """
        Verifies that send message without live connection emits auto fallback queued event.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        broadcasted: list[IpcEvent] = []

        class _ResolvedContactManager(_DummyContactManager):
            """
            Provides a resolved contact manager helper for test scenarios.
            """

            def resolve_target(self, _target: str) -> tuple[str, str]:
                """
                Resolves target for the test scenario.

                Args:
                    _target (str): The target.

                Returns:
                    tuple[str, str]: The computed return value.
                """

                return 'peer', 'peer-onion'

        class _NoLiveState:
            """
            Provides a no live state helper for test scenarios.
            """

            def get_connection(self, _onion: str) -> None:
                """
                Returns connection for the test scenario.

                Args:
                    _onion (str): The onion.

                Returns:
                    None
                """

                return None

        router = MessageRouter(
            cm=cast(ContactManager, _ResolvedContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=cast(StateTracker, _NoLiveState()),
            broadcast_callback=broadcasted.append,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )

        router.send_message('peer', 'hello', 'msg-1')

        self.assertEqual(len(message_manager.queued), 1)
        self.assertEqual(message_manager.queued[0]['msg_id'], 'msg-1')
        self.assertEqual(message_manager.queued[0]['payload'], 'hello')
        self.assertEqual(history_manager.events[0][0][0], HistoryEvent.QUEUED)
        self.assertEqual(len(broadcasted), 1)
        self.assertIsInstance(broadcasted[0], AutoFallbackQueuedEvent)
        self.assertIs(broadcasted[0].event_type, EventType.AUTO_FALLBACK_QUEUED)
        self.assertEqual(cast(AutoFallbackQueuedEvent, broadcasted[0]).msg_id, 'msg-1')

    def test_send_message_without_live_connection_stays_silent_during_reconnect_grace(
        self,
    ) -> None:
        """
        Verifies that grace-window fallback keeps chat UI noise suppressed.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        broadcasted: list[IpcEvent] = []
        state = StateTracker()
        state.mark_live_reconnect_grace('peer-onion', 1.0)

        class _ResolvedContactManager(_DummyContactManager):
            """
            Provides a resolved contact manager helper for test scenarios.
            """

            def resolve_target(self, _target: str) -> tuple[str, str]:
                """
                Resolves target for the test scenario.

                Args:
                    _target (str): The target.

                Returns:
                    tuple[str, str]: The computed return value.
                """

                return 'peer', 'peer-onion'

        router = MessageRouter(
            cm=cast(ContactManager, _ResolvedContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=state,
            broadcast_callback=broadcasted.append,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )

        router.send_message('peer', 'hello', 'msg-1')

        self.assertEqual(len(message_manager.queued), 1)
        self.assertEqual(message_manager.queued[0]['msg_id'], 'msg-1')
        self.assertEqual(message_manager.queued[0]['payload'], 'hello')
        self.assertEqual(history_manager.events[0][0][0], HistoryEvent.QUEUED)
        self.assertEqual(broadcasted, [])

    def test_live_ack_carries_original_request_id_from_state_tracker(self) -> None:
        """
        Verifies that live ack carries original request ID from state tracker.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        broadcasted: list[IpcEvent] = []
        state = StateTracker()
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=state,
            broadcast_callback=broadcasted.append,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-04T12:00:00+00:00',
        )
        state.remember_message_request_id('msg-1', 'req-live-1')

        router.process_incoming_ack('peer-onion', 'msg-1')

        self.assertEqual(len(broadcasted), 1)
        self.assertIsInstance(broadcasted[0], AckEvent)
        self.assertEqual(cast(AckEvent, broadcasted[0]).request_id, 'req-live-1')
        self.assertIsNone(state.pop_message_request_id('msg-1'))

    def test_send_drop_command_tracks_request_id_for_later_outbox_ack(self) -> None:
        """
        Verifies that send drop command tracks request ID for later outbox ack.

        Args:
            None

        Returns:
            None
        """

        contact_manager = Mock()
        contact_manager.resolve_target_for_interaction.return_value = (
            'peer',
            'peer-onion',
        )
        contact_manager.get_onion_by_alias.return_value = None
        tor_manager = Mock()
        tor_manager.onion = 'self-onion'
        message_manager = Mock()
        history_manager = Mock()
        network_manager = Mock()
        outbox_worker = Mock()
        sent_events: list[IpcEvent] = []
        handler = NetworkCommandHandler(
            tm=cast(TorManager, tor_manager),
            cm=cast(ContactManager, contact_manager),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            network=cast(Any, network_manager),
            outbox=cast(OutboxWorker, outbox_worker),
            broadcast_cb=lambda _event: None,
            send_to_cb=lambda _conn, event: sent_events.append(event),
            register_live_consumer_cb=lambda _conn: None,
            config=cast(Config, _DummyConfig()),
        )
        command = SendDropCommand(
            target='peer',
            text='hello',
            msg_id='msg-1',
            request_id='req-drop-1',
        )

        with request_context(command.request_id):
            handler.handle(command, cast(socket.socket, object()))

        outbox_worker.remember_message_request_id.assert_called_once_with(
            'msg-1',
            'req-drop-1',
        )
        self.assertEqual(len(sent_events), 1)
        self.assertIs(sent_events[0].event_type, EventType.DROP_QUEUED)
        self.assertEqual(sent_events[0].request_id, 'req-drop-1')

    def test_outbox_drop_ack_carries_original_request_id_from_state_tracker(
        self,
    ) -> None:
        """
        Verifies that outbox drop ack carries original request ID from state tracker.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        state.remember_message_request_id('msg-1', 'req-drop-ack-1')
        broadcasted: list[IpcEvent] = []
        worker = OutboxWorker(
            tm=cast(TorManager, Mock(onion='self-onion')),
            mm=cast(MessageManager, Mock()),
            hm=cast(HistoryManager, Mock()),
            crypto=cast(Crypto, Mock()),
            broadcast_callback=broadcasted.append,
            stop_flag=threading.Event(),
            config=cast(Config, _DummyConfig()),
            state=state,
        )
        conn = _NetworkSocket()

        with patch.object(
            worker,
            '_establish_tunnel',
            return_value=(
                cast(socket.socket, conn),
                cast(TcpStreamReader, _FakeStream(['/ack msg-1'])),
            ),
        ):
            worker._send_single_drop(
                'peer-onion',
                (
                    1,
                    'peer-onion',
                    'out',
                    'hello',
                    'msg-1',
                    '2026-04-04T12:00:00+00:00',
                ),
            )

        self.assertEqual(len(broadcasted), 1)
        self.assertIsInstance(broadcasted[0], AckEvent)
        self.assertEqual(
            cast(AckEvent, broadcasted[0]).request_id,
            'req-drop-ack-1',
        )
        self.assertIsNone(state.pop_message_request_id('msg-1'))

    def test_tcp_stream_reader_preserves_partial_buffer_bytes(self) -> None:
        """
        Verifies that TCP stream reader preserves partial buffer bytes.

        Args:
            None

        Returns:
            None
        """

        writer, reader = socket.socketpair()
        try:
            writer.sendall(b'/msg abc payload\nrest\xe2')
            writer.shutdown(socket.SHUT_WR)

            stream = TcpStreamReader(reader)

            self.assertEqual(stream.read_line(), '/msg abc payload')
            self.assertEqual(stream.get_buffer(), b'rest\xe2')
        finally:
            writer.close()
            reader.close()

    def test_add_pending_connection_rejects_shadow_socket_when_active_exists(
        self,
    ) -> None:
        """
        Verifies that add pending connection rejects shadow socket when active exists.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        active_conn, active_peer = socket.socketpair()
        pending_conn, pending_peer = socket.socketpair()
        try:
            state.add_active_connection('peer', active_conn)

            added = state.add_pending_connection(
                'peer',
                pending_conn,
                b'',
                reason=PendingConnectionReason.USER_ACCEPT,
                origin=ConnectionOrigin.INCOMING,
            )

            self.assertFalse(added)
            self.assertEqual(pending_conn.fileno(), -1)
        finally:
            active_peer.close()
            pending_peer.close()
            if active_conn.fileno() != -1:
                active_conn.close()

    def test_pop_any_connection_closes_shadow_pending_socket(self) -> None:
        """
        Verifies that pop any connection closes shadow pending socket.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        active_conn, active_peer = socket.socketpair()
        pending_conn, pending_peer = socket.socketpair()
        try:
            state._connections['peer'] = active_conn
            state._pending_connections['peer'] = pending_conn
            state._initial_buffers['peer'] = b'rest'
            state._pending_connection_reasons['peer'] = (
                PendingConnectionReason.USER_ACCEPT
            )
            state._pending_connection_origins['peer'] = ConnectionOrigin.INCOMING

            conn = state.pop_any_connection('peer')

            self.assertIs(conn, active_conn)
            self.assertEqual(pending_conn.fileno(), -1)
        finally:
            active_peer.close()
            pending_peer.close()
            if active_conn.fileno() != -1:
                active_conn.close()

    def test_handshake_protocol_rejects_non_challenge_frame(self) -> None:
        """
        Verifies that handshake protocol rejects non challenge frame.

        Args:
            None

        Returns:
            None
        """

        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_challenge_line('/msg deadbeef')

    def test_handshake_protocol_rejects_wrong_challenge_length(self) -> None:
        """
        Verifies that handshake protocol rejects wrong challenge length.

        Args:
            None

        Returns:
            None
        """

        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_challenge_line(
                f'/challenge {"ab" * (Constants.TOR_HANDSHAKE_CHALLENGE_BYTES - 1)}'
            )

    def test_handshake_protocol_rejects_auth_frame_with_extra_tokens(self) -> None:
        """
        Verifies that handshake protocol rejects auth frame with extra tokens.

        Args:
            None

        Returns:
            None
        """

        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_auth_line('/auth peer sig ASYNC extra')

    def test_handshake_protocol_round_trips_recovery_auth_hints(self) -> None:
        """
        Verifies that handshake protocol round trips recovery auth hints.

        Args:
            None

        Returns:
            None
        """

        for origin in (
            ConnectionOrigin.AUTO_RECONNECT,
            ConnectionOrigin.RETUNNEL,
        ):
            auth_line = HandshakeProtocol.build_auth_line(
                'peer-onion',
                'signature',
                origin=origin,
            )

            parsed = HandshakeProtocol.parse_auth_line(auth_line)

            self.assertEqual(
                parsed,
                ('peer-onion', 'signature', False, True),
            )

    def test_handshake_protocol_rejects_unsupported_recovery_hint(self) -> None:
        """
        Verifies that handshake protocol rejects unsupported recovery hint.

        Args:
            None

        Returns:
            None
        """

        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_auth_line(
                f'/auth peer sig {ConnectionOrigin.MANUAL.value}'
            )

    def test_crypto_verify_signature_rejects_invalid_onion_checksum(self) -> None:
        """
        Verifies that crypto verify signature rejects invalid onion checksum.

        Args:
            None

        Returns:
            None
        """

        seed = b'\x42' * 32
        public_key, secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)
        crypto = Crypto(cast(KeyManager, _DummyKeyManager(secret_key)))
        challenge = 'ab' * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES
        signature = crypto.sign_challenge(challenge)

        self.assertIsNotNone(signature)

        version = bytes([Constants.TOR_V3_VERSION_BYTE])
        valid_onion = self._build_v3_onion(
            public_key,
            self._build_v3_checksum(public_key, version),
            version,
        )
        invalid_onion = self._build_v3_onion(public_key, b'\x00\x00', version)

        assert signature is not None
        self.assertTrue(crypto.verify_signature(valid_onion, challenge, signature))
        self.assertFalse(crypto.verify_signature(invalid_onion, challenge, signature))

    def test_crypto_verify_signature_rejects_invalid_onion_version(self) -> None:
        """
        Verifies that crypto verify signature rejects invalid onion version.

        Args:
            None

        Returns:
            None
        """

        seed = b'\x24' * 32
        public_key, secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)
        crypto = Crypto(cast(KeyManager, _DummyKeyManager(secret_key)))
        challenge = 'cd' * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES
        signature = crypto.sign_challenge(challenge)

        self.assertIsNotNone(signature)

        invalid_version = b'\x04'
        onion = self._build_v3_onion(
            public_key,
            self._build_v3_checksum(public_key, invalid_version),
            invalid_version,
        )

        assert signature is not None
        self.assertFalse(crypto.verify_signature(onion, challenge, signature))

    def test_receiver_accepts_zero_argument_disconnect(self) -> None:
        """
        Verifies that receiver accepts zero argument disconnect.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _DummyState()),
            router=cast(MessageRouter, _DummyRouterReceiver()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )
        writer, reader = socket.socketpair()
        try:
            writer.sendall(b'/disconnect\n')
            writer.shutdown(socket.SHUT_WR)

            receiver._receiver_target(
                'peer-onion',
                reader,
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

            self.assertEqual(len(disconnect_calls), 1)
            self.assertEqual(disconnect_calls[0][0], 'peer-onion')
            self.assertFalse(disconnect_calls[0][1])
            self.assertFalse(disconnect_calls[0][2])
            self.assertEqual(reject_calls, [])
        finally:
            writer.close()
            if reader.fileno() != -1:
                reader.close()

    def test_receiver_ignores_malformed_ack_frame(self) -> None:
        """
        Verifies that receiver ignores malformed ack frame.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        acked_msg_ids: list[str] = []

        class _AckTrackingRouter:
            """
            Provides a ack tracking router helper for test scenarios.
            """

            def process_incoming_ack(self, _onion: str, msg_id: str) -> None:
                """
                Executes process incoming ack for the test scenario.

                Args:
                    _onion (str): The onion.
                    msg_id (str): The msg ID.

                Returns:
                    None
                """

                acked_msg_ids.append(msg_id)

            def process_incoming_msg(
                self,
                _conn: socket.socket,
                _onion: str,
                _payload_id: str,
                _b64_payload: str,
            ) -> bool:
                """
                Executes process incoming msg for the test scenario.

                Args:
                    _conn (socket.socket): The conn.
                    _onion (str): The onion.
                    _payload_id (str): The payload ID.
                    _b64_payload (str): The b64 payload.

                Returns:
                    bool: The computed return value.
                """

                return False

        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _DummyState()),
            router=cast(MessageRouter, _AckTrackingRouter()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )
        writer, reader = socket.socketpair()
        try:
            writer.sendall(b'/ack msg-1 extra\n/disconnect\n')
            writer.shutdown(socket.SHUT_WR)

            receiver._receiver_target(
                'peer-onion',
                reader,
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

            self.assertEqual(acked_msg_ids, [])
            self.assertEqual(len(disconnect_calls), 1)
            self.assertEqual(reject_calls, [])
        finally:
            writer.close()
            if reader.fileno() != -1:
                reader.close()

    def test_receiver_ignores_idle_timeout_for_active_live_socket(self) -> None:
        """
        Verifies that receiver ignores idle timeout for active live socket.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _DummyState()),
            router=cast(MessageRouter, _DummyRouterReceiver()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )
        conn = _DummyReceiverSocket()

        class _PatchedStream:
            """
            Provides a patched stream helper for test scenarios.
            """

            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                """
                Initializes the patched stream helper.

                Args:
                    _conn (Any): The conn.
                    _initial_buffer (bytes): The initial buffer.

                Returns:
                    None
                """

                self._actions: list[object] = [socket.timeout(), '/disconnect']

            def read_line(self) -> Optional[str]:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    Optional[str]: The computed return value.
                """

                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return cast(Optional[str], action)

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                cast(socket.socket, conn),
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertFalse(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])

    def test_receiver_exits_idle_timeout_for_unknown_socket(self) -> None:
        """
        Verifies that receiver exits idle timeout for unknown socket.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []

        class _UnknownSocketState(_DummyState):
            """
            Provides a unknown socket state helper for test scenarios.
            """

            def is_known_socket(self, _onion: str, _conn: socket.socket) -> bool:
                """
                Reports whether the helper is known socket.

                Args:
                    _onion (str): The onion.
                    _conn (socket.socket): The conn.

                Returns:
                    bool: The computed return value.
                """

                return False

        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _UnknownSocketState()),
            router=cast(MessageRouter, _DummyRouterReceiver()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )
        conn = _DummyReceiverSocket()

        class _PatchedStream:
            """
            Provides a patched stream helper for test scenarios.
            """

            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                """
                Initializes the patched stream helper.

                Args:
                    _conn (Any): The conn.
                    _initial_buffer (bytes): The initial buffer.

                Returns:
                    None
                """

                self._actions: list[object] = [socket.timeout(), '/disconnect']

            def read_line(self) -> Optional[str]:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    Optional[str]: The computed return value.
                """

                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return cast(Optional[str], action)

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                cast(socket.socket, conn),
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertTrue(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])

    def test_receiver_treats_idle_timeout_with_local_eof_as_disconnect(self) -> None:
        """
        Verifies that a known socket is torn down when an idle timeout is followed by a local EOF indication.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _DummyState()),
            router=cast(MessageRouter, _DummyRouterReceiver()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )

        class _PeekEofSocket(_DummyReceiverSocket):
            """
            Provides a receiver socket that reports EOF on peek after one idle timeout.
            """

            def recv(self, _size: int, _flags: int = 0) -> bytes:
                """
                Returns EOF for the test scenario.

                Args:
                    _size (int): The requested size.
                    _flags (int): The socket recv flags.

                Returns:
                    bytes: The computed return value.
                """

                return b''

        conn = _PeekEofSocket()

        class _PatchedStream:
            """
            Provides a patched stream helper for test scenarios.
            """

            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                """
                Initializes the patched stream helper.

                Args:
                    _conn (Any): The conn.
                    _initial_buffer (bytes): The initial buffer.

                Returns:
                    None
                """

                self._actions: list[object] = [socket.timeout()]

            def read_line(self) -> Optional[str]:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    Optional[str]: The computed return value.
                """

                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return cast(Optional[str], action)

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                cast(socket.socket, conn),
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertTrue(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])

    def test_receiver_keeps_pending_accept_timeout_behavior(self) -> None:
        """
        Verifies that receiver keeps pending accept timeout behavior.

        Args:
            None

        Returns:
            None
        """

        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=cast(ContactManager, _DummyContactManagerReceiver()),
            hm=cast(HistoryManager, _DummyHistoryManagerReceiver()),
            state=cast(StateTracker, _DummyState()),
            router=cast(MessageRouter, _DummyRouterReceiver()),
            broadcast_callback=lambda _event: None,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=cast(Config, _DummyReceiverConfig()),
        )
        conn = _DummyReceiverSocket()

        class _PatchedStream:
            """
            Provides a patched stream helper for test scenarios.
            """

            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                """
                Initializes the patched stream helper.

                Args:
                    _conn (Any): The conn.
                    _initial_buffer (bytes): The initial buffer.

                Returns:
                    None
                """

                self._actions: list[object] = [socket.timeout()]

            def read_line(self) -> Optional[str]:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    Optional[str]: The computed return value.
                """

                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return cast(Optional[str], action)

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                cast(socket.socket, conn),
                b'',
                True,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertTrue(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])

    def test_listener_accepts_remote_recovery_replacement_with_local_context(
        self,
    ) -> None:
        """
        Verifies that listener accepts remote recovery replacement only when local recovery context exists.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        state.mark_live_reconnect_grace('peer-onion', 5.0)
        listener, receiver_mock = self._build_live_listener(state)
        broadcast_mock = cast(Mock, listener._broadcast)
        router_mock = cast(Mock, listener._router)

        listener._handle_live_incoming(
            new_conn,
            cast(TcpStreamReader, _ListenerStream()),
            'peer-onion',
            True,
        )

        self.assertIs(state.get_connection('peer-onion'), new_conn)
        self.assertTrue(cast(_DummyConn, old_conn).closed)
        self.assertEqual(cast(_DummyConn, new_conn).sent, [b'/accepted\n'])
        receiver_mock.start_receiving.assert_called_once()
        router_mock.force_fallback.assert_called_once_with('peer-onion')
        router_mock.replay_unacked_messages.assert_called_once_with('peer-onion')
        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(
            event_types,
            [EventType.CONNECTION_CONNECTING, EventType.CONNECTED],
        )
        connecting_event = cast(
            ConnectionConnectingEvent, broadcast_mock.call_args_list[0].args[0]
        )
        connected_event = cast(ConnectedEvent, broadcast_mock.call_args_list[1].args[0])
        self.assertIs(connecting_event.origin, ConnectionOrigin.GRACE_RECONNECT)
        self.assertIs(connected_event.origin, ConnectionOrigin.GRACE_RECONNECT)

    def test_listener_rejects_recovery_hint_without_local_recovery_context(
        self,
    ) -> None:
        """
        Verifies that a peer recovery hint alone cannot replace an active live socket.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        listener, receiver_mock = self._build_live_listener(state)
        broadcast_mock = cast(Mock, listener._broadcast)
        router_mock = cast(Mock, listener._router)

        listener._handle_live_incoming(
            new_conn,
            cast(TcpStreamReader, _ListenerStream()),
            'peer-onion',
            True,
        )

        self.assertIs(state.get_connection('peer-onion'), old_conn)
        self.assertTrue(cast(_DummyConn, new_conn).closed)
        self.assertEqual(cast(_DummyConn, new_conn).sent, [b'/reject self-onion\n'])
        receiver_mock.start_receiving.assert_not_called()
        router_mock.force_fallback.assert_not_called()
        self.assertEqual(broadcast_mock.call_count, 0)

    def test_listener_pending_retunnel_expiry_schedules_auto_reconnect(
        self,
    ) -> None:
        """
        Verifies that pending retunnel expiry re-enters the standard auto-reconnect failure path.

        Args:
            None

        Returns:
            None
        """

        class _ListenerReconnectConfig(_ListenerTestConfig):
            """
            Provides listener config with reconnect scheduling enabled.
            """

            def get_int(self, key: Any) -> int:
                """
                Returns integer settings for the test scenario.

                Args:
                    key (Any): The requested setting key.

                Returns:
                    int: The configured integer value.
                """

                if key is SettingKey.MAX_UNSEEN_LIVE_MSGS:
                    return 0
                if key is SettingKey.LIVE_RECONNECT_DELAY:
                    return 15
                if key is SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT:
                    return 5
                return super().get_int(key)

        state = StateTracker()
        state.mark_retunnel_started('peer-onion')
        conn = cast(socket.socket, _DummyConn())
        scheduled_reconnects: list[str] = []
        broadcast_mock = Mock()

        def _enqueue_reconnect(onion: str) -> bool:
            """
            Records the scheduled reconnect for the test scenario.

            Args:
                onion (str): The reconnect target.

            Returns:
                bool: Always True for the test path.
            """

            scheduled_reconnects.append(onion)
            return True

        listener = InboundListener(
            tm=cast(TorManager, Mock(onion='self-onion')),
            cm=cast(ContactManager, Mock()),
            hm=cast(HistoryManager, Mock()),
            crypto=cast(Crypto, Mock()),
            state=state,
            router=cast(MessageRouter, Mock()),
            receiver=cast(StreamReceiver, Mock()),
            broadcast_callback=broadcast_mock,
            has_live_consumers_callback=lambda: False,
            enqueue_live_reconnect_callback=_enqueue_reconnect,
            stop_flag=threading.Event(),
            config=cast(Config, _ListenerReconnectConfig()),
        )
        state.add_pending_connection(
            'peer-onion',
            conn,
            b'',
            reason=PendingConnectionReason.CONSUMER_ABSENT,
            origin=ConnectionOrigin.RETUNNEL,
        )

        with patch(
            'metor.core.daemon.managed.network.listener.time.time',
            side_effect=[100.0, 100.3, 100.3, 100.3],
        ):
            listener._watch_pending_connection('peer-onion', 'peer', conn)

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(
            event_types,
            [
                EventType.DISCONNECTED,
                EventType.RETUNNEL_FAILED,
                EventType.AUTO_RECONNECT_SCHEDULED,
            ],
        )
        self.assertEqual(scheduled_reconnects, ['peer-onion'])
        self.assertTrue(state.has_scheduled_auto_reconnect('peer-onion'))

    def test_remote_fallback_disconnect_defers_noise_until_reconnect_grace_expires(
        self,
    ) -> None:
        """
        Verifies that remote fallback disconnect stays silent until grace expires.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        controller = _DisconnectControllerHarness(state, cast(Config, _DummyConfig()))
        broadcast_mock = cast(Mock, controller._broadcast)
        history_manager = cast(_DummyHistoryManager, controller._hm)
        scheduled_threads: list[tuple[Any, tuple[Any, ...]]] = []

        class _CapturedThread:
            """
            Captures a deferred thread target for manual execution.
            """

            def __init__(self, target: Any, args: tuple[Any, ...]) -> None:
                """
                Initializes the captured thread helper.

                Args:
                    target (Any): The deferred target.
                    args (tuple[Any, ...]): The deferred arguments.

                Returns:
                    None
                """

                self._target = target
                self._args = args

            def start(self) -> None:
                """
                Captures the deferred target instead of executing it.

                Args:
                    None

                Returns:
                    None
                """

                scheduled_threads.append((self._target, self._args))

        def _thread_factory(*args: Any, **kwargs: Any) -> _CapturedThread:
            """
            Creates captured-thread helpers for the test scenario.

            Args:
                *args (Any): Ignored positional arguments.
                **kwargs (Any): Thread keyword arguments.

            Returns:
                _CapturedThread: The computed return value.
            """

            del args
            return _CapturedThread(kwargs['target'], kwargs.get('args', ()))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.threading.Thread',
            side_effect=_thread_factory,
        ):
            disconnect_helper(
                controller,
                'peer',
                initiated_by_self=False,
                is_fallback=True,
                socket_to_close=conn,
                origin=ConnectionOrigin.INCOMING,
            )

        self.assertTrue(cast(_DummyConn, conn).closed)
        self.assertEqual(broadcast_mock.call_count, 1)
        self.assertIsInstance(
            cast(IpcEvent, broadcast_mock.call_args_list[0].args[0]),
            ConnectionConnectingEvent,
        )
        self.assertEqual(history_manager.events, [])
        self.assertEqual(controller.enqueued_live_reconnects, [])
        self.assertEqual(len(scheduled_threads), 1)
        self.assertTrue(state.has_live_reconnect_grace('peer-onion'))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.time.sleep',
            side_effect=lambda _seconds: None,
        ):
            target, args = scheduled_threads[0]
            target(*args)

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(
            event_types,
            [
                EventType.CONNECTION_CONNECTING,
                EventType.DISCONNECTED,
                EventType.AUTO_RECONNECT_SCHEDULED,
            ],
        )
        self.assertEqual(controller.enqueued_live_reconnects, ['peer-onion'])

    def test_remote_fallback_disconnect_keeps_unacked_live_messages_during_grace(
        self,
    ) -> None:
        """
        Verifies that recoverable fallback keeps unacked live messages pending.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-28T14:24:09',
        )
        controller = _DisconnectControllerHarness(state, cast(Config, _DummyConfig()))
        broadcast_mock = cast(Mock, controller._broadcast)

        class _CapturedThread:
            """
            Captures the deferred thread target for manual execution.
            """

            def __init__(self, target: Any, args: tuple[Any, ...]) -> None:
                """
                Initializes the captured thread helper.

                Args:
                    target (Any): The deferred target.
                    args (tuple[Any, ...]): The deferred arguments.

                Returns:
                    None
                """

                self._target = target
                self._args = args

            def start(self) -> None:
                """
                Suppresses deferred execution for the immediate assertion window.

                Args:
                    None

                Returns:
                    None
                """

                return None

        def _thread_factory(*args: Any, **kwargs: Any) -> _CapturedThread:
            """
            Creates captured-thread helpers for the test scenario.

            Args:
                *args (Any): Ignored positional arguments.
                **kwargs (Any): Thread keyword arguments.

            Returns:
                _CapturedThread: The computed return value.
            """

            del args
            return _CapturedThread(kwargs['target'], kwargs.get('args', ()))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.threading.Thread',
            side_effect=_thread_factory,
        ):
            disconnect_helper(
                controller,
                'peer',
                initiated_by_self=False,
                is_fallback=True,
                socket_to_close=conn,
                origin=ConnectionOrigin.INCOMING,
            )

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(event_types, [EventType.CONNECTION_CONNECTING])
        self.assertTrue(state.has_unacked_messages('peer-onion'))

    def test_remote_fallback_disconnect_stays_silent_when_replacement_arrives_in_time(
        self,
    ) -> None:
        """
        Verifies that delayed fallback noise is cancelled when recovery reconnect wins.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        replacement_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        controller = _DisconnectControllerHarness(state, cast(Config, _DummyConfig()))
        broadcast_mock = cast(Mock, controller._broadcast)
        scheduled_threads: list[tuple[Any, tuple[Any, ...]]] = []

        class _CapturedThread:
            """
            Captures a deferred thread target for manual execution.
            """

            def __init__(self, target: Any, args: tuple[Any, ...]) -> None:
                """
                Initializes the captured thread helper.

                Args:
                    target (Any): The deferred target.
                    args (tuple[Any, ...]): The deferred arguments.

                Returns:
                    None
                """

                self._target = target
                self._args = args

            def start(self) -> None:
                """
                Captures the deferred target instead of executing it.

                Args:
                    None

                Returns:
                    None
                """

                scheduled_threads.append((self._target, self._args))

        def _thread_factory(*args: Any, **kwargs: Any) -> _CapturedThread:
            """
            Creates captured-thread helpers for the test scenario.

            Args:
                *args (Any): Ignored positional arguments.
                **kwargs (Any): Thread keyword arguments.

            Returns:
                _CapturedThread: The computed return value.
            """

            del args
            return _CapturedThread(kwargs['target'], kwargs.get('args', ()))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.threading.Thread',
            side_effect=_thread_factory,
        ):
            disconnect_helper(
                controller,
                'peer',
                initiated_by_self=False,
                is_fallback=True,
                socket_to_close=conn,
                origin=ConnectionOrigin.INCOMING,
            )

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(event_types, [EventType.CONNECTION_CONNECTING])

        state.add_active_connection('peer-onion', replacement_conn)

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.time.sleep',
            side_effect=lambda _seconds: None,
        ):
            target, args = scheduled_threads[0]
            target(*args)

        self.assertEqual(broadcast_mock.call_count, 1)
        self.assertEqual(controller.enqueued_live_reconnects, [])

    def test_remote_fallback_finalizer_stays_silent_while_outbound_attempt_is_in_flight(
        self,
    ) -> None:
        """
        Verifies that deferred fallback does not emit disconnect noise while a new outbound attempt is already running.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        controller = _DisconnectControllerHarness(state, cast(Config, _DummyConfig()))
        broadcast_mock = cast(Mock, controller._broadcast)
        scheduled_threads: list[tuple[Any, tuple[Any, ...]]] = []

        class _CapturedThread:
            """
            Captures a deferred thread target for manual execution.
            """

            def __init__(self, target: Any, args: tuple[Any, ...]) -> None:
                """
                Initializes the captured thread helper.

                Args:
                    target (Any): The deferred target.
                    args (tuple[Any, ...]): The deferred arguments.

                Returns:
                    None
                """

                self._target = target
                self._args = args

            def start(self) -> None:
                """
                Captures the deferred target instead of executing it.

                Args:
                    None

                Returns:
                    None
                """

                scheduled_threads.append((self._target, self._args))

        def _thread_factory(*args: Any, **kwargs: Any) -> _CapturedThread:
            """
            Creates captured-thread helpers for the test scenario.

            Args:
                *args (Any): Ignored positional arguments.
                **kwargs (Any): Thread keyword arguments.

            Returns:
                _CapturedThread: The computed return value.
            """

            del args
            return _CapturedThread(kwargs['target'], kwargs.get('args', ()))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.threading.Thread',
            side_effect=_thread_factory,
        ):
            disconnect_helper(
                controller,
                'peer',
                initiated_by_self=False,
                is_fallback=True,
                socket_to_close=conn,
                origin=ConnectionOrigin.INCOMING,
            )

        state.add_outbound_attempt('peer-onion', origin=ConnectionOrigin.MANUAL)

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.time.sleep',
            side_effect=lambda _seconds: None,
        ):
            target, args = scheduled_threads[0]
            target(*args)

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(event_types, [EventType.CONNECTION_CONNECTING])
        self.assertEqual(controller.enqueued_live_reconnects, [])

    def test_discard_outbound_attempt_clears_recent_mutual_connect_window(self) -> None:
        """
        Verifies that clearing an outbound attempt also clears the recent race marker.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())

        state.bind_outbound_socket('peer-onion', conn)
        self.assertTrue(state.has_active_or_recent_outbound_attempt('peer-onion'))

        state.discard_outbound_attempt('peer-onion')

        self.assertFalse(state.has_active_or_recent_outbound_attempt('peer-onion'))

    def test_remote_fallback_grace_expiry_without_auto_reconnect_keeps_unacked_live_messages(
        self,
    ) -> None:
        """
        Verifies that grace expiry without local auto reconnect keeps unacked live messages retained.

        Args:
            None

        Returns:
            None
        """

        class _NoAutoReconnectConfig(_DummyConfig):
            """
            Provides one config that disables local auto reconnect for the test.
            """

            def get_int(self, key: Any) -> int:
                """
                Returns integer settings for the test scenario.

                Args:
                    key (Any): The requested setting key.

                Returns:
                    int: The configured integer value.
                """

                if key is SettingKey.LIVE_RECONNECT_DELAY:
                    return 0
                if key is SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT:
                    return 1
                return super().get_int(key)

        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-28T16:13:02',
        )
        controller = _DisconnectControllerHarness(
            state,
            cast(Config, _NoAutoReconnectConfig()),
        )
        broadcast_mock = cast(Mock, controller._broadcast)
        scheduled_threads: list[tuple[Any, tuple[Any, ...]]] = []

        class _CapturedThread:
            """
            Captures a deferred thread target for manual execution.
            """

            def __init__(self, target: Any, args: tuple[Any, ...]) -> None:
                """
                Initializes the captured thread helper.

                Args:
                    target (Any): The deferred target.
                    args (tuple[Any, ...]): The deferred arguments.

                Returns:
                    None
                """

                self._target = target
                self._args = args

            def start(self) -> None:
                """
                Captures the deferred target instead of executing it.

                Args:
                    None

                Returns:
                    None
                """

                scheduled_threads.append((self._target, self._args))

        def _thread_factory(*args: Any, **kwargs: Any) -> _CapturedThread:
            """
            Creates captured-thread helpers for the test scenario.

            Args:
                *args (Any): Ignored positional arguments.
                **kwargs (Any): Thread keyword arguments.

            Returns:
                _CapturedThread: The computed return value.
            """

            del args
            return _CapturedThread(kwargs['target'], kwargs.get('args', ()))

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.threading.Thread',
            side_effect=_thread_factory,
        ):
            disconnect_helper(
                controller,
                'peer',
                initiated_by_self=False,
                is_fallback=True,
                socket_to_close=conn,
                origin=ConnectionOrigin.INCOMING,
            )

        with patch(
            'metor.core.daemon.managed.network.controller.session.terminate.time.sleep',
            side_effect=lambda _seconds: None,
        ):
            target, args = scheduled_threads[0]
            target(*args)

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in broadcast_mock.call_args_list
        ]
        self.assertEqual(
            event_types,
            [
                EventType.CONNECTION_CONNECTING,
                EventType.DISCONNECTED,
            ],
        )
        self.assertTrue(state.has_unacked_messages('peer-onion'))

    def test_auto_reconnect_terminal_failure_converts_retained_unacked_to_drop(
        self,
    ) -> None:
        """
        Verifies that retained unacked live messages become drops only after reconnect fails terminally.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-28T15:46:44',
        )
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(
                max_connections=10, max_retries=0, live_reconnect_delay=1
            ),
            connect_side_effect=ConnectionError('boom'),
        )

        connect_to_helper(
            controller,
            'peer',
            origin=ConnectionOrigin.AUTO_RECONNECT,
        )

        event_types = [
            cast(IpcEvent, call.args[0]).event_type
            for call in controller.broadcast_mock.call_args_list
        ]
        self.assertEqual(
            event_types,
            [
                EventType.CONNECTION_CONNECTING,
                EventType.FALLBACK_SUCCESS,
                EventType.CONNECTION_FAILED,
            ],
        )
        self.assertFalse(state.has_unacked_messages('peer-onion'))

    def test_router_replays_unacked_messages_over_recovered_live_socket(self) -> None:
        """
        Verifies that retained unacked live messages are replayed over the recovered socket.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        state = StateTracker()
        conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', conn)
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-28T15:46:44',
        )
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )

        replayed_msg_ids = router.replay_unacked_messages('peer-onion')

        self.assertEqual(replayed_msg_ids, ['msg-1'])
        self.assertEqual(len(cast(_DummyConn, conn).sent), 1)
        self.assertTrue(cast(_DummyConn, conn).sent[0].startswith(b'/msg msg-1 '))
        self.assertTrue(state.has_unacked_messages('peer-onion'))

    def test_router_convert_unacked_messages_to_drop_uses_drop_type(self) -> None:
        """
        Verifies that router-side fallback persists converted live messages as drop rows.

        Args:
            None

        Returns:
            None
        """

        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        state = StateTracker()
        state.add_unacked_message(
            'peer-onion',
            'msg-1',
            'hello',
            '2026-04-28T15:46:44',
        )
        router = MessageRouter(
            cm=cast(ContactManager, _DummyContactManager()),
            hm=cast(HistoryManager, history_manager),
            mm=cast(MessageManager, message_manager),
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=cast(Config, _DummyConfig()),
        )

        router.convert_unacked_messages_to_drop(
            'peer',
            'peer-onion',
            emit_event=False,
        )

        self.assertEqual(message_manager.queued[0]['msg_type'], MessageType.DROP_TEXT)

    def test_listener_tracks_remote_auto_reconnect_replacement_as_pending(
        self,
    ) -> None:
        """
        Verifies that listener tracks remote auto reconnect replacement as pending.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        state.mark_live_reconnect_grace('peer-onion', 5.0)
        listener, receiver_mock = self._build_live_listener(
            state,
            allow_headless_live_backlog=False,
            has_live_consumers=False,
        )
        broadcast_mock = cast(Mock, listener._broadcast)

        with patch(
            'metor.core.daemon.managed.network.listener.threading.Thread',
            return_value=_PassiveThread(),
        ):
            listener._handle_live_incoming(
                new_conn,
                cast(TcpStreamReader, _ListenerStream(b'recovery-buffer')),
                'peer-onion',
                True,
            )

        self.assertIs(state.get_connection('peer-onion'), old_conn)
        pending_conn, initial_buffer, reason, origin = state.pop_pending_connection(
            'peer-onion'
        )
        self.assertIs(pending_conn, new_conn)
        self.assertEqual(initial_buffer, b'recovery-buffer')
        self.assertIs(reason, PendingConnectionReason.CONSUMER_ABSENT)
        self.assertIs(origin, ConnectionOrigin.GRACE_RECONNECT)
        self.assertEqual(cast(_DummyConn, new_conn).sent, [b'/pending\n'])
        receiver_mock.start_receiving.assert_not_called()
        self.assertEqual(broadcast_mock.call_count, 0)

    def test_listener_rejects_plain_duplicate_incoming_when_live_is_active(
        self,
    ) -> None:
        """
        Verifies that listener rejects plain duplicate incoming when live is active.

        Args:
            None

        Returns:
            None
        """

        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        listener, receiver_mock = self._build_live_listener(state)
        broadcast_mock = cast(Mock, listener._broadcast)

        listener._handle_live_incoming(
            new_conn,
            cast(TcpStreamReader, _ListenerStream()),
            'peer-onion',
        )

        self.assertIs(state.get_connection('peer-onion'), old_conn)
        self.assertTrue(cast(_DummyConn, new_conn).closed)
        self.assertEqual(receiver_mock.start_receiving.call_count, 0)
        self.assertEqual(broadcast_mock.call_count, 0)
        self.assertEqual(len(cast(_DummyConn, new_conn).sent), 1)
        self.assertTrue(cast(_DummyConn, new_conn).sent[0].startswith(b'/reject '))

    def test_outbox_establish_tunnel_closes_socket_after_handshake_failure(
        self,
    ) -> None:
        """
        Verifies that outbox establish tunnel closes socket after handshake failure.

        Args:
            None

        Returns:
            None
        """

        conn = _NetworkSocket()
        tor_manager = Mock()
        tor_manager.connect.return_value = conn
        tor_manager.onion = 'self-onion'
        worker = OutboxWorker(
            tm=cast(TorManager, tor_manager),
            mm=cast(MessageManager, object()),
            hm=cast(HistoryManager, object()),
            crypto=cast(Crypto, Mock()),
            broadcast_callback=lambda _event: None,
            stop_flag=threading.Event(),
            config=cast(Config, _DummyConfig()),
        )

        class _InvalidChallengeStream:
            """
            Provides a invalid challenge stream helper for test scenarios.
            """

            def __init__(self, _conn: Any) -> None:
                """
                Initializes the invalid challenge stream helper.

                Args:
                    _conn (Any): The conn.

                Returns:
                    None
                """

                return None

            def read_line(self) -> str:
                """
                Reads line from the helper stream.

                Args:
                    None

                Returns:
                    str: The computed return value.
                """

                return '/msg invalid'

        with patch(
            'metor.core.daemon.managed.outbox.TcpStreamReader',
            _InvalidChallengeStream,
        ):
            result = worker._establish_tunnel('peer-onion')

        self.assertIsNone(result)
        self.assertTrue(conn.closed)


if __name__ == '__main__':
    unittest.main()
