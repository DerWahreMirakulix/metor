"""Frontend-independent streaming audio ports; input and output have separate owners."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioCapabilities:
    """Observed native availability; enumeration never proves acoustic suitability."""

    input_available: bool
    output_available: bool
    speaker_aec: bool = False


@dataclass(frozen=True)
class AudioEndpoint:
    """Native route descriptor that does not open a stream."""

    index: int
    name: str
    input_available: bool
    output_available: bool


class CapturePort(Protocol):
    """Bounded encoded input; cancellation must not interrupt independent output."""

    failed: bool

    def start_capture(self, *, headset_confirmed: bool) -> None:
        """Opens input after explicit route and capture admission.

        Args:
            headset_confirmed: Caller has explicitly confirmed the headset route.
        Returns:
            None
        """
        ...

    def stop_capture(self) -> None:
        """Stops input while retaining complete frames for final handoff.

        Args:
            None
        Returns:
            None
        """
        ...

    def interrupt_capture(self) -> None:
        """Signals cancellation without waiting for a blocked consumer.

        Args:
            None
        Returns:
            None
        """
        ...

    def take_frame(self) -> bytes | None:
        """Transfers one bounded complete frame without blocking.

        Args:
            None
        Returns:
            bytes | None: Next frame, or no frame currently available.
        """
        ...

    def discard_capture(self) -> None:
        """Releases retained input after handoff or explicit abandonment.

        Args:
            None
        Returns:
            None
        """
        ...


class OutputPort(Protocol):
    """Bounded output; stopping playback never implicitly consumes Core content."""

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Writes complete encoded samples or raises on unconfirmed output.

        Args:
            frame: Bounded frame in the route's agreed codec.
            headset_confirmed: Explicit headset route confirmation.
        Returns:
            None
        """
        ...

    def stop_output(self) -> None:
        """Stops output independently of simultaneous microphone ownership.

        Args:
            None
        Returns:
            None
        """
        ...
