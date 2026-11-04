"""Exact-owner voice review and explicitly published local message metadata."""

from dataclasses import dataclass

from metor.core.api import Delivery, MessageStatusCode

# Local Package Imports
from .press import CaptureBinding


@dataclass
class VoiceReview:
    """Volatile exact-owner review metadata, never a local audio file or sent message."""

    binding: CaptureBinding
    size_bytes: int
    duration_ms: int | None
    unknown: bool = False


@dataclass
class LocalVoiceTurn:
    """Stable same-runtime metadata for an explicitly published LIVE voice message."""

    binding: CaptureBinding
    size_bytes: int = 0
    duration_ms: int | None = None
    finalized: bool = False
    actual_delivery: Delivery = Delivery.LIVE
    status: MessageStatusCode = MessageStatusCode.PENDING
    order: int = 0
