"""
Module defining the background worker for sending asynchronous offline messages.
Implements connection tunneling (batching), focus-aware keep-alives, and strict UUID
JSON-enveloping to guarantee message consistency and deduplication.
Enforces TCP stream framing to prevent UTF-8 fragmentation crashes.
"""

import json
import socket
import threading
import time
import base64
from typing import List, Optional, Tuple, Callable, Dict, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    IpcEvent,
    AckEvent,
    EventType,
    JsonValue,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    create_event,
)
from metor.core.daemon.managed.models import PrimaryTransport
from metor.data import (
    HistoryActor,
    MessageManager,
    MessageStatus,
    HistoryManager,
    HistoryEvent,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.models import TorCommand
from metor.core.daemon.managed.network import (
    HandshakeProtocol,
    StateTracker,
    TcpStreamReader,
)

if TYPE_CHECKING:
    from metor.data.profile import Config


class OutboxWorker:
    """Background service for processing the Drop & Go offline message queue via Persistent Tunnels."""

    @staticmethod
    def _is_expected_ack_line(msg_id: str, ack_line: Optional[str]) -> bool:
        """
        Validates one drop ACK frame against the exact expected message identifier.

        Args:
            msg_id (str): The logical message identifier awaiting confirmation.
            ack_line (Optional[str]): The raw newline-delimited ACK frame.

        Returns:
            bool: True if the ACK frame is well-formed and matches the message ID.
        """
        if ack_line is None:
            return False

        parts: list[str] = ack_line.strip().split()
        return (
            len(parts) == 2 and parts[0] == TorCommand.ACK.value and parts[1] == msg_id
        )

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
        error_callback: Optional[Callable[[str], None]] = None,
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
            error_callback (Optional[Callable[[str], None]]): Optional callback used to
                surface unexpected worker-loop errors outside projected history.

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
        self._error_callback: Optional[Callable[[str], None]] = error_callback

        # Cache for persistent tunnels: onion -> (socket, stream_reader, last_used_timestamp)
        self._tunnels: Dict[str, Tuple[socket.socket, TcpStreamReader, float]] = {}
        self._tunnels_lock: threading.Lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

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

    def _is_drop_standby_allowed(self) -> bool:
        """
        Checks whether cached drop standby is allowed while live exists.

        Args:
            None

        Returns:
            bool: True if drop standby is enabled.
        """
        return self._config.get_bool(SettingKey.ALLOW_DROP_STANDBY_ON_LIVE)

    def start(self) -> None:
        """
        Starts the worker loop in a background thread.

        Args:
            None

        Returns:
            None
        """
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._worker_thread = threading.Thread(target=self._loop, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        """
        Stops the worker loop and closes all cached tunnels.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        self._close_all_tunnels()

        if (
            self._worker_thread
            and self._worker_thread.is_alive()
            and threading.current_thread() is not self._worker_thread
        ):
            self._worker_thread.join(
                timeout=(
                    Constants.WORKER_SLEEP_SLOW_SEC + Constants.THREAD_POLL_TIMEOUT
                )
            )

    def reset_tunnel(self, onion: str) -> None:
        """
        Closes a cached drop tunnel so the next send establishes a fresh route.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        self._close_tunnel(onion)

    def retunnel(self, onion: str, alias: str) -> None:
        """
        Rotates Tor circuits for future drop sends and discards any cached tunnel.

        Args:
            onion (str): The target onion identity.
            alias (str): The strict alias for UI feedback.

        Returns:
            None
        """
        self._broadcast(RetunnelInitiatedEvent(alias=alias, onion=onion))
        self._close_tunnel(onion)

        success, event_type, params = self._tm.rotate_circuits()
        if not success:
            failure_params: Dict[str, JsonValue] = {'alias': alias}
            failure_params['onion'] = onion
            failure_params.update(params)
            self._broadcast(
                create_event(event_type or EventType.RETUNNEL_FAILED, failure_params)
            )
            return

        self._broadcast(RetunnelSuccessEvent(alias=alias, onion=onion))

    def _loop(self) -> None:
        """
        Target execution loop checking the database for pending drops and managing
        cached drop tunnels.
        Enforces Thread-Safety by catching any unexpected errors to prevent silent worker crashes.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(Constants.WORKER_SLEEP_SLOW_SEC)

            try:
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
            except Exception:
                self._report_internal_error(
                    'Outbox worker loop recovered from an unexpected runtime error.'
                )

        self._close_all_tunnels()

    def _process_batch(
        self, onion: str, messages: List[Tuple[int, str, str, str, str, str]]
    ) -> None:
        """
        Transmits a batch of messages over a persistent Tor tunnel.
        Establishes a new tunnel if none exists and manages robust stream reading.
        Applies Infinite Retries by breaking on failure while keeping messages PENDING.
        Refreshes cached tunnel activity immediately upon every socket push.

        Args:
            onion (str): The target onion identity.
            messages (List[Tuple[int, str, str, str, str, str]]): The grouped outbox rows.

        Returns:
            None
        """
        idle_timeout: float = self._config.get_float(
            SettingKey.DROP_TUNNEL_IDLE_TIMEOUT
        )
        if idle_timeout == 0.0:
            self._close_tunnel(onion)
            for row in messages:
                if self._stop_flag.is_set():
                    return
                self._send_single_drop(onion, row)
            return

        conn: Optional[socket.socket] = None
        stream: Optional[TcpStreamReader] = None

        with self._tunnels_lock:
            tunnel: Optional[Tuple[socket.socket, TcpStreamReader, float]] = (
                self._tunnels.get(onion)
            )

        if tunnel:
            conn, stream, _ = tunnel
        else:
            tunnel_data: Optional[Tuple[socket.socket, TcpStreamReader]] = (
                self._establish_tunnel(onion)
            )
            if tunnel_data:
                conn, stream = tunnel_data
                with self._tunnels_lock:
                    self._tunnels[onion] = (conn, stream, time.time())
                if self._state:
                    self._state.mark_drop_tunnel_open(onion)
                self._hm.log_event(
                    HistoryEvent.TUNNEL_CONNECTED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                )

        if not conn or not stream:
            self._hm.log_event(
                HistoryEvent.TUNNEL_FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text='Failed to build Tor circuit',
            )
            return

        try:
            stream_idle_timeout: float = self._config.get_float(
                SettingKey.STREAM_IDLE_TIMEOUT
            )
            conn.settimeout(stream_idle_timeout)

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

                try:
                    conn.sendall(drop_msg.encode('utf-8'))
                    # Refresh the cached tunnel activity timestamp after a successful send.
                    with self._tunnels_lock:
                        if onion in self._tunnels:
                            self._tunnels[onion] = (conn, stream, time.time())
                    if self._state:
                        self._state.touch_drop_tunnel(onion)

                    ack_line: Optional[str] = stream.read_line()
                    if not self._is_expected_ack_line(msg_id, ack_line):
                        raise ConnectionError('Tunnel dropped or invalid ACK received.')

                    self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
                    self._hm.log_event(
                        HistoryEvent.SENT,
                        onion,
                        actor=HistoryActor.LOCAL,
                    )
                    self._broadcast(AckEvent(msg_id=msg_id, timestamp=timestamp))
                except Exception as e:
                    self._hm.log_event(
                        HistoryEvent.FAILED,
                        onion,
                        actor=HistoryActor.SYSTEM,
                        detail_text=str(e),
                    )
                    self._close_tunnel(onion)
                    break  # Stop processing batch, messages remain PENDING for next tick retry

            if (
                self._state
                and self._state.get_primary_transport(
                    onion,
                    standby_drop_allowed=self._is_drop_standby_allowed(),
                )
                is PrimaryTransport.LIVE
                and not self._is_drop_standby_allowed()
            ):
                self._close_tunnel(onion)
        except Exception as e:
            self._hm.log_event(
                HistoryEvent.FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=str(e),
            )
            self._close_tunnel(onion)

    def _send_single_drop(
        self, onion: str, row: Tuple[int, str, str, str, str, str]
    ) -> None:
        """
        Sends exactly one offline message over a short-lived tunnel.

        Args:
            onion (str): The target onion identity.
            row (Tuple[int, str, str, str, str, str]): The queued outbox row.

        Returns:
            None
        """
        tunnel_data: Optional[Tuple[socket.socket, TcpStreamReader]] = (
            self._establish_tunnel(onion)
        )
        if not tunnel_data:
            self._hm.log_event(
                HistoryEvent.TUNNEL_FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text='Failed to build Tor circuit',
            )
            return

        conn, stream = tunnel_data
        db_id, _, _, payload, msg_id, timestamp = row

        try:
            conn.settimeout(self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT))
            drop_msg: str = self._build_drop_message(payload, msg_id, timestamp)
            conn.sendall(drop_msg.encode('utf-8'))

            ack_line: Optional[str] = stream.read_line()
            if not self._is_expected_ack_line(msg_id, ack_line):
                raise ConnectionError('Tunnel dropped or invalid ACK received.')

            self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
            self._hm.log_event(
                HistoryEvent.SENT,
                onion,
                actor=HistoryActor.LOCAL,
            )
            self._broadcast(AckEvent(msg_id=msg_id, timestamp=timestamp))
        except Exception as e:
            self._hm.log_event(
                HistoryEvent.FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=str(e),
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _build_drop_message(self, payload: str, msg_id: str, timestamp: str) -> str:
        """
        Builds the newline-delimited JSON envelope for a drop message.

        Args:
            payload (str): The message content.
            msg_id (str): The stable message identifier.
            timestamp (str): The recorded message timestamp.

        Returns:
            str: The encoded Tor DROP command line.
        """
        envelope: Dict[str, JsonValue] = {
            'id': msg_id,
            'timestamp': timestamp,
            'text': payload,
        }
        envelope_str: str = json.dumps(envelope)
        b64_payload: str = base64.b64encode(envelope_str.encode('utf-8')).decode(
            'utf-8'
        )
        return f'{TorCommand.DROP.value} {msg_id} {b64_payload}\n'

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
        conn: Optional[socket.socket] = None
        try:
            conn = self._tm.connect(onion)
            tor_timeout: float = self._config.get_float(SettingKey.TOR_TIMEOUT)
            conn.settimeout(tor_timeout)

            stream: TcpStreamReader = TcpStreamReader(conn)
            challenge_line: Optional[str] = stream.read_line()

            if not challenge_line:
                conn.close()
                return None

            challenge: str = HandshakeProtocol.parse_challenge_line(challenge_line)
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
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            return None

    def _cleanup_tunnels(self) -> None:
        """
        Checks all active tunnels against the idle cache policy and UI focus state.
        Closes tunnels that exceeded their idle budget or are disallowed by the
        current transport policy.

        Args:
            None

        Returns:
            None
        """
        idle_timeout: float = self._config.get_float(
            SettingKey.DROP_TUNNEL_IDLE_TIMEOUT
        )
        now: float = time.time()
        expired_onions: List[str] = []

        with self._tunnels_lock:
            tunnel_items: List[
                Tuple[str, Tuple[socket.socket, TcpStreamReader, float]]
            ] = list(self._tunnels.items())

        for onion, (_, _, last_used) in tunnel_items:
            is_focused: bool = (
                self._state.is_focused_by_ui(onion) if self._state else False
            )

            if (
                self._state
                and self._state.get_primary_transport(
                    onion,
                    standby_drop_allowed=self._is_drop_standby_allowed(),
                )
                is PrimaryTransport.LIVE
                and not self._is_drop_standby_allowed()
            ):
                expired_onions.append(onion)
                continue

            if idle_timeout == 0.0:
                expired_onions.append(onion)
                continue

            # Focus may keep a cached drop tunnel alive while caching is enabled.
            if is_focused:
                continue

            if (now - last_used) > idle_timeout:
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
        with self._tunnels_lock:
            tunnel: Optional[Tuple[socket.socket, TcpStreamReader, float]] = (
                self._tunnels.pop(onion, None)
            )

        if not tunnel:
            return

        conn, _, _ = tunnel
        if self._state:
            self._state.clear_drop_tunnel(onion)
        try:
            conn.close()
            self._hm.log_event(
                HistoryEvent.TUNNEL_CLOSED,
                onion,
                actor=HistoryActor.SYSTEM,
            )
        except Exception:
            pass

    def _close_all_tunnels(self) -> None:
        """
        Closes and removes every cached tunnel safely.

        Args:
            None

        Returns:
            None
        """
        with self._tunnels_lock:
            onions: List[str] = list(self._tunnels.keys())

        for onion in onions:
            self._close_tunnel(onion)
