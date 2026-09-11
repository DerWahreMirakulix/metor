"""Session access event and terminal socket helpers."""

import socket

from metor.core.api import EventType, IpcEvent, create_event

from ..local_auth import SessionAuthPrompt


class SessionEventMixin:
    """Builds authentication events and closes rejected IPC sessions."""

    @staticmethod
    def _session_auth_event(
        event_type: EventType, prompt: SessionAuthPrompt
    ) -> IpcEvent:
        """Builds one session-auth challenge event.

        Args:
            event_type (EventType): The event type to create.
            prompt (SessionAuthPrompt): The challenge payload.

        Returns:
            IpcEvent: The typed authentication event.
        """
        return create_event(
            event_type,
            {'challenge': prompt.challenge, 'salt': prompt.salt},
        )

    @staticmethod
    def _rate_limited_event(retry_after: int) -> IpcEvent:
        """Builds one local-auth cooldown event.

        Args:
            retry_after (int): Remaining cooldown seconds.

        Returns:
            IpcEvent: The typed rate-limit event.
        """
        return create_event(
            EventType.LOCAL_AUTH_RATE_LIMITED,
            {'retry_after': retry_after},
        )

    @staticmethod
    def _disconnect_client(conn: socket.socket) -> None:
        """Closes one IPC socket after terminal authentication failure.

        Args:
            conn (socket.socket): The client socket.

        Returns:
            None
        """
        try:
            conn.close()
        except OSError:
            pass
