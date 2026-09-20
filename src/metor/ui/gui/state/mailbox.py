"""Bounded generation-tagged worker-to-GUI handoff with explicit overload."""

from collections import deque
from dataclasses import asdict, dataclass
import json
import threading

from metor.core.api import IpcEvent
from metor.client import FrontendProfileCatalog, FrontendProfileOperationResult
from metor.ui.gui.constants import GuiLimits
from metor.client.platform import AudioEndpoint

# Local Package Imports
from .media import PlaybackProgress


@dataclass(frozen=True)
class Update:
    """One typed operation result or content event from a worker."""

    generation: int
    operation: str
    event: IpcEvent | None = None
    status: str = ''
    audio_endpoints: tuple[AudioEndpoint, ...] | None = None
    playback: PlaybackProgress | None = None
    profile_catalog: FrontendProfileCatalog | None = None
    profile_result: FrontendProfileOperationResult | None = None


class Mailbox:
    """Limits GUI handoff memory and retains a separate overload signal."""

    def __init__(self) -> None:
        """Creates an empty synchronized queue.

        Args:
            None
        Returns:
            None
        """
        self._records: deque[tuple[Update, int]] = deque()
        self._bytes: int = 0
        self._lock = threading.Lock()
        self.overloaded: bool = False

    def put(self, update: Update) -> bool:
        """Admits within both budgets; rejection requires transport resynchronization.

        Args:
            update: Typed record whose payload is accounted before admission.
        Returns:
            bool: Whether the update was retained.
        """
        size = len(update.event.to_json().encode('utf-8')) if update.event else 0
        size += len(update.status.encode('utf-8')) + len(
            update.operation.encode('utf-8')
        )
        if update.audio_endpoints is not None:
            size += len(
                json.dumps([asdict(item) for item in update.audio_endpoints]).encode(
                    'utf-8'
                )
            )
        if update.playback is not None:
            size += len(json.dumps(asdict(update.playback)).encode('utf-8'))
        for local in (update.profile_catalog, update.profile_result):
            if local is not None:
                size += len(json.dumps(asdict(local)).encode('utf-8'))
        with self._lock:
            if (
                len(self._records) >= GuiLimits.QUEUE_RECORDS
                or self._bytes + size > GuiLimits.QUEUE_BYTES
            ):
                self.overloaded = True
                return False
            self._records.append((update, size))
            self._bytes += size
            return True

    def take(self) -> Update | None:
        """Removes one FIFO record without waiting on the UI thread.

        Args:
            None
        Returns:
            Update | None: Next update, if present.
        """
        with self._lock:
            if not self._records:
                return None
            update, size = self._records.popleft()
            self._bytes -= size
            return update

    def clear(self) -> None:
        """Drops abandoned profile references under the queue lock.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            self._records.clear()
            self._bytes = 0
            self.overloaded = False
