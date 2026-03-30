"""
Module encapsulating the Tor peer authentication protocol tie-breaker algorithms.
"""

from typing import Optional, Tuple


class HandshakeProtocol:
    """Handles deterministic tie-breaking for mutual peer connections."""

    @staticmethod
    def evaluate_tie_breaker(
        local_onion: Optional[str], remote_onion: str, is_outbound_attempt: bool
    ) -> Tuple[bool, bool]:
        """
        Determines how to handle mutual simultaneous connection attempts deterministically.

        Args:
            local_onion (Optional[str]): Our own local onion address.
            remote_onion (str): The remote peer's onion address.
            is_outbound_attempt (bool): Whether we simultaneously initiated an outbound connection.

        Returns:
            Tuple[bool, bool]: A tuple containing (should_reject, is_mutual_winner).
        """
        should_reject: bool = False
        is_mutual_winner: bool = False

        if is_outbound_attempt:
            if local_onion and local_onion < remote_onion:
                should_reject = True
            else:
                is_mutual_winner = True

        return should_reject, is_mutual_winner
