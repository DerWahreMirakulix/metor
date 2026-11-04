"""Strict call signaling scoped to the authenticated peer, socket, and exact identity."""

import socket
import secrets
import time
from typing import TYPE_CHECKING

from metor.core.api import CallInfo, CallReason, CallState, is_valid_message_id
from metor.core.daemon.managed.models import TorCommand
from metor.shared.constants import Constants

# Local Package Imports
from .models import CallSession
from .media import receive_audio

if TYPE_CHECKING:
    from .controller import CallController


def _wire_session(
    controller: 'CallController', onion: str, connection: socket.socket, wire_id: str
) -> CallSession | None:
    """Finds a wire identity only within its authenticated socket lifetime."""
    return next(
        (
            session
            for session in controller.sessions.values()
            if session.wire_id == wire_id
            and session.info.peer == onion
            and session.connection is connection
        ),
        None,
    )


def _parse_tick(value: str) -> int | None:
    """Validates a bounded nonnegative call-relative peer timestamp."""
    try:
        tick = int(value)
    except ValueError:
        return None
    return tick if 0 <= tick <= Constants.CALL_FRAME_SEQUENCE_MAX else None


def process_frame(
    controller: 'CallController',
    onion: str,
    connection: socket.socket,
    line: str,
    borrowed: bool,
) -> bool:
    """Consumes dedicated frames; malformed or cross-socket traffic cannot grant audio."""
    parts = line.split()
    if (
        len(parts) < 2
        or not parts[0].startswith(Constants.CALL_FRAME_PREFIX)
        or not is_valid_message_id(parts[1])
    ):
        return False
    kind, call_id = parts[:2]
    if kind == TorCommand.CALL_OFFER.value:
        if len(parts) != 4 or parts[2] != Constants.CALL_CODEC:
            return False
        offer_tick = _parse_tick(parts[3])
        if offer_tick is None:
            return False
        alias = controller.cm.ensure_alias_for_onion(onion)
        if alias is None:
            return False
        with controller.lock:
            existing = _wire_session(controller, onion, connection, call_id)
            if (
                existing is not None
                and existing.info.peer == onion
                and existing.connection is connection
                and existing.info.state in (CallState.INCOMING, CallState.ACTIVE)
            ):
                return True
            seen = controller.offered_ids.setdefault(connection, set())
            if (
                call_id in seen
                or len(seen) >= Constants.CALL_TRANSPORT_IDENTITIES_MAX
                or not controller._available()
            ):
                busy = True
            else:
                busy = False
                seen.add(call_id)
                incoming = CallSession(
                    CallInfo(
                        call_id=secrets.token_hex(Constants.CALL_ID_BYTES),
                        peer=onion,
                        alias=alias,
                        state=CallState.INCOMING,
                    ),
                    wire_id=call_id,
                    connection=connection,
                    borrowed=borrowed,
                )
                controller._remember(incoming)
                incoming.observe_clock(offer_tick)
                if not borrowed:
                    controller.exclusive_sockets.add(connection)
        if busy:
            frame = f'{TorCommand.CALL_END.value} {call_id} {CallReason.BUSY.value}\n'.encode(
                'ascii'
            )
            if borrowed:
                controller.transport_state.send_frame(connection, frame)
            else:
                controller.transport_state.finish_connection(connection, frame)
                controller.transport_state.retire_connection(
                    connection, preserve_final=True
                )
        else:
            controller._emit(incoming)
        return True

    if kind == TorCommand.CALL_CHAT_END.value and len(parts) == 2:
        with controller.lock:
            shared = _wire_session(controller, onion, connection, call_id)
            allowed = (
                shared is not None
                and shared.info.peer == onion
                and shared.connection is connection
                and shared.borrowed
                and shared.info.state is not CallState.ENDED
            )
        if allowed and controller.chat_end is not None:
            controller.chat_end(onion, connection)
        return True

    with controller.lock:
        session = _wire_session(controller, onion, connection, call_id)
        if (
            session is None
            or session.info.peer != onion
            or session.connection is not connection
            or session.info.state is CallState.ENDED
        ):
            # Late media/controls from a revoked call are ignored, never reauthorized.
            return kind in (
                TorCommand.CALL_AUDIO.value,
                TorCommand.CALL_END.value,
                TorCommand.CALL_PING.value,
                TorCommand.CALL_ACCEPT.value,
            )
        session.last_peer = time.monotonic()
        if kind == TorCommand.CALL_ACCEPT.value and len(parts) == 3:
            if session.info.state is not CallState.OUTGOING:
                return False
            accept_tick = _parse_tick(parts[2])
            if accept_tick is None:
                return False
            session.observe_clock(accept_tick)
            session.info.state = CallState.ACTIVE
            session.info.started_at = time.time()
            session.frames.clear()
            accepted = True
        else:
            accepted = False
        if kind == TorCommand.CALL_AUDIO.value and len(parts) == 5:
            try:
                sequence = int(parts[2])
            except ValueError:
                return False
            audio_tick = _parse_tick(parts[3])
            if audio_tick is None:
                return False
            return receive_audio(session, sequence, audio_tick, parts[4])
        if kind == TorCommand.CALL_PING.value and len(parts) == 3:
            ping_tick = _parse_tick(parts[2])
            if ping_tick is None:
                return False
            session.observe_clock(ping_tick)
            return True
    if accepted:
        controller._emit(session)
        return True
    if kind == TorCommand.CALL_END.value and len(parts) == 3:
        try:
            reason = CallReason(parts[2])
        except ValueError:
            return False
        if reason not in (
            CallReason.REJECTED,
            CallReason.CANCELLED,
            CallReason.HUNG_UP,
            CallReason.BUSY,
            CallReason.TIMEOUT,
            CallReason.CLIENT_LOST,
            CallReason.PROFILE_LOCKED,
            CallReason.TRANSPORT_LOST,
        ):
            return False
        controller.finish(session, reason)
        return True
    return False
