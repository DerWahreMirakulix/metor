"""Live-session activity timeout and transient read-receipt maintenance."""

import socket
import time
from typing import TYPE_CHECKING, List, Optional

from metor.core.daemon.managed.models import SessionState, TorCommand
from metor.data import MessageManager, SettingKey

# Local Package Imports
from ..network import NetworkManager, StateTracker

if TYPE_CHECKING:
    from metor.data.profile import Config


class SessionMaintenance:
    """Owns periodic activity policy for one installed network runtime."""

    def __init__(
        self,
        network: NetworkManager,
        state: StateTracker,
        mm: MessageManager,
        config: 'Config',
    ) -> None:
        """Initializes maintenance with active runtime dependencies.

        Args:
            network (NetworkManager): Network lifecycle facade.
            state (StateTracker): Shared session activity state.
            mm (MessageManager): Durable pending-live message store.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._network: NetworkManager = network
        self._state: StateTracker = state
        self._mm: MessageManager = mm
        self._config: 'Config' = config

    def send_read_receipts(self, onion: str, msg_ids: List[str]) -> None:
        """Sends transient best-effort read receipts over an active session.

        Args:
            onion (str): The peer onion identity.
            msg_ids (List[str]): The locally consumed message identifiers.

        Returns:
            None
        """
        if not self._state.is_live_active(onion):
            return
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        if conn is None:
            return
        try:
            for msg_id in msg_ids:
                conn.sendall(f'{TorCommand.READ.value} {msg_id}\n'.encode('utf-8'))
        except Exception:
            pass

    def check_idle_timeouts(self) -> None:
        """Closes stable, unfocused sessions that exceeded their idle budget.

        Args:
            None

        Returns:
            None
        """
        idle_timeout: float = self._config.get_float(SettingKey.LIVE_IDLE_TIMEOUT)
        if idle_timeout <= 0:
            return

        now: float = time.time()
        for onion in self._state.get_active_connections_keys():
            if self._state.get_live_state(onion) is not SessionState.CONNECTED:
                continue
            if self._state.get_focus_count(onion) > 0:
                continue
            if self._state.is_retunneling(onion):
                continue
            if self._state.has_live_reconnect_grace(onion):
                continue
            if self._state.has_scheduled_auto_reconnect(onion):
                continue
            if self._state.has_outbound_attempt(onion):
                continue
            if self._state.has_unacked_messages(onion):
                continue
            if self._mm.get_pending_live_outbox(onion):
                continue
            last_activity: Optional[float] = self._state.get_session_last_activity(
                onion
            )
            if last_activity is None or now - last_activity <= idle_timeout:
                continue
            self._network.disconnect(onion, initiated_by_self=True)
