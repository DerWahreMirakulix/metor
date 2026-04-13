"""
Module encapsulating the Tor peer authentication protocol tie-breaker algorithms.
"""

from typing import Optional, Tuple

from metor.core.daemon.managed.models import TorCommand
from metor.utils import Constants


class HandshakeProtocol:
    """Handles deterministic tie-breaking for mutual peer connections."""

    @staticmethod
    def parse_challenge_line(line: str) -> str:
        """
        Validates one peer-auth challenge frame and returns its nonce.

        Args:
            line (str): The raw line received from the peer.

        Raises:
            ValueError: If the frame is malformed or the nonce is invalid.

        Returns:
            str: The validated hexadecimal challenge string.
        """
        parts: list[str] = line.strip().split()
        if len(parts) != 2 or parts[0] != TorCommand.CHALLENGE.value:
            raise ValueError('Invalid handshake challenge frame.')

        challenge_hex: str = parts[1]
        try:
            challenge: bytes = bytes.fromhex(challenge_hex)
        except ValueError as exc:
            raise ValueError('Invalid handshake challenge encoding.') from exc

        if len(challenge) != Constants.TOR_HANDSHAKE_CHALLENGE_BYTES:
            raise ValueError('Invalid handshake challenge length.')

        return challenge_hex

    @staticmethod
    def parse_auth_line(line: str) -> Tuple[str, str, bool]:
        """
        Validates one peer-auth frame and returns its onion, signature, and async flag.

        Args:
            line (str): The raw auth line received from the peer.

        Raises:
            ValueError: If the frame shape is malformed.

        Returns:
            Tuple[str, str, bool]: The remote onion, signature, and async-mode flag.
        """
        parts: list[str] = line.strip().split()
        if len(parts) not in (3, 4) or parts[0] != TorCommand.AUTH.value:
            raise ValueError('Invalid handshake auth frame.')

        is_async: bool = False
        if len(parts) == 4:
            if parts[3] != 'ASYNC':
                raise ValueError('Invalid handshake auth frame.')
            is_async = True

        return parts[1], parts[2], is_async

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
