"""Targeted regression tests for daemon hardening around IPC and live transport."""

# ruff: noqa: E402

import base64
import hashlib
import json
import socket
import sys
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import nacl.bindings

from metor.core.api import ConnectionOrigin
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.receiver import StreamReceiver
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.state import (
    PendingConnectionReason,
    StateTracker,
)
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.utils import Constants


class _DummyConfig:
    def get_bool(self, _key: Any) -> bool:
        return True

    def get_float(self, _key: Any) -> float:
        return 0.2


class _DummyProfileManager:
    def __init__(self) -> None:
        self.config: _DummyConfig = _DummyConfig()

    def get_static_port(self) -> None:
        return None

    def set_daemon_port(self, _port: int, _pid: int) -> None:
        return None


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

    def queue_message(self, **kwargs: Any) -> _QueueResult:
        self.queued.append(kwargs)
        return _QueueResult()


class _DummyConn:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed: bool = False

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


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


class DaemonHardeningTests(unittest.TestCase):
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

    def test_ipc_broadcast_sends_without_holding_lock(self) -> None:
        server = IpcServer(_DummyProfileManager(), lambda _cmd, _conn: None)
        client = _InspectingSocket(server)
        server._clients = [client]

        server.broadcast(_DummyEvent())

        self.assertEqual(client.payloads, [b'{"event_type": "test"}\n'])
        self.assertFalse(client.lock_was_held)

    def test_async_drop_skips_invalid_payload_and_processes_next_message(self) -> None:
        history_manager = _DummyHistoryManager()
        message_manager = _DummyMessageManager()
        router = MessageRouter(
            cm=_DummyContactManager(),
            hm=history_manager,
            mm=message_manager,
            state=object(),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            has_live_consumers_callback=lambda: False,
            config=_DummyConfig(),
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

        router.process_async_drop(conn, stream, 'peer-onion')

        self.assertEqual(len(message_manager.queued), 1)
        self.assertEqual(message_manager.queued[0]['msg_id'], 'msg-1')
        self.assertEqual(message_manager.queued[0]['payload'], 'hello')
        self.assertEqual(conn.sent, [b'/ack msg-1\n'])
        self.assertTrue(conn.closed)

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

    def test_crypto_verify_signature_rejects_invalid_onion_checksum(self) -> None:
        seed = b'\x42' * 32
        public_key, secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)
        crypto = Crypto(_DummyKeyManager(secret_key))
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
        crypto = Crypto(_DummyKeyManager(secret_key))
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
            cm=_DummyContactManagerReceiver(),
            hm=_DummyHistoryManagerReceiver(),
            state=_DummyState(),
            router=_DummyRouterReceiver(),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=_DummyReceiverConfig(),
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

    def test_receiver_ignores_idle_timeout_for_active_live_socket(self) -> None:
        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=_DummyContactManagerReceiver(),
            hm=_DummyHistoryManagerReceiver(),
            state=_DummyState(),
            router=_DummyRouterReceiver(),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=_DummyReceiverConfig(),
        )
        conn = _DummyReceiverSocket()

        class _PatchedStream:
            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                self._actions: list[object] = [socket.timeout(), '/disconnect']

            def read_line(self) -> Optional[str]:
                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return action

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                conn,
                b'',
                False,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertFalse(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])

    def test_receiver_keeps_pending_accept_timeout_behavior(self) -> None:
        disconnect_calls: list[tuple[Any, ...]] = []
        reject_calls: list[tuple[Any, ...]] = []
        receiver = StreamReceiver(
            cm=_DummyContactManagerReceiver(),
            hm=_DummyHistoryManagerReceiver(),
            state=_DummyState(),
            router=_DummyRouterReceiver(),
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: False,
            disconnect_cb=lambda *args: disconnect_calls.append(args),
            reject_cb=lambda *args: reject_calls.append(args),
            config=_DummyReceiverConfig(),
        )
        conn = _DummyReceiverSocket()

        class _PatchedStream:
            def __init__(self, _conn: Any, _initial_buffer: bytes = b'') -> None:
                self._actions: list[object] = [socket.timeout()]

            def read_line(self) -> Optional[str]:
                action: object = self._actions.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return action

        with patch(
            'metor.core.daemon.managed.network.receiver.TcpStreamReader',
            _PatchedStream,
        ):
            receiver._receiver_target(
                'peer-onion',
                conn,
                b'',
                True,
                ConnectionOrigin.INCOMING,
            )

        self.assertEqual(conn.timeouts, [0.2])
        self.assertEqual(len(disconnect_calls), 1)
        self.assertTrue(disconnect_calls[0][2])
        self.assertEqual(reject_calls, [])


if __name__ == '__main__':
    unittest.main()
