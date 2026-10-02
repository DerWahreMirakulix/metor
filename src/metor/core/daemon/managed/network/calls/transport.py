"""CALL-only authenticated transport and bounded lifecycle supervision."""

import socket
import time
from typing import TYPE_CHECKING

from metor.core.api import CallReason, CallState
from metor.core.daemon.managed.models import TorCommand
from metor.shared.constants import Constants
from metor.versioning import (
    PEER_PROTOCOL_MIN_SUPPORTED,
    PEER_PROTOCOL_VERSION,
    negotiate_protocol_generation,
)

# Local Package Imports
from ..handshake import HandshakeProtocol
from ..stream import TcpStreamReader
from .models import CallSession

if TYPE_CHECKING:
    from .controller import CallController


def connect(controller: 'CallController', session: CallSession) -> None:
    """Borrows accepted chat or opens CALL transport without requesting LIVE consent."""
    connection: socket.socket | None = None
    try:
        connection = controller.transport_state.get_connection(session.info.peer)
        borrowed = connection is not None
        if connection is None:
            connection = controller.tm.connect(session.info.peer)
            with controller.lock:
                cancelled = session.info.state is not CallState.CONNECTING
                if not cancelled:
                    session.connection = connection
                    controller.exclusive_sockets.add(connection)
            if cancelled:
                controller.transport_state.retire_connection(connection)
                return
            connection.settimeout(Constants.CALL_PEER_TIMEOUT_SEC)
            stream = TcpStreamReader(connection)
            challenge_line = stream.read_line()
            if challenge_line is None:
                raise ConnectionError('Call authentication incomplete.')
            challenge, peer_current, peer_min = HandshakeProtocol.parse_challenge_line(
                challenge_line
            )
            if (
                negotiate_protocol_generation(
                    PEER_PROTOCOL_VERSION,
                    PEER_PROTOCOL_MIN_SUPPORTED,
                    peer_current,
                    peer_min,
                )
                is None
            ):
                controller.finish(session, CallReason.UNSUPPORTED)
                return
            signature = controller.crypto.sign_challenge(challenge)
            if signature is None or controller.tm.onion is None:
                raise ConnectionError('Call authentication unavailable.')
            controller.transport_state.send_frame(
                connection,
                HandshakeProtocol.build_auth_line(
                    controller.tm.onion, signature, is_call=True
                ).encode('ascii'),
            )
        with controller.lock:
            cancelled = session.info.state is not CallState.CONNECTING
            if not cancelled:
                session.connection = connection
                session.borrowed = borrowed
                session.info.state = CallState.OUTGOING
                session.last_peer = time.monotonic()
        if cancelled:
            if not borrowed:
                controller.transport_state.retire_connection(connection)
            return
        if not controller.send(
            session,
            f'{TorCommand.CALL_OFFER.value} {session.wire_id} {Constants.CALL_CODEC} {session.tick()}\n',
        ):
            return
        controller._emit(session)
        if not borrowed:
            receive(controller, session.info.peer, connection, stream)
    except (OSError, ValueError, RuntimeError, MemoryError):
        controller.finish(session, CallReason.TRANSPORT_LOST)
        if connection is not None and connection is not session.connection:
            controller.transport_state.retire_connection(connection)


def receive(
    controller: 'CallController',
    onion: str,
    connection: socket.socket,
    stream: TcpStreamReader,
) -> None:
    """Reads only dedicated CALL frames; the socket never enters LIVE state."""
    try:
        stream = TcpStreamReader(
            connection, stream.get_buffer(), max_bytes=Constants.CALL_MAX_FRAME_BYTES
        )
        connection.settimeout(Constants.CALL_KEEPALIVE_SEC)
        while not controller.closed.is_set() and not controller.stop_flag.is_set():
            try:
                line = stream.read_line()
            except socket.timeout:
                with controller.lock:
                    tracked = any(
                        s.connection is connection
                        and s.info.state is not CallState.ENDED
                        for s in controller.sessions.values()
                    )
                if not tracked:
                    break
                continue
            if line is None or not controller.process_frame(
                onion, connection, line, borrowed=False
            ):
                break
            with controller.lock:
                if any(
                    s.connection is connection and s.info.state is CallState.ENDED
                    for s in controller.sessions.values()
                ):
                    break
    except (OSError, ValueError, RuntimeError, MemoryError):
        pass
    finally:
        controller.transport_lost(connection)
        controller.transport_state.retire_connection(connection, preserve_final=True)


def monitor(controller: 'CallController') -> None:
    """Expires requests, retires dead transports, and keeps muted calls live without audio."""
    while (
        not controller.closed.wait(Constants.CALL_KEEPALIVE_SEC)
        and not controller.stop_flag.is_set()
    ):
        now = time.monotonic()
        with controller.lock:
            sessions = [
                s
                for s in controller.sessions.values()
                if s.info.state is not CallState.ENDED
            ]
        for session in sessions:
            if session.borrowed:
                current = controller.transport_state.get_connection(session.info.peer)
                with controller.lock:
                    missing_chat = (
                        session.borrowed and current is not session.connection
                    )
            else:
                missing_chat = False
            if missing_chat:
                controller.finish(session, CallReason.TRANSPORT_LOST)
            elif session.info.state is not CallState.ACTIVE and now >= session.deadline:
                controller.finish(session, CallReason.TIMEOUT, notify=True)
            elif (
                session.connection is not None
                and now - session.last_peer >= Constants.CALL_PEER_TIMEOUT_SEC
            ):
                controller.finish(session, CallReason.TRANSPORT_LOST)
            elif (
                session.connection is not None
                and now - session.last_ping >= Constants.CALL_KEEPALIVE_SEC
            ):
                session.last_ping = now
                controller.send(
                    session,
                    f'{TorCommand.CALL_PING.value} {session.wire_id} {session.tick()}\n',
                )
