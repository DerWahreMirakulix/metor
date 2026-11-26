"""Typed helper models for the chat event package."""

from dataclasses import dataclass
import threading
from typing import Optional


@dataclass
class BufferedInboxNotification:
    """Stores one aggregated pending inbox notification for delayed UI rendering."""

    alias: str
    onion: Optional[str]
    count: int
    timer: threading.Timer
