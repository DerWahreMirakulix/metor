"""Public connection-bound Voice lease; no frontend persistence or blob ownership."""

from metor.client import MetorClient
from metor.core.api import (
    RegisterVoiceOwnerCommand,
    ReleaseVoiceOwnerCommand,
    VoiceOwnerRegisteredEvent,
    VoiceOwnerReleasedEvent,
)


class VoiceOwnerLease:
    """Keeps only the current Core-issued token in volatile GUI memory."""

    def __init__(self) -> None:
        """Creates an inert lease before authenticated bootstrap.

        Args:
            None
        Returns:
            None
        """
        self.token: str | None = None

    @staticmethod
    def register(client: MetorClient) -> VoiceOwnerRegisteredEvent | None:
        """Requests the protected disposable policy on an authenticated connection.

        Args:
            client: Current public SDK client advertising the capability.
        Returns:
            VoiceOwnerRegisteredEvent | None: Confirmed lease or unconfirmed failure.
        """
        return client.request(RegisterVoiceOwnerCommand(), VoiceOwnerRegisteredEvent)

    @staticmethod
    def detach(client: MetorClient, token: str | None, purging: bool = False) -> None:
        """Explicitly releases owned staging and always closes this IPC connection.

        Args:
            client: Captured departing client, never a replacement connection.
            token: Captured departing owner's opaque token.
            purging: Accepted purge forbids ordinary producer finalization requests.
        Returns:
            None
        """
        try:
            if token is not None and not purging:
                client.request(ReleaseVoiceOwnerCommand(token), VoiceOwnerReleasedEvent)
        except Exception:
            # Confirmed disconnect invokes Core's durable owner-loss recovery.
            pass
        finally:
            client.disconnect()
