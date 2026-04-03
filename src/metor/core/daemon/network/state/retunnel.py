"""Reconnect-grace and retunnel state mixins."""

import threading
import time
from typing import Dict, Optional, Set


class StateTrackerRetunnelMixin:
    """Encapsulates reconnect grace windows and retunnel lifecycle markers."""

    _lock: threading.Lock
    _live_reconnect_grace: Dict[str, float]
    _retunnel_reconnects: Set[str]
    _retunnel_in_progress: Set[str]
    _retunnel_recovery_retry_counts: Dict[str, int]
    _retunnel_recovery_retry_pending: Set[str]

    def mark_live_reconnect_grace(self, onion: str, grace_timeout_sec: float) -> None:
        """Marks a peer as eligible for a short incoming auto-accept reconnect window."""
        with self._lock:
            if grace_timeout_sec <= 0:
                self._live_reconnect_grace.pop(onion, None)
                return

            self._live_reconnect_grace[onion] = time.time() + grace_timeout_sec

    def consume_live_reconnect_grace(self, onion: str) -> bool:
        """Consumes an incoming reconnect grace window if it is still valid."""
        with self._lock:
            expires_at: Optional[float] = self._live_reconnect_grace.get(onion)
            if expires_at is None:
                return False

            if expires_at < time.time():
                del self._live_reconnect_grace[onion]
                return False

            del self._live_reconnect_grace[onion]
            return True

    def has_live_reconnect_grace(self, onion: str) -> bool:
        """Checks whether an inbound reconnect grace window is still valid."""
        with self._lock:
            expires_at: Optional[float] = self._live_reconnect_grace.get(onion)
            if expires_at is None:
                return False

            if expires_at < time.time():
                del self._live_reconnect_grace[onion]
                return False

            return True

    def has_retunnel_recovery_retry_pending(self, onion: str) -> bool:
        """Checks whether one delayed retunnel recovery retry is already scheduled."""
        with self._lock:
            return onion in self._retunnel_recovery_retry_pending

    def reserve_retunnel_recovery_retry(
        self,
        onion: str,
        retry_limit: int,
    ) -> Optional[int]:
        """Reserves one bounded delayed retunnel recovery retry."""
        with self._lock:
            if onion not in self._retunnel_in_progress:
                return None

            if onion in self._retunnel_recovery_retry_pending:
                return None

            attempt: int = self._retunnel_recovery_retry_counts.get(onion, 0)
            if attempt >= retry_limit:
                return None

            attempt += 1
            self._retunnel_recovery_retry_counts[onion] = attempt
            self._retunnel_recovery_retry_pending.add(onion)
            return attempt

    def finish_retunnel_recovery_retry(self, onion: str) -> None:
        """Marks one delayed retunnel recovery retry worker as finished."""
        with self._lock:
            self._retunnel_recovery_retry_pending.discard(onion)

    def mark_retunnel_reconnect(self, onion: str) -> None:
        """Marks that the next successful connection should finalize a retunnel flow."""
        with self._lock:
            self._retunnel_reconnects.add(onion)

    def mark_retunnel_started(self, onion: str) -> None:
        """Marks a peer as currently executing a retunnel flow."""
        with self._lock:
            self._retunnel_in_progress.add(onion)
            self._retunnel_recovery_retry_counts[onion] = 0
            self._retunnel_recovery_retry_pending.discard(onion)

    def is_retunneling(self, onion: str) -> bool:
        """Checks whether a peer is currently inside a retunnel flow."""
        with self._lock:
            return onion in self._retunnel_in_progress

    def consume_retunnel_reconnect(self, onion: str) -> bool:
        """Consumes a pending retunnel completion marker."""
        with self._lock:
            if onion not in self._retunnel_reconnects:
                return False
            self._retunnel_reconnects.discard(onion)
            return True

    def discard_retunnel_reconnect(self, onion: str) -> None:
        """Clears a pending retunnel completion marker."""
        with self._lock:
            self._retunnel_reconnects.discard(onion)

    def clear_retunnel_flow(self, onion: str) -> None:
        """Clears all retunnel markers for one peer."""
        with self._lock:
            self._retunnel_reconnects.discard(onion)
            self._retunnel_in_progress.discard(onion)
            self._retunnel_recovery_retry_counts.pop(onion, None)
            self._retunnel_recovery_retry_pending.discard(onion)
