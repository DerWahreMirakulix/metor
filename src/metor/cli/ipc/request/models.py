"""Models describing one CLI-side IPC request result."""

from dataclasses import dataclass
from typing import Optional

from metor.core.api import IpcEvent


@dataclass(frozen=True)
class IpcRequestResult:
    """Result of one CLI-side IPC request exchange."""

    event: Optional[IpcEvent] = None
    message: Optional[str] = None
    insert_leading_blank_line: bool = False
    auth_incomplete: bool = False
