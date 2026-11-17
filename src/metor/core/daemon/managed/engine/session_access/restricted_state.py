"""Read-only projection of the requesting client's current restriction policy."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from metor.core.api import RestrictedClientStateEvent

if TYPE_CHECKING:
    from .controller import SessionAccessController


def restricted_state(
    owner: SessionAccessController, conn: socket.socket
) -> RestrictedClientStateEvent:
    """Returns policy only; owned Calls have a separate privacy-scoped projection.

    Args:
        owner: Core session authorization owner.
        conn: Authenticated or restricted requesting connection.
    Returns:
        RestrictedClientStateEvent: Effective policy without chat/media access.
    """
    policy = owner.restricted_policy(conn)
    if policy is None:
        return RestrictedClientStateEvent()
    return RestrictedClientStateEvent(
        restricted=True,
        notification_privacy=policy.notification_privacy,
        accept_calls_locked=policy.accept_calls_locked,
    )
