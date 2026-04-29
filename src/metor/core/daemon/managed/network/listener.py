"""
Module wrapping the server socket binding and authentication validation.
Routes inbound connections to the application drops or the live connection state pool.
Enforces Max Concurrent Connection Limits to mitigate RAM/FD Exhaustion attacks.
"""

import select
import socket
import threading
import secrets
import time
from typing import Optional, Callable, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
    IpcEvent,
    ConnectedEvent,
    DisconnectedEvent,
    IncomingConnectionEvent,
    RetunnelSuccessEvent,
    RuntimeErrorCode,
    ConnectionRejectedEvent,
    MaxConnectionsReachedEvent,
    create_event,
)
from metor.core.daemon.managed.models import (
    LiveTransportState,
    RejectIntent,
    TorCommand,
)
from metor.core.daemon.managed.crypto import Crypto
from metor.data import (
    HistoryActor,
    HistoryManager,
    HistoryEvent,
    HistoryReasonCode,
    ContactManager,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.managed.network.state import (
    PendingConnectionReason,
    StateTracker,
)
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.router import MessageRouter

if TYPE_CHECKING:
    from metor.core.daemon.managed.network.receiver import StreamReceiver
    from metor.data.profile import Config


class InboundListener:
    """Manages the passive Tor listener socket and initial peer handshakes."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        crypto: Crypto,
        state: StateTracker,
        router: MessageRouter,
        receiver: 'StreamReceiver',
        broadcast_callback: Callable[[IpcEvent], None],
        has_live_consumers_callback: Callable[[], bool],
        enqueue_live_reconnect_callback: Callable[[str], bool],
        stop_flag: threading.Event,
        config: 'Config',
    ) -> None:
        """
        Initializes the InboundListener.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            crypto (Crypto): Cryptographic engine.
            state (StateTracker): The thread-safe state container.
            router (MessageRouter): The application-layer message router.
            receiver (StreamReceiver): The stream receiver to instantiate upon acceptance.
            broadcast_callback (Callable): IPC broadcaster.
            has_live_consumers_callback (Callable[[], bool]): Callback to check whether an interactive live consumer is attached.
            enqueue_live_reconnect_callback (Callable[[str], bool]): Callback to queue one delayed automatic reconnect attempt.
            stop_flag (threading.Event): Global daemon termination flag.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._crypto: Crypto = crypto
        self._state: StateTracker = state
        self._router: MessageRouter = router
        self._receiver: 'StreamReceiver' = receiver
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_live_consumers: Callable[[], bool] = has_live_consumers_callback
        self._enqueue_live_reconnect: Callable[[str], bool] = (
            enqueue_live_reconnect_callback
        )
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config
        self._listener_thread: Optional[threading.Thread] = None
        self._startup_event: threading.Event = threading.Event()
        self._startup_lock: threading.Lock = threading.Lock()
        self._startup_error: Optional[str] = None

    def _allows_headless_live_backlog(self) -> bool:
        """
        Determines whether inbound live may be auto-accepted without an interactive consumer.

        Args:
            None

        Returns:
            bool: True if headless live backlog is allowed.
        """
        return self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS) != 0

    def _mark_live_reconnect_grace(self, onion: str) -> None:
        """
        Marks one incoming reconnect grace window using the profile configuration.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        grace_timeout_sec: int = self._config.get_int(
            SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT
        )
        self._state.mark_live_reconnect_grace(onion, float(grace_timeout_sec))

    def _schedule_live_reconnect(self, alias: str, onion: str) -> None:
        """
        Queues one automatic reconnect attempt and emits the scheduling lifecycle.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.

        Returns:
            None
        """
        self._state.mark_scheduled_auto_reconnect(onion)
        was_scheduled: bool = self._enqueue_live_reconnect(onion)
        if not was_scheduled:
            return

        self._hm.log_event(
            HistoryEvent.AUTO_RECONNECT_SCHEDULED,
            onion,
            actor=HistoryActor.SYSTEM,
            trigger=ConnectionOrigin.AUTO_RECONNECT,
        )
        self._broadcast(
            AutoReconnectScheduledEvent(
                alias=alias,
                onion=onion,
                origin=ConnectionOrigin.AUTO_RECONNECT,
                actor=ConnectionActor.SYSTEM,
            )
        )

    def _set_startup_error(self, error: str) -> None:
        """
        Stores one listener startup failure and releases any waiting starter.

        Args:
            error (str): The startup failure detail.

        Returns:
            None
        """
        with self._startup_lock:
            if self._startup_event.is_set():
                return
            self._startup_error = error
            self._startup_event.set()

    def _mark_started(self) -> None:
        """
        Marks the inbound listener as successfully bound and listening.

        Args:
            None

        Returns:
            None
        """
        with self._startup_lock:
            self._startup_error = None
            self._startup_event.set()

    def start_listener(self) -> None:
        """
        Starts the local Tor listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        with self._startup_lock:
            self._startup_error = None
            self._startup_event.clear()

        self._listener_thread = threading.Thread(
            target=self._listener_target,
            daemon=True,
        )
        try:
            self._listener_thread.start()
        except Exception as exc:
            self._set_startup_error(str(exc).strip() or exc.__class__.__name__)

        ready: bool = self._startup_event.wait(Constants.LISTENER_READY_TIMEOUT)
        with self._startup_lock:
            startup_error: Optional[str] = self._startup_error

        if startup_error is not None:
            raise RuntimeError(
                f'Inbound live listener failed to start: {startup_error}'
            )
        if not ready:
            raise RuntimeError('Timed out while waiting for the inbound live listener.')

    def _listener_target(self) -> None:
        """
        Background loop accepting raw incoming Tor sockets.
        Enforces maximum connection limits to prevent DoS.

        Args:
            None

        Returns:
            None
        """
        listener: Optional[socket.socket] = None
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind((Constants.LOCALHOST, self._tm.incoming_port or 0))
            listener.listen(Constants.SERVER_BACKLOG)
            self._mark_started()

            while not self._stop_flag.is_set():
                try:
                    listener.settimeout(Constants.THREAD_POLL_TIMEOUT)
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError as e:
                    if self._stop_flag.is_set():
                        break
                    self._hm.log_event(
                        HistoryEvent.STREAM_CORRUPTED,
                        None,
                        actor=HistoryActor.SYSTEM,
                        detail_text=str(e).strip() or e.__class__.__name__,
                    )
                    continue

                max_conn: int = self._config.get_int(
                    SettingKey.MAX_CONCURRENT_CONNECTIONS
                )
                tracked_socket_count: int = self._state.get_tracked_live_socket_count()

                if tracked_socket_count >= max_conn:
                    self._hm.log_event(
                        HistoryEvent.REJECTED,
                        None,
                        actor=HistoryActor.SYSTEM,
                        detail_text='Listener drop',
                        detail_code=HistoryReasonCode.MAX_CONNECTIONS_REACHED,
                    )
                    self._broadcast(
                        MaxConnectionsReachedEvent(
                            target='Unknown (Listener)', max_conn=max_conn
                        )
                    )
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue

                self._state.add_unauthenticated_connection(conn)
                try:
                    threading.Thread(
                        target=self._handle_incoming, args=(conn,), daemon=True
                    ).start()
                except Exception:
                    self._state.remove_unauthenticated_connection(conn)
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._hm.log_event(
                        HistoryEvent.STREAM_CORRUPTED,
                        None,
                        actor=HistoryActor.SYSTEM,
                        detail_text='Inbound listener failed to start handler thread.',
                    )
                    continue
        except MemoryError as e:
            self._set_startup_error(str(e))
            self._hm.log_event(
                HistoryEvent.STREAM_CORRUPTED,
                None,
                actor=HistoryActor.SYSTEM,
                detail_text=str(e),
            )
        except Exception as e:
            error_text: str = str(e).strip() or e.__class__.__name__
            self._set_startup_error(error_text)
            self._hm.log_event(
                HistoryEvent.STREAM_CORRUPTED,
                None,
                actor=HistoryActor.SYSTEM,
                detail_text=error_text,
            )
            self._broadcast(create_event(EventType.INTERNAL_ERROR))
        finally:
            if listener is not None:
                try:
                    listener.close()
                except Exception:
                    pass

    def _handle_incoming(self, conn: socket.socket) -> None:
        """
        Authenticates inbound requests using the constrained stream reader.

        Args:
            conn (socket.socket): The incoming socket connection.

        Returns:
            None
        """
        auth_successful: bool = False
        onion: Optional[str] = None
        is_async: bool = False
        stream: Optional[TcpStreamReader] = None

        try:
            tor_timeout: float = self._config.get_float(SettingKey.TOR_TIMEOUT)
            conn.settimeout(tor_timeout)
            challenge: str = secrets.token_hex(Constants.TOR_HANDSHAKE_CHALLENGE_BYTES)
            conn.sendall(f'{TorCommand.CHALLENGE.value} {challenge}\n'.encode('utf-8'))

            stream = TcpStreamReader(conn)
            line: Optional[str] = stream.read_line()

            if line:
                remote_onion, signature, is_async, has_recovery_hint = (
                    HandshakeProtocol.parse_auth_line(line)
                )
                if self._crypto.verify_signature(remote_onion, challenge, signature):
                    onion = remote_onion
                    auth_successful = True
        except MemoryError as e:
            self._hm.log_event(
                HistoryEvent.STREAM_CORRUPTED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=str(e),
            )
        except Exception:
            pass
        finally:
            self._state.remove_unauthenticated_connection(conn)

        if not auth_successful or not onion or not stream:
            try:
                conn.close()
            except Exception:
                pass
            return

        if is_async:
            self._router.process_async_drop(conn, stream, onion)
            return

        self._handle_live_incoming(conn, stream, onion, has_recovery_hint)

    def _watch_pending_connection(
        self, onion: str, alias: str, conn: socket.socket
    ) -> None:
        """
        Expires a pending inbound live socket once the remote side disappears or the
        late-acceptance window elapses.

        Args:
            onion (str): The peer onion identity.
            alias (str): The strict alias for UI feedback.
            conn (socket.socket): The pending socket to supervise.

        Returns:
            None
        """
        deadline: float = time.time() + self._config.get_float(
            SettingKey.LATE_ACCEPTANCE_TIMEOUT
        )

        while not self._stop_flag.is_set():
            if not self._state.is_pending_socket(onion, conn):
                return

            remaining_sec: float = deadline - time.time()
            if remaining_sec <= 0:
                break

            wait_sec: float = min(Constants.THREAD_POLL_TIMEOUT, remaining_sec)
            try:
                readable, _, exceptional = select.select([conn], [], [conn], wait_sec)
            except Exception:
                break

            if not self._state.is_pending_socket(onion, conn):
                return

            if exceptional:
                break

            if not readable:
                continue

            try:
                peek: bytes = conn.recv(1, socket.MSG_PEEK)
            except (BlockingIOError, InterruptedError):
                continue
            except Exception:
                break

            if peek == b'' or peek:
                break

        if not self._state.remove_pending_connection_if_socket(onion, conn):
            return

        self._state.mark_recent_pending_expiry(onion)
        self._hm.log_event(
            HistoryEvent.CONNECTION_LOST,
            onion,
            actor=HistoryActor.SYSTEM,
            trigger=ConnectionOrigin.INCOMING,
            detail_code=HistoryReasonCode.PENDING_ACCEPTANCE_EXPIRED,
        )

        try:
            conn.close()
        except Exception:
            pass

        if self._state.is_retunneling(onion):
            preserved_live_connection: bool = self._state.is_live_active(onion)
            self._state.clear_retunnel_flow(onion)
            if preserved_live_connection:
                self._state.mark_live_reconnect_grace(onion, 0.0)
            else:
                self._mark_live_reconnect_grace(onion)
                self._broadcast(
                    DisconnectedEvent(
                        alias=alias,
                        onion=onion,
                        actor=ConnectionActor.SYSTEM,
                        origin=ConnectionOrigin.RETUNNEL,
                        reason_code=ConnectionReasonCode.PENDING_ACCEPTANCE_EXPIRED,
                    )
                )
            self._broadcast(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error_code': RuntimeErrorCode.PENDING_ACCEPTANCE_EXPIRED,
                    },
                )
            )
            if not preserved_live_connection:
                if self._config.get_int(SettingKey.LIVE_RECONNECT_DELAY) > 0:
                    self._schedule_live_reconnect(alias, onion)
                else:
                    self._router.convert_unacked_messages_to_drop(alias, onion)

    def _handle_live_incoming(
        self,
        conn: socket.socket,
        stream: TcpStreamReader,
        onion: str,
        has_recovery_hint: bool = False,
    ) -> None:
        """
        Evaluates tie-breakers and manages interactive live connections.

        Args:
            conn (socket.socket): The active socket connection.
            stream (TcpStreamReader): The constrained byte stream.
            onion (str): The peer's onion identity.
            has_recovery_hint (bool): Whether the remote AUTH frame requested a
                generic recovery replacement path.

        Returns:
            None
        """
        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        if not alias:
            conn.close()
            return

        is_outbound_attempt: bool = self._state.has_active_or_recent_outbound_attempt(
            onion
        )
        should_reject, is_mutual_winner = HandshakeProtocol.evaluate_tie_breaker(
            self._tm.onion, onion, is_outbound_attempt
        )

        transport_state = self._state.get_peer_transport_state(onion)
        grace_reconnect: bool = self._state.has_live_reconnect_grace(onion)
        retunnel_reconnect: bool = transport_state.is_retunneling
        scheduled_auto_reconnect: bool = self._state.has_scheduled_auto_reconnect(onion)
        trusted_recovery_hint: bool = False
        if has_recovery_hint:
            trusted_recovery_hint = (
                grace_reconnect
                or retunnel_reconnect
                or scheduled_auto_reconnect
                or transport_state.live_state is LiveTransportState.CONNECTED
            )

        if has_recovery_hint and self._state.has_local_recovery_opt_out(onion):
            try:
                conn.sendall(
                    (
                        f'{TorCommand.REJECT.value} '
                        f'{RejectIntent.MANUAL.value} {self._tm.onion}\n'
                    ).encode('utf-8')
                )
            except Exception:
                pass
            conn.close()
            return

        duplicate_reason_code: Optional[HistoryReasonCode] = None

        if (
            transport_state.live_state
            in (LiveTransportState.CONNECTED, LiveTransportState.PENDING)
            and not grace_reconnect
            and not retunnel_reconnect
            and not scheduled_auto_reconnect
            and not trusted_recovery_hint
        ):
            duplicate_reason_code = (
                HistoryReasonCode.DUPLICATE_INCOMING_CONNECTED
                if transport_state.live_state is LiveTransportState.CONNECTED
                else HistoryReasonCode.DUPLICATE_INCOMING_PENDING
            )
            should_reject = True

        if should_reject:
            try:
                conn.sendall(
                    f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                )
            except Exception:
                pass
            conn.close()

            if duplicate_reason_code is not None:
                self._hm.log_event(
                    HistoryEvent.REJECTED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    trigger=ConnectionOrigin.INCOMING,
                    detail_code=duplicate_reason_code,
                )
                return

            if (
                not scheduled_auto_reconnect
                and self._state.get_outbound_attempt_origin(onion)
                is ConnectionOrigin.MANUAL
            ):
                self._state.override_outbound_connected_origin(
                    onion,
                    ConnectionOrigin.MUTUAL_CONNECT,
                )

            rejection_origin: ConnectionOrigin = (
                ConnectionOrigin.AUTO_RECONNECT
                if scheduled_auto_reconnect
                else ConnectionOrigin.MUTUAL_CONNECT
            )
            self._hm.log_event(
                HistoryEvent.REJECTED,
                onion,
                actor=HistoryActor.SYSTEM,
                trigger=rejection_origin,
                detail_code=HistoryReasonCode.MUTUAL_TIEBREAKER_LOSER,
            )
            self._broadcast(
                ConnectionRejectedEvent(
                    alias=alias,
                    onion=onion,
                    origin=rejection_origin,
                    actor=ConnectionActor.SYSTEM,
                    reason_code=ConnectionReasonCode.MUTUAL_TIEBREAKER_LOSER,
                )
            )
            return

        contact_auto_accept: bool = (
            alias in self._cm.get_all_contacts()
            and self._config.get_bool(SettingKey.AUTO_ACCEPT_CONTACTS)
        )
        incoming_origin: ConnectionOrigin = ConnectionOrigin.INCOMING
        if grace_reconnect:
            incoming_origin = ConnectionOrigin.GRACE_RECONNECT
        elif retunnel_reconnect:
            incoming_origin = ConnectionOrigin.RETUNNEL
        elif scheduled_auto_reconnect:
            incoming_origin = ConnectionOrigin.AUTO_RECONNECT
        elif trusted_recovery_hint:
            incoming_origin = ConnectionOrigin.GRACE_RECONNECT
        elif is_mutual_winner:
            incoming_origin = ConnectionOrigin.MUTUAL_CONNECT
        elif contact_auto_accept:
            incoming_origin = ConnectionOrigin.AUTO_ACCEPT_CONTACT

        seamless_recovery_replacement: bool = (
            transport_state.live_state is LiveTransportState.CONNECTED
            and incoming_origin is ConnectionOrigin.GRACE_RECONNECT
        )

        should_auto_accept_now: bool = (
            grace_reconnect
            or retunnel_reconnect
            or scheduled_auto_reconnect
            or trusted_recovery_hint
            or is_mutual_winner
            or contact_auto_accept
        )

        accepted_now: bool = False
        pending_reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT
        allow_immediate_accept: bool = (
            is_mutual_winner
            or self._has_live_consumers()
            or self._allows_headless_live_backlog()
        )
        if should_auto_accept_now and allow_immediate_accept:
            if grace_reconnect:
                self._state.consume_live_reconnect_grace(onion)
            self._state.add_active_connection(onion, conn)
            accepted_now = True
        else:
            try:
                conn.sendall(f'{TorCommand.PENDING.value}\n'.encode('utf-8'))
            except Exception:
                pass
            if should_auto_accept_now:
                pending_reason = PendingConnectionReason.CONSUMER_ABSENT
            pending_registered: bool = self._state.add_pending_connection(
                onion,
                conn,
                stream.get_buffer(),
                reason=pending_reason,
                origin=incoming_origin,
            )
            if not pending_registered:
                return
            threading.Thread(
                target=self._watch_pending_connection,
                args=(onion, alias, conn),
                daemon=True,
            ).start()

        if accepted_now:
            try:
                conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
            except Exception:
                pass

            if not seamless_recovery_replacement:
                self._hm.log_event(
                    HistoryEvent.CONNECTED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    trigger=incoming_origin,
                )
            if self._state.consume_retunnel_reconnect(onion):
                self._hm.log_event(
                    HistoryEvent.RETUNNEL_SUCCEEDED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                )
                self._state.clear_retunnel_flow(onion)
                self._broadcast(RetunnelSuccessEvent(alias=alias, onion=onion))
            else:
                self._broadcast(
                    ConnectedEvent(
                        alias=alias,
                        onion=onion,
                        origin=incoming_origin,
                        actor=ConnectionActor.SYSTEM,
                    )
                )

            if self._receiver:
                self._receiver.start_receiving(
                    onion,
                    conn,
                    stream.get_buffer(),
                    connection_origin=incoming_origin,
                )
            self._router.replay_unacked_messages(onion)
        else:
            self._hm.log_event(
                HistoryEvent.REQUESTED,
                onion,
                actor=HistoryActor.REMOTE,
                trigger=(
                    incoming_origin
                    if pending_reason is PendingConnectionReason.CONSUMER_ABSENT
                    else ConnectionOrigin.INCOMING
                ),
            )
            if pending_reason is PendingConnectionReason.USER_ACCEPT:
                self._broadcast(
                    IncomingConnectionEvent(
                        alias=alias,
                        onion=onion,
                        origin=ConnectionOrigin.INCOMING,
                        actor=ConnectionActor.REMOTE,
                    )
                )
