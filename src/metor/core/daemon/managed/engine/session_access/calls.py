"""Connection-owned handles that bind call actions to an exact pending socket."""

from __future__ import annotations

from dataclasses import replace
import secrets
import socket
import time
from typing import TYPE_CHECKING

from metor.core.api import (
    AcceptCommand,
    ChatStartupStateEvent,
    IncomingConnectionEvent,
    IpcEvent,
    PendingConnectionExpiredEvent,
    RejectCommand,
    RuntimeSnapshotEvent,
    NoPendingConnectionEvent,
    ConnectedEvent,
)
from metor.utils import Constants

# Local Package Imports
from .grants import PendingCallGrant

if TYPE_CHECKING:
    from .controller import SessionAccessController


def issue_handle(
    owner: SessionAccessController, conn: socket.socket, onion: str, token: str | None
) -> str | None:
    """Projects a source-qualified request into one recipient's bounded authority.

    Args:
        owner: Authentication and runtime owner.
        conn: Recipient IPC connection.
        onion: Canonical request peer.
        token: Exact transport token captured by the original projection.
    Returns:
        str | None: Stable per-client handle; stale source projections get no handle.
    """
    with owner._lock:
        pending = owner._pending_call(onion)
        if pending is None:
            return None
        if owner._pending_token is not None and (
            token is None or token != owner._pending_token(onion)
        ):
            return None
        handles = owner._call_handles.setdefault(conn, {})
        for handle, grant in tuple(handles.items()):
            if not owner._valid_call_grant(conn, grant):
                handles.pop(handle, None)
        for handle, grant in handles.items():
            if grant.onion == onion and grant.pending is pending[0]:
                return handle
        if len(handles) >= Constants.MAX_ANONYMOUS_CALL_HANDLES:
            return None
        handle = secrets.token_urlsafe(Constants.PENDING_CALL_TOKEN_BYTES)
        handles[handle] = PendingCallGrant(
            onion,
            owner._restriction_generations.get(conn, 0),
            owner._auth_runtime_generation,
            pending[0],
            min(pending[1], time.time() + Constants.PENDING_EXPIRY_FEEDBACK_WINDOW_SEC),
        )
        return handle


def project_event(
    owner: SessionAccessController, conn: socket.socket, event: IpcEvent
) -> IpcEvent:
    """Replaces internal source tokens with recipient-specific action handles.

    Args:
        owner: Session authority owner.
        conn: Recipient connection.
        event: Original Core event, never mutated for other recipients.
    Returns:
        IpcEvent: Recipient-owned event projection without transport tokens.
    """
    if isinstance(event, IncomingConnectionEvent):
        handle = (
            issue_handle(owner, conn, event.onion, event.action_handle)
            if event.onion is not None
            else None
        )
        return replace(event, action_handle=handle)
    if isinstance(event, PendingConnectionExpiredEvent):
        handle = None
        with owner._lock:
            handles = owner._call_handles.get(conn, {})
            for candidate, grant in tuple(handles.items()):
                if grant.onion == event.onion and not owner._valid_call_grant(
                    conn, grant
                ):
                    handle = candidate
                    handles.pop(candidate, None)
                    break
        return replace(event, action_handle=handle)
    return event


def project_snapshot(
    owner: SessionAccessController, conn: socket.socket, event: IpcEvent
) -> IpcEvent:
    """Qualifies each pending snapshot row before it leaves the authenticated service.

    Args:
        owner: Session authority owner.
        conn: Authorized snapshot recipient.
        event: Public runtime or startup projection.
    Returns:
        IpcEvent: Snapshot whose handles refer only to their original pending sockets.
    """
    if not isinstance(event, (RuntimeSnapshotEvent, ChatStartupStateEvent)):
        return event
    projected = replace(
        event,
        pending=[
            replace(
                entry,
                action_handle=issue_handle(
                    owner, conn, entry.onion, entry.action_handle
                )
                if entry.onion is not None
                else None,
            )
            for entry in event.pending
        ],
    )
    if isinstance(projected, RuntimeSnapshotEvent):
        with owner._lock:
            accepted = owner._accepted_calls.get(conn, {})
            for handle, (onion, context, _generation) in tuple(accepted.items()):
                if owner._live_context(onion) != context:
                    accepted.pop(handle, None)
            projected.live_contexts = [
                replace(
                    entry,
                    call_handle=next(
                        (
                            handle
                            for handle, (
                                onion,
                                _context,
                                generation,
                            ) in accepted.items()
                            if onion == entry.onion
                            and generation == entry.context_generation
                        ),
                        None,
                    ),
                )
                for entry in projected.live_contexts
            ]
    return projected


def observe_transition(owner: SessionAccessController, event: IpcEvent) -> None:
    """Carries existing request handles into their exact positively accepted socket.

    Args:
        owner: Core session authority owner.
        event: Authoritative transport event before public privacy projection.
    Returns:
        None
    """
    if not isinstance(event, ConnectedEvent):
        return
    active = owner._active_connection(event.onion)
    generation = owner._live_generation(event.onion)
    if active is None or generation is None:
        return
    with owner._lock:
        accepted = [
            (conn, handle)
            for conn, handles in owner._call_handles.items()
            for handle, grant in handles.items()
            if grant.onion == event.onion
            and grant.pending is active
            and grant.runtime == owner._auth_runtime_generation
            and grant.restriction == owner._restriction_generations.get(conn, 0)
        ]
    for conn, handle in accepted:
        record_accepted(owner, conn, handle, event.onion, generation)


def record_accepted(
    owner: SessionAccessController,
    conn: socket.socket,
    handle: str,
    onion: str,
    generation: int,
) -> None:
    """Binds an accepted call handle to one still-authorized logical LIVE context.

    Args:
        owner: Session access owner.
        conn: Accepting connection.
        handle: Consumed exact request identity.
        onion: Positively accepted peer.
        generation: Positively accepted context generation.
    Returns:
        None
    """
    context = owner._live_context(onion)
    if context is None:
        return
    with owner._lock:
        accepted = owner._accepted_calls.setdefault(conn, {})
        for previous, (peer, old_context, _generation) in tuple(accepted.items()):
            if peer == onion or owner._live_context(peer) != old_context:
                accepted.pop(previous, None)
        if len(accepted) >= Constants.MAX_ANONYMOUS_CALL_HANDLES:
            accepted.pop(next(iter(accepted)))
        accepted[handle] = (onion, context, generation)


def authorize_action(
    owner: SessionAccessController,
    conn: socket.socket,
    command: AcceptCommand | RejectCommand,
) -> bool:
    """Consumes an explicit handle only after ordinary session authorization.

    Args:
        owner: Session authority owner.
        conn: Fully authorized requesting connection.
        command: Action carrying a per-client handle; legacy absence is preserved.
    Returns:
        bool: Whether dispatch may use the exact socket transferred by the handle.
    """
    if command.action_handle is None:
        return True
    with owner._lock:
        grant = owner._call_handles.get(conn, {}).get(command.action_handle)
        valid = grant is not None and owner._valid_call_grant(conn, grant)
    if not valid or grant is None:
        owner._send(conn, NoPendingConnectionEvent(alias='unknown'))
        return False
    command.target = grant.onion
    owner._consume_call_handle(conn, command.action_handle)
    return True
