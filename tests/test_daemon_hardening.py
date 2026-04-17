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
    ConnectionOrigin,
    EventType,
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
from metor.core.daemon.managed.network.controller.session.protocols import (
    ConnectControllerProtocol,
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
    SettingKey,
)
from metor.data.profile import ProfileManager
from metor.data.profile.config import Config
from metor.ui.chat.ipc import IpcClient
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.theme import Theme
from metor.utils import Constants


class _DummyConfig:
    def get_bool(self, _key: Any) -> bool:
        return True

    def get_int(self, _key: Any) -> int:
        return 1

    def get_float(self, _key: Any) -> float:
        return 0.2


class _DropQuotaConfig(_DummyConfig):
    def __init__(self, unread_drop_limit: int) -> None:
        self._unread_drop_limit: int = unread_drop_limit

    def get_int(self, key: Any) -> int:
        if key is SettingKey.MAX_UNSEEN_DROP_MSGS:
            return self._unread_drop_limit
        return super().get_int(key)


class _DummyProfileManager:
    def __init__(self) -> None:
        self.config: _DummyConfig = _DummyConfig()
        self.initialized: bool = False

    def initialize(self) -> None:
        self.initialized = True

    def uses_plaintext_storage(self) -> bool:
        return False

    def uses_encrypted_storage(self) -> bool:
        return True

    def get_static_port(self) -> None:
        return None

    def set_daemon_port(self, _port: int, _pid: int) -> None:
        return None


class _PlaintextProfileManager(_DummyProfileManager):
    def uses_plaintext_storage(self) -> bool:
        return True

    def uses_encrypted_storage(self) -> bool:
        return False


class _DummyEvent:
    def to_json(self) -> str:
        return json.dumps({'event_type': 'test'})


class _InspectingSocket:
    def __init__(self, server: IpcServer) -> None:
        self._server: IpcServer = server
        self.lock_was_held: Optional[bool] = None
        self.payloads: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        self.lock_was_held = self._server._lock.locked()
        self.payloads.append(payload)

    def close(self) -> None:
        return None


class _QueueResult:
    def __init__(self, was_duplicate: bool = False) -> None:
        self.was_duplicate: bool = was_duplicate


class _DummyContactManager:
    def ensure_alias_for_onion(self, _onion: str) -> str:
        return 'peer'

    def resolve_target(self, _target: str) -> None:
        return None


class _DummyHistoryManager:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def log_event(self, *args: Any, **kwargs: Any) -> None:
        self.events.append((args, kwargs))


class _DummyMessageManager:
    def __init__(self) -> None:
        self.queued: list[dict[str, Any]] = []
        self.unread_drop_count: int = 0

    def queue_message(self, **kwargs: Any) -> _QueueResult:
        self.queued.append(kwargs)
        return _QueueResult()

    def has_inbound_message(self, _onion: str, _msg_id: str) -> bool:
        return False

    def get_unread_live_count(self, _onion: str) -> int:
        return 0

    def get_unread_drop_count(self, _onion: str) -> int:
        return self.unread_drop_count


class _DummyConn:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed: bool = False

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


class _NetworkSocket:
    def __init__(self) -> None:
        self.closed: bool = False
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


class _AcceptedClientSocket:
    def __init__(self) -> None:
        self.closed: bool = False
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


class _AcceptorSocket:
    def __init__(self, accepted_connections: list[_AcceptedClientSocket]) -> None:
        self._accepted_connections: list[_AcceptedClientSocket] = accepted_connections
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def accept(self) -> tuple[_AcceptedClientSocket, tuple[str, int]]:
        conn = self._accepted_connections.pop(0)
        return conn, ('127.0.0.1', 0)


class _StopAfterRejectSocket:
    def __init__(self, server: IpcServer, conn: _AcceptedClientSocket) -> None:
        self._server: IpcServer = server
        self._conn: _AcceptedClientSocket = conn
        self._accepted: bool = False
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def accept(self) -> tuple[_AcceptedClientSocket, tuple[str, int]]:
        if not self._accepted:
            self._accepted = True
            return self._conn, ('127.0.0.1', 0)

        self._server._stop_flag.set()
        raise OSError('stop accept loop')


class _ThreadStartHandle:
    def __init__(self, index: int, server: IpcServer) -> None:
        self._index: int = index
        self._server: IpcServer = server

    def start(self) -> None:
        if self._index == 1:
            raise RuntimeError('thread start failed')
        self._server._stop_flag.set()


class _ThreadStartFactory:
    def __init__(self, server: IpcServer) -> None:
        self._server: IpcServer = server
        self.calls: int = 0

    def __call__(self, *args: Any, **kwargs: Any) -> _ThreadStartHandle:
        del args, kwargs
        self.calls += 1
        return _ThreadStartHandle(self.calls, self._server)


class _PassiveThread:
    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return False


class _ImmediateListenerThread:
    def __init__(self, target: Any) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class _ImmediateListenerThreadFactory:
    def __call__(self, *args: Any, **kwargs: Any) -> _ImmediateListenerThread:
        del args
        return _ImmediateListenerThread(kwargs['target'])


class _FakeChatIpcSocket:
    def __init__(self, recv_items: list[object]) -> None:
        self._recv_items: list[object] = recv_items
        self.connected_to: Optional[tuple[str, int]] = None
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []
        self.closed: bool = False
        self.shutdown_called: bool = False

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def connect(self, address: tuple[str, int]) -> None:
        self.connected_to = address

    def recv(self, _size: int) -> bytes:
        item = self._recv_items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return cast(bytes, item)

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def shutdown(self, _how: int) -> None:
        self.shutdown_called = True

    def close(self) -> None:
        self.closed = True


class _FaultingOutboxMessageManager:
    def __init__(self, stop_flag: threading.Event) -> None:
        self._stop_flag: threading.Event = stop_flag
        self.calls: int = 0

    def get_pending_outbox(self) -> list[tuple[int, str, str, str, str, str]]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('boom')

        self._stop_flag.set()
        return []


class _DummyKeyManager:
    def __init__(self, secret_key: bytes) -> None:
        self._secret_key: bytes = secret_key

    def get_metor_key(self) -> bytes:
        return self._secret_key


class _FakeStream:
    def __init__(self, messages: list[Optional[str]]) -> None:
        self._messages: list[Optional[str]] = messages
        self._index: int = 0

    def read_line(self) -> Optional[str]:
        if self._index >= len(self._messages):
            return None

        message: Optional[str] = self._messages[self._index]
        self._index += 1
        return message


class _DummyReceiverConfig:
    def get_float(self, _key: Any) -> float:
        return 0.2


class _DummyState:
    def consume_outbound_connected_origin(self, _onion: str) -> None:
        return None

    def add_active_connection(self, _onion: str, _conn: socket.socket) -> None:
        return None

    def consume_retunnel_reconnect(self, _onion: str) -> bool:
        return False

    def clear_retunnel_flow(self, _onion: str) -> None:
        return None

    def is_known_socket(self, _onion: str, _conn: socket.socket) -> bool:
        return True


class _DummyContactManagerReceiver:
    def ensure_alias_for_onion(self, _onion: str) -> str:
        return 'peer'


class _DummyHistoryManagerReceiver:
    def log_event(self, *args: Any, **kwargs: Any) -> None:
        return None


class _DummyRouterReceiver:
    def process_incoming_ack(self, _onion: str, _msg_id: str) -> None:
        return None

    def process_incoming_msg(
        self,
        _conn: socket.socket,
        _onion: str,
        _payload_id: str,
        _b64_payload: str,
    ) -> bool:
        return False


class _DummyReceiverSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def close(self) -> None:
        return None


class _ListenerTestConfig:
    def __init__(self, *, allow_headless_live_backlog: bool = True) -> None:
        self._allow_headless_live_backlog: bool = allow_headless_live_backlog

    def get_bool(self, key: Any) -> bool:
        if key is SettingKey.AUTO_ACCEPT_CONTACTS:
            return False
        return False

    def get_int(self, key: Any) -> int:
        if key is SettingKey.MAX_UNSEEN_LIVE_MSGS:
            return 1 if self._allow_headless_live_backlog else 0
        return 0

    def get_float(self, _key: Any) -> float:
        return 0.2


class _ListenerStream:
    def __init__(self, buffer: bytes = b'') -> None:
        self._buffer: bytes = buffer

    def get_buffer(self) -> bytes:
        return self._buffer


class _ConnectTestConfig:
    def __init__(
        self,
        max_connections: int,
        max_retries: int = 0,
        live_reconnect_delay: int = 0,
    ) -> None:
        self._max_connections: int = max_connections
        self._max_retries: int = max_retries
        self._live_reconnect_delay: int = live_reconnect_delay

    def get_int(self, key: Any) -> int:
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
        return 0.0


class _ConnectControllerHarness:
    def __init__(
        self,
        state: StateTracker,
        config: _ConnectTestConfig,
        connect_side_effect: Optional[BaseException] = None,
    ) -> None:
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
        self._receiver = None
        self.enqueued_live_reconnects: list[str] = []

    def accept(
        self,
        _target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        del origin

    def _get_local_connection_actor(self, _origin: ConnectionOrigin) -> Any:
        return None

    def _get_local_history_actor(self, _origin: ConnectionOrigin) -> Any:
        return None

    def _sleep_connect_retry_backoff(self) -> None:
        return None

    def _broadcast_retunnel_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
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
        self._state.mark_live_reconnect_grace(onion, 0.0)
        self._state.clear_retunnel_flow(onion)
        params: dict[str, Any] = {'alias': alias, 'onion': onion}
        if error is not None:
            params['error'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        self.enqueued_live_reconnects.append(onion)
        return True


class _RetunnelControllerHarness(ConnectionControllerRetunnelMixin):
    def __init__(self) -> None:
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
        self.connect_to_mock(target, origin=origin)

    def disconnect(self, *args: Any, **kwargs: Any) -> None:
        self.disconnect_mock(*args, **kwargs)


class DaemonHardeningTests(unittest.TestCase):
    @staticmethod
    def _build_daemon(
        start_locked: bool = False,
        require_session_auth: bool = False,
    ) -> Daemon:
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
        return (
            base64.b32encode(public_key + checksum + version)
            .decode('ascii')
            .lower()
            .rstrip('=')
        )

    @staticmethod
    def _build_v3_checksum(public_key: bytes, version: bytes) -> bytes:
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
        daemon = self._build_daemon(require_session_auth=False)
        daemon._local_auth.install_context(create_session_auth_context('secret'))

        self.assertFalse(daemon._requires_session_auth())

    def test_create_managed_daemon_rejects_plaintext_locked_mode(self) -> None:
        with self.assertRaises(PlaintextLockedDaemonError):
            create_managed_daemon(_PlaintextProfileManager(), start_locked=True)

    def test_runtime_error_status_formats_daemon_log_prefix(self) -> None:
        formatted = CommandHandlers._format_daemon_status(
            DaemonStatus.RUNTIME_ERROR,
            {'message': 'IPC acceptor recovered cleanly.'},
        )

        self.assertEqual(
            formatted,
            f'{Theme.CYAN}[DAEMON-LOG]{Theme.RESET} IPC acceptor recovered cleanly.',
        )

    def test_inbound_listener_start_listener_raises_when_bind_fails(self) -> None:
        listener = InboundListener(
            tm=cast(TorManager, Mock(incoming_port=43123)),
            cm=cast(ContactManager, Mock()),
            hm=cast(HistoryManager, Mock()),
            crypto=cast(Crypto, Mock()),
            state=cast(StateTracker, Mock()),
            router=cast(MessageRouter, Mock()),
            receiver=cast(StreamReceiver, Mock()),
            broadcast_callback=Mock(),
            has_live_consumers_callback=lambda: False,
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

        listener._hm.log_event.assert_called_once()
        listener._broadcast.assert_called_once()

    def test_start_subsystems_aborts_when_listener_readiness_fails(self) -> None:
        daemon = self._build_daemon()
        daemon._pm.initialize = Mock()
        daemon._tm = Mock()
        daemon._tm.start.return_value = (True, None, {})
        daemon._tm.onion = 'peeronion'
        daemon._network = Mock()
        daemon._network.start_listener.side_effect = RuntimeError('listener failed')
        daemon._outbox = Mock()
        daemon._ipc = Mock(port=43111)
        daemon.stop = Mock()
        status_cb = Mock()
        daemon._status_cb = status_cb

        result = daemon._start_subsystems()

        self.assertFalse(result)
        daemon.stop.assert_called_once()
        daemon._outbox.start.assert_not_called()
        status_cb.assert_called_once_with(
            DaemonStatus.RUNTIME_ERROR,
            {'message': 'listener failed'},
        )

    def test_locked_daemon_rejects_self_destruct_command(self) -> None:
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
        self.assertTrue(OutboxWorker._is_expected_ack_line('msg-1', '/ack msg-1'))
        self.assertFalse(
            OutboxWorker._is_expected_ack_line('msg-1', '/ack msg-1 extra')
        )
        self.assertFalse(OutboxWorker._is_expected_ack_line('msg-1', '/ack other'))
        self.assertFalse(
            OutboxWorker._is_expected_ack_line('msg-1', 'prefix /ack msg-1')
        )

    def test_chat_ipc_client_applies_timeout_and_ignores_read_timeouts(self) -> None:
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
        state = StateTracker()
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=10, max_retries=0),
        )
        controller._crypto.sign_challenge = Mock(return_value='signature')
        controller._receiver = Mock()
        conn = _NetworkSocket()
        controller.tor_manager_mock.connect = Mock(return_value=conn)

        class _ChallengeStream:
            def __init__(self, _conn: Any) -> None:
                return None

            def read_line(self) -> str:
                return f'/challenge {"ab" * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES}'

            def get_buffer(self) -> bytes:
                return b''

        with patch(
            'metor.core.daemon.managed.network.controller.session.connect.TcpStreamReader',
            _ChallengeStream,
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
        state = StateTracker()
        controller = _ConnectControllerHarness(
            state,
            _ConnectTestConfig(max_connections=10, max_retries=0),
        )
        conn = _NetworkSocket()
        controller.tor_manager_mock.connect = Mock(return_value=conn)

        class _InvalidChallengeStream:
            def __init__(self, _conn: Any) -> None:
                return None

            def read_line(self) -> str:
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
        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        broadcasted: list[IpcEvent] = []

        class _ResolvedContactManager(_DummyContactManager):
            def resolve_target(self, _target: str) -> tuple[str, str]:
                return 'peer', 'peer-onion'

        class _NoLiveState:
            def get_connection(self, _onion: str) -> None:
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

    def test_live_ack_carries_original_request_id_from_state_tracker(self) -> None:
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
        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_challenge_line('/msg deadbeef')

    def test_handshake_protocol_rejects_wrong_challenge_length(self) -> None:
        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_challenge_line(
                f'/challenge {"ab" * (Constants.TOR_HANDSHAKE_CHALLENGE_BYTES - 1)}'
            )

    def test_handshake_protocol_rejects_auth_frame_with_extra_tokens(self) -> None:
        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_auth_line('/auth peer sig ASYNC extra')

    def test_handshake_protocol_round_trips_recovery_auth_hints(self) -> None:
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
        with self.assertRaises(ValueError):
            HandshakeProtocol.parse_auth_line(
                f'/auth peer sig {ConnectionOrigin.MANUAL.value}'
            )

    def test_crypto_verify_signature_rejects_invalid_onion_checksum(self) -> None:
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
        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        acked_msg_ids: list[str] = []

        class _AckTrackingRouter:
            def process_incoming_ack(self, _onion: str, msg_id: str) -> None:
                acked_msg_ids.append(msg_id)

            def process_incoming_msg(
                self,
                _conn: socket.socket,
                _onion: str,
                _payload_id: str,
                _b64_payload: str,
            ) -> bool:
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
            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                self._actions: list[object] = [socket.timeout(), '/disconnect']

            def read_line(self) -> Optional[str]:
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
        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []

        class _UnknownSocketState(_DummyState):
            def is_known_socket(self, _onion: str, _conn: socket.socket) -> bool:
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
            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                self._actions: list[object] = [socket.timeout(), '/disconnect']

            def read_line(self) -> Optional[str]:
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
            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                self._actions: list[object] = [socket.timeout()]

            def read_line(self) -> Optional[str]:
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

    def test_listener_accepts_remote_retunnel_replacement_over_active_socket(
        self,
    ) -> None:
        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        listener, receiver_mock = self._build_live_listener(state)

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
        self.assertEqual(listener._broadcast.call_count, 1)
        event = listener._broadcast.call_args.args[0]
        self.assertIs(event.event_type, EventType.CONNECTED)
        self.assertEqual(event.origin, ConnectionOrigin.GRACE_RECONNECT)

    def test_listener_tracks_remote_auto_reconnect_replacement_as_pending(
        self,
    ) -> None:
        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        listener, receiver_mock = self._build_live_listener(
            state,
            allow_headless_live_backlog=False,
            has_live_consumers=False,
        )

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
        self.assertEqual(listener._broadcast.call_count, 0)

    def test_listener_rejects_plain_duplicate_incoming_when_live_is_active(
        self,
    ) -> None:
        state = StateTracker()
        old_conn = cast(socket.socket, _DummyConn())
        new_conn = cast(socket.socket, _DummyConn())
        state.add_active_connection('peer-onion', old_conn)
        listener, receiver_mock = self._build_live_listener(state)

        listener._handle_live_incoming(
            new_conn,
            cast(TcpStreamReader, _ListenerStream()),
            'peer-onion',
        )

        self.assertIs(state.get_connection('peer-onion'), old_conn)
        self.assertTrue(cast(_DummyConn, new_conn).closed)
        self.assertEqual(receiver_mock.start_receiving.call_count, 0)
        self.assertEqual(listener._broadcast.call_count, 0)
        self.assertEqual(len(cast(_DummyConn, new_conn).sent), 1)
        self.assertTrue(cast(_DummyConn, new_conn).sent[0].startswith(b'/reject '))

    def test_outbox_establish_tunnel_closes_socket_after_handshake_failure(
        self,
    ) -> None:
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
            def __init__(self, _conn: Any) -> None:
                return None

            def read_line(self) -> str:
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
