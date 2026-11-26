"""Volatile accepted LIVE scopes independent of individual transport sockets."""

import socket
import threading
import time
from typing import Dict, Optional

from metor.core.api import ConnectionActor, ConnectionReasonCode


class StateTrackerContextMixin:
    """Owns logical conversation permission until an explicit lifecycle fence."""

    _lock: threading.RLock
    _connections: Dict[str, socket.socket]
    _accepted_live_contexts: Dict[str, int]
    _accepted_live_context_deadlines: Dict[str, float]
    _live_context_generations: Dict[str, int]
    _last_disconnect_reasons: Dict[str, ConnectionReasonCode]
    _last_disconnect_actors: Dict[str, ConnectionActor]
    _session_last_activity: Dict[str, float]

    def accepted_live_context_generation(self, onion: str) -> Optional[int]:
        """Returns accepted recovery authority without extending its lifetime.

        Args:
            onion: Canonical authenticated peer identity.
        Returns:
            Optional[int]: Accepted scope generation, absent before consent or after End.
        """
        with self._lock:
            deadline = self._accepted_live_context_deadlines.get(onion)
            if deadline is not None and deadline <= time.monotonic():
                return None
            return self._accepted_live_contexts.get(onion)

    def has_unrevoked_live_context(self, onion: str) -> bool:
        """Fences dismissal until accepted recovery's terminal cleanup is committed.

        An expired deadline grants no recovery permission. Its outstanding
        cleanup still owns retained state until the lifecycle worker revokes
        the exact scope under the operation and state locks.

        Args:
            onion: Canonical peer whose cleanup lifetime is inspected.
        Returns:
            bool: Whether an accepted scope still owns lifecycle cleanup.
        """
        with self._lock:
            return onion in self._accepted_live_contexts

    def begin_accepted_live_recovery(
        self, onion: str, timeout_sec: float
    ) -> Optional[float]:
        """Starts one configured recovery deadline without extending repeated failures.

        Args:
            onion: Canonical peer whose transport was lost.
            timeout_sec: Configured grace duration; zero expires immediately.
        Returns:
            Optional[float]: Original monotonic deadline, absent without accepted consent.
        """
        with self._lock:
            if onion not in self._accepted_live_contexts:
                return None
            deadline = self._accepted_live_context_deadlines.get(onion)
            if deadline is None:
                deadline = time.monotonic() + timeout_sec
                self._accepted_live_context_deadlines[onion] = deadline
            return deadline

    def accepted_live_recovery_deadline(self, onion: str) -> Optional[float]:
        """Returns the original loss deadline for bounded retry scheduling.

        Args:
            onion: Canonical peer whose recovery is inspected.
        Returns:
            Optional[float]: Monotonic deadline, absent for active or ended scopes.
        """
        with self._lock:
            return self._accepted_live_context_deadlines.get(onion)

    def expire_accepted_live_recovery(
        self, onion: str, generation: int, deadline: float
    ) -> bool:
        """Revokes only an unrecovered scope matching the timer's exact identity.

        Args:
            onion: Canonical original peer.
            generation: Original accepted logical generation.
            deadline: Original loss deadline; later losses have independent timers.
        Returns:
            bool: Whether this timer still owns terminal cleanup.
        """
        with self._lock:
            if (
                self._accepted_live_contexts.get(onion) != generation
                or self._accepted_live_context_deadlines.get(onion) != deadline
                or time.monotonic() < deadline
                or onion in self._connections
            ):
                return False
            self._accepted_live_contexts.pop(onion, None)
            self._accepted_live_context_deadlines.pop(onion, None)
            return True

    def revoke_accepted_live_context(self, onion: str) -> Optional[int]:
        """Revokes logical recovery permission while retaining projection identity.

        Callers serialize this with exact socket/attempt teardown through the
        state barrier. Transport loss alone never invokes this operation.

        Args:
            onion: Canonical peer whose accepted scope ends.
        Returns:
            Optional[int]: Previously accepted generation, if present.
        """
        with self._lock:
            self._accepted_live_context_deadlines.pop(onion, None)
            return self._accepted_live_contexts.pop(onion, None)

    def get_live_context_generation(self, onion: str) -> Optional[int]:
        """Returns logical conversation ownership only for an active transport.

        Args:
            onion: Canonical peer whose active permission is requested.
        Returns:
            Optional[int]: Active logical generation, if connected.
        """
        with self._lock:
            if onion not in self._connections:
                return None
            return self._live_context_generations.get(onion)

    def get_live_media_generation(self, onion: str) -> Optional[int]:
        """Qualifies accepted conversation ownership across transport loss.

        Args:
            onion: Canonical peer whose existing media context is requested.
        Returns:
            Optional[int]: Accepted generation, absent for ended or initial attempts.
        """
        return self.accepted_live_context_generation(onion)

    def known_live_context_generation(self, onion: str) -> Optional[int]:
        """Projects the last logical identity without granting recovery permission.

        Args:
            onion: Canonical peer whose presentation lifetime is projected.
        Returns:
            Optional[int]: Known accepted identity, including retained ended state.
        """
        with self._lock:
            return self._live_context_generations.get(onion)

    def forget_ended_live_context(self, onion: str) -> bool:
        """Removes ended presentation markers without revoking accepted permission."""
        with self._lock:
            if onion in self._accepted_live_contexts:
                return False
            self._live_context_generations.pop(onion, None)
            self._accepted_live_context_deadlines.pop(onion, None)
            self._last_disconnect_reasons.pop(onion, None)
            self._last_disconnect_actors.pop(onion, None)
            self._session_last_activity.pop(onion, None)
            return True
