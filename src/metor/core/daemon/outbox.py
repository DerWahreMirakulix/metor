"""
Module defining the background worker for sending asynchronous offline messages.
Implements connection tunneling (Batching), TTL Keep-Alives (Multi-Client Focus),
and strict UUID JSON-Enveloping to guarantee message consistency and deduplication.
Enforces TCP Stream Framing to prevent UTF-8 fragmentation crashes.
"""

import json
import socket
import threading
import time
import base64
from typing import List, Optional, Tuple, Callable, Dict, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import IpcEvent, AckEvent, DropFailedEvent, JsonValue
from metor.data import (
    MessageManager,
    MessageStatus,
    HistoryManager,
    HistoryEvent,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.crypto import Crypto
from metor.core.daemon.models import TorCommand
from metor.core.daemon.network import StateTracker, TcpStreamReader

if TYPE_CHECKING:
    from metor.data.profile.config import Config


class OutboxWorker:
    """Background service for processing the Drop & Go offline message queue via Persistent Tunnels."""

    def __init__(
        self,
        tm: TorManager,
        mm: MessageManager,
        hm: HistoryManager,
        crypto: Crypto,
        broadcast_callback: Callable[[IpcEvent], None],
        stop_flag: threading.Event,
        config: 'Config',
        state: Optional[StateTracker] = None,
    ) -> None:
        """
        Initializes the OutboxWorker.

        Args:
            tm (TorManager): The Tor network manager for outbound connections.
            mm (MessageManager): The database manager for accessing pending messages.
            hm (HistoryManager): The history logger.
            crypto (Crypto): The cryptographic service for handshakes.
            broadcast_callback (Callable): Callback to broadcast IPC events.
            stop_flag (threading.Event): Event to gracefully shutdown the worker loop.
            config (Config): The profile configuration instance.
            state (Optional[StateTracker]): State tracker to read UI focus reference counts.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._mm: MessageManager = mm
        self._hm: HistoryManager = hm
        self._crypto: Crypto = crypto
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config
        self._state: Optional[StateTracker] = state

        # Cache for persistent tunnels: onion -> (socket, stream_reader, last_used_timestamp)
        self._tunnels: Dict[str, Tuple[socket.socket, TcpStreamReader, float]] = {}

    def start(self) -> None:
        """
        Starts the worker loop in a background thread.

        Args:
            None

        Returns:
            None
        """
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        """
        Target execution loop checking the database for pending drops and managing tunnel TTLs.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(2.0)

            pending_rows: List[Tuple[int, str, str, str, str, str]] = (
                self._mm.get_pending_outbox()
            )

            # 1. Group messages by target onion (Batching)
            batches: Dict[str, List[Tuple[int, str, str, str, str, str]]] = {}
            for row in pending_rows:
                target_onion = row[1]
                batches.setdefault(target_onion, []).append(row)

            # 2. Process each batch through persistent tunnels
            for onion, messages in batches.items():
                self._process_batch(onion, messages)

            # 3. Clean up stale or unfocused tunnels
            self._cleanup_tunnels()

        # Teardown all tunnels on shutdown
        for onion, (conn, _, _) in self._tunnels.items():
            try:
                conn.close()
            except Exception:
                pass
        self._tunnels.clear()

    def _process_batch(
        self, onion: str, messages: List[Tuple[int, str, str, str, str, str]]
    ) -> None:
        """
        Transmits a batch of messages over a persistent Tor tunnel.
        Establishes a new tunnel if none exists and manages robust stream reading.

        Args:
            onion (str): The target onion identity.
            messages (List[Tuple[int, str, str, str, str, str]]): The grouped outbox rows.

        Returns:
            None
        """
        conn: Optional[socket.socket] = None
        stream: Optional[TcpStreamReader] = None

        if onion in self._tunnels:
            conn, stream, _ = self._tunnels[onion]
        else:
            tunnel_data: Optional[Tuple[socket.socket, TcpStreamReader]] = (
                self._establish_tunnel(onion)
            )
            if tunnel_data:
                conn, stream = tunnel_data
                self._tunnels[onion] = (conn, stream, time.time())
                self._hm.log_event(HistoryEvent.DROP_TUNNEL_CONNECTED, onion)

        if not conn or not stream:
            self._hm.log_event(
                HistoryEvent.DROP_TUNNEL_FAILED, onion, 'Failed to build Tor circuit'
            )
            for row in messages:
                self._broadcast(DropFailedEvent(msg_id=row[4]))
            return

        try:
            idle_timeout: float = self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT)
            conn.settimeout(idle_timeout)

            for row in messages:
                db_id, _, _, payload, msg_id, timestamp = row

                envelope: Dict[str, JsonValue] = {
                    'id': msg_id,
                    'timestamp': timestamp,
                    'text': payload,
                }
                envelope_str: str = json.dumps(envelope)
                b64_payload: str = base64.b64encode(
                    envelope_str.encode('utf-8')
                ).decode('utf-8')

                drop_msg: str = f'{TorCommand.DROP.value} {msg_id} {b64_payload}\n'
                conn.sendall(drop_msg.encode('utf-8'))

                ack_line: Optional[str] = stream.read_line()
                if not ack_line:
                    raise ConnectionError('Tunnel dropped while awaiting ACK.')

                if f'{TorCommand.ACK.value} {msg_id}' in ack_line:
                    self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
                    self._hm.log_event(HistoryEvent.DROP_SENT, onion)
                    self._broadcast(AckEvent(msg_id=msg_id, text=payload))

            self._tunnels[onion] = (conn, stream, time.time())

        except Exception as e:
            self._hm.log_event(HistoryEvent.DROP_FAILED, onion, str(e))
            for row in messages:
                self._broadcast(DropFailedEvent(msg_id=row[4]))
            self._close_tunnel(onion)

    def _establish_tunnel(
        self, onion: str
    ) -> Optional[Tuple[socket.socket, TcpStreamReader]]:
        """
        Performs the Ed25519 ASYNC Handshake to open a new tunnel securely.

        Args:
            onion (str): The target onion identity.

        Returns:
            Optional[Tuple[socket.socket, TcpStreamReader]]: The authenticated socket and its stream reader, or None if failed.
        """
        try:
            conn: socket.socket = self._tm.connect(onion)
            tor_timeout: float = self._config.get_float(SettingKey.TOR_TIMEOUT)
            conn.settimeout(tor_timeout)

            stream: TcpStreamReader = TcpStreamReader(conn)
            challenge_line: Optional[str] = stream.read_line()

            if not challenge_line:
                conn.close()
                return None

            challenge: str = challenge_line.strip().split(' ')[1]
            signature: Optional[str] = self._crypto.sign_challenge(challenge)

            if not signature:
                conn.close()
                return None

            auth_msg: str = (
                f'{TorCommand.AUTH.value} {self._tm.onion} {signature} ASYNC\n'
            )
            conn.sendall(auth_msg.encode('utf-8'))
            return conn, stream
        except Exception:
            return None

    def _cleanup_tunnels(self) -> None:
        """
        Checks all active tunnels against the TTL and UI Focus Reference Counts.
        Closes tunnels that have expired and are no longer focused.

        Args:
            None

        Returns:
            None
        """
        ttl_setting: float = self._config.get_float(SettingKey.DROP_TUNNEL_TTL)
        now: float = time.time()
        expired_onions: List[str] = []

        for onion, (_, _, last_used) in self._tunnels.items():
            is_focused: bool = (
                self._state.is_focused_by_ui(onion) if self._state else False
            )

            if ttl_setting == 0.0:
                if not is_focused:
                    expired_onions.append(onion)
                continue

            if (now - last_used) > ttl_setting and not is_focused:
                expired_onions.append(onion)

        for onion in expired_onions:
            self._close_tunnel(onion)

    def _close_tunnel(self, onion: str) -> None:
        """
        Safely closes a tunnel and removes it from the cache.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        if onion in self._tunnels:
            conn, _, _ = self._tunnels.pop(onion)
            try:
                conn.close()
                self._hm.log_event(HistoryEvent.DROP_TUNNEL_CLOSED, onion)
            except Exception:
                pass
