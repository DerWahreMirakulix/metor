"""Transport, focus, and derived transport snapshot state mixins."""

import threading
import time
from typing import TYPE_CHECKING, Dict, Optional

from metor.core.daemon.models import (
    DropTunnelState,
    LiveTransportState,
    PeerTransportState,
    PrimaryTransport,
)


class StateTrackerTransportMixin:
    """Encapsulates focus counters, drop tunnels, and transport snapshots."""

    _lock: threading.Lock
    _drop_tunnels: Dict[str, DropTunnelState]
    _ui_focus_counts: Dict[str, int]

    if TYPE_CHECKING:

        def get_live_state(self, onion: str) -> LiveTransportState: ...

        def is_retunneling(self, onion: str) -> bool: ...

    def add_ui_focus(self, onion: str) -> None:
        """Increments the reference count of UI clients focusing on a peer."""
        with self._lock:
            self._ui_focus_counts[onion] = self._ui_focus_counts.get(onion, 0) + 1

    def get_focus_count(self, onion: str) -> int:
        """Returns the current number of UI clients focusing one peer."""
        with self._lock:
            return self._ui_focus_counts.get(onion, 0)

    def remove_ui_focus(self, onion: str) -> None:
        """Decrements the reference count of UI clients focusing on a peer."""
        with self._lock:
            if onion in self._ui_focus_counts:
                self._ui_focus_counts[onion] -= 1
                if self._ui_focus_counts[onion] <= 0:
                    del self._ui_focus_counts[onion]

    def is_focused_by_ui(self, onion: str) -> bool:
        """Checks if any connected UI client currently focuses the peer."""
        with self._lock:
            return self._ui_focus_counts.get(onion, 0) > 0

    def mark_drop_tunnel_open(
        self, onion: str, opened_at: Optional[float] = None
    ) -> None:
        """Marks a cached drop tunnel as active for one peer."""
        timestamp: float = opened_at if opened_at is not None else time.time()
        with self._lock:
            self._drop_tunnels[onion] = DropTunnelState(
                opened_at=timestamp,
                last_used_at=timestamp,
            )

    def touch_drop_tunnel(self, onion: str, touched_at: Optional[float] = None) -> None:
        """Updates the last-used timestamp for a cached drop tunnel."""
        timestamp: float = touched_at if touched_at is not None else time.time()
        with self._lock:
            tunnel: Optional[DropTunnelState] = self._drop_tunnels.get(onion)
            if not tunnel:
                self._drop_tunnels[onion] = DropTunnelState(
                    opened_at=timestamp,
                    last_used_at=timestamp,
                )
                return

            self._drop_tunnels[onion] = DropTunnelState(
                opened_at=tunnel.opened_at,
                last_used_at=timestamp,
            )

    def clear_drop_tunnel(self, onion: str) -> None:
        """Removes cached drop tunnel metadata for one peer."""
        with self._lock:
            self._drop_tunnels.pop(onion, None)

    def has_drop_tunnel(self, onion: str) -> bool:
        """Checks whether a cached drop tunnel exists for one peer."""
        with self._lock:
            return onion in self._drop_tunnels

    def get_drop_tunnel_state(self, onion: str) -> Optional[DropTunnelState]:
        """Returns the cached drop tunnel metadata for one peer."""
        with self._lock:
            return self._drop_tunnels.get(onion)

    def get_primary_transport(
        self, onion: str, standby_drop_allowed: bool = False
    ) -> PrimaryTransport:
        """Derives the primary transport for one peer."""
        live_state: LiveTransportState = self.get_live_state(onion)
        if live_state is not LiveTransportState.DISCONNECTED:
            return PrimaryTransport.LIVE

        if self.has_drop_tunnel(onion):
            return PrimaryTransport.DROP

        return PrimaryTransport.NONE

    def get_peer_transport_state(
        self, onion: str, standby_drop_allowed: bool = False
    ) -> PeerTransportState:
        """Returns a derived peer transport snapshot."""
        return PeerTransportState(
            onion=onion,
            live_state=self.get_live_state(onion),
            primary_transport=self.get_primary_transport(
                onion,
                standby_drop_allowed=standby_drop_allowed,
            ),
            has_drop_tunnel=self.has_drop_tunnel(onion),
            focus_count=self.get_focus_count(onion),
            standby_drop_allowed=standby_drop_allowed,
            is_retunneling=self.is_retunneling(onion),
        )
