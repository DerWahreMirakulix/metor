"""Authenticated drop-tunnel establishment and synchronized cache ownership."""

import socket
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from metor.core.tor import TorManager
from metor.core.daemon.managed.models import PrimaryTransport
from metor.data import HistoryActor, HistoryEvent, HistoryManager, SettingKey
from metor.versioning import (
    PEER_PROTOCOL_MIN_SUPPORTED,
    PEER_PROTOCOL_VERSION,
    negotiate_protocol_generation,
)

# Local Package Imports
from ..crypto import Crypto
from ..network import HandshakeProtocol, StateTracker, TcpStreamReader

if TYPE_CHECKING:
    from metor.data.profile import Config


class DropTunnelManager:
    """Owns authenticated drop connections and the persistent tunnel cache."""

    def __init__(
        self,
        tm: TorManager,
        hm: HistoryManager,
        crypto: Crypto,
        state: StateTracker,
        config: 'Config',
    ) -> None:
        """Initializes tunnel establishment and cache dependencies.

        Args:
            tm (TorManager): Tor network manager for outbound connections.
            hm (HistoryManager): Transport history manager.
            crypto (Crypto): Peer handshake signing service.
            state (StateTracker): Shared transport state.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._hm: HistoryManager = hm
        self._crypto: Crypto = crypto
        self._state: StateTracker = state
        self._config: 'Config' = config
        self._tunnels: Dict[str, Tuple[socket.socket, TcpStreamReader, float]] = {}
        self._lock: threading.Lock = threading.Lock()

    def acquire(self, onion: str) -> Optional[Tuple[socket.socket, TcpStreamReader]]:
        """Returns a cached tunnel or establishes and caches a new one.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[Tuple[socket.socket, TcpStreamReader]]: The usable tunnel.
        """
        with self._lock:
            cached: Optional[Tuple[socket.socket, TcpStreamReader, float]] = (
                self._tunnels.get(onion)
            )
        if cached is not None:
            return cached[0], cached[1]

        tunnel: Optional[Tuple[socket.socket, TcpStreamReader]] = self.establish(onion)
        if tunnel is None:
            return None

        conn, stream = tunnel
        with self._lock:
            self._tunnels[onion] = (conn, stream, time.time())
        self._state.mark_drop_tunnel_open(onion)
        self._hm.log_event(
            HistoryEvent.TUNNEL_CONNECTED,
            onion,
            actor=HistoryActor.SYSTEM,
        )
        return tunnel

    def establish(self, onion: str) -> Optional[Tuple[socket.socket, TcpStreamReader]]:
        """Establishes one authenticated asynchronous peer tunnel.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[Tuple[socket.socket, TcpStreamReader]]: The authenticated
                socket and stream reader, or None on failure.
        """
        conn: Optional[socket.socket] = None
        try:
            conn = self._tm.connect(onion)
            conn.settimeout(self._config.get_float(SettingKey.TOR_TIMEOUT))
            stream = TcpStreamReader(conn)
            challenge_line: Optional[str] = stream.read_line()
            if not challenge_line:
                conn.close()
                return None

            challenge, peer_current, peer_minimum = (
                HandshakeProtocol.parse_challenge_line(challenge_line)
            )
            negotiated_version: Optional[int] = negotiate_protocol_generation(
                PEER_PROTOCOL_VERSION,
                PEER_PROTOCOL_MIN_SUPPORTED,
                peer_current,
                peer_minimum,
            )
            if negotiated_version is None:
                raise ValueError('Peer protocol ranges do not overlap')

            signature: Optional[str] = self._crypto.sign_challenge(challenge)
            if not signature:
                conn.close()
                return None

            local_onion: Optional[str] = self._tm.onion
            if not local_onion:
                conn.close()
                return None

            conn.sendall(
                HandshakeProtocol.build_auth_line(
                    local_onion,
                    signature,
                    is_async=True,
                ).encode('utf-8')
            )
            return conn, stream
        except Exception:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            return None

    def touch(self, onion: str, conn: socket.socket, stream: TcpStreamReader) -> None:
        """Refreshes cached and shared activity after a successful write.

        Args:
            onion (str): The peer onion identity.
            conn (socket.socket): The cached tunnel socket.
            stream (TcpStreamReader): The cached tunnel stream.

        Returns:
            None
        """
        with self._lock:
            if onion in self._tunnels:
                self._tunnels[onion] = (conn, stream, time.time())
        self._state.touch_drop_tunnel(onion)

    def cleanup(self, standby_drop_allowed: bool) -> None:
        """Closes tunnels disallowed by focus, idle, or transport policy.

        Args:
            standby_drop_allowed (bool): Whether drop standby may coexist with
                an active session.

        Returns:
            None
        """
        idle_timeout: float = self._config.get_float(
            SettingKey.DROP_TUNNEL_IDLE_TIMEOUT
        )
        now: float = time.time()
        expired_onions: List[str] = []
        with self._lock:
            tunnel_items: List[
                Tuple[str, Tuple[socket.socket, TcpStreamReader, float]]
            ] = list(self._tunnels.items())

        for onion, (_, _, last_used) in tunnel_items:
            if (
                self._state.get_primary_transport(
                    onion,
                    standby_drop_allowed=standby_drop_allowed,
                )
                is PrimaryTransport.SESSION
                and not standby_drop_allowed
            ):
                expired_onions.append(onion)
                continue
            if idle_timeout == 0.0:
                expired_onions.append(onion)
                continue
            if self._state.is_focused_by_ui(onion):
                continue
            if (now - last_used) > idle_timeout:
                expired_onions.append(onion)

        for onion in expired_onions:
            self.close(onion)

    def close(self, onion: str) -> None:
        """Closes and forgets one cached tunnel.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        with self._lock:
            tunnel: Optional[Tuple[socket.socket, TcpStreamReader, float]] = (
                self._tunnels.pop(onion, None)
            )
        if tunnel is None:
            return

        self._state.clear_drop_tunnel(onion)
        try:
            tunnel[0].close()
            self._hm.log_event(
                HistoryEvent.TUNNEL_CLOSED,
                onion,
                actor=HistoryActor.SYSTEM,
            )
        except Exception:
            pass

    def close_all(self) -> None:
        """Closes every cached tunnel.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            onions: List[str] = list(self._tunnels)
        for onion in onions:
            self.close(onion)
