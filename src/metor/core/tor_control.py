"""Private, deadline-bound Tor control session for one profile-owned onion service."""

import base64
import hmac
import re
import secrets
import select
import socket
import time
from pathlib import Path

from metor.shared.network import decode_tor_v3_onion_public_key, recv_before
from metor.utils import Constants


class OnionServiceControl:
    """Authenticate Tor before sending the expanded Ed25519 key, with no wire logging."""

    def __init__(self, control_port: int) -> None:
        self._socket = socket.create_connection(
            (Constants.LOCALHOST, control_port), Constants.TOR_CONTROL_TIMEOUT_SEC
        )

    def is_alive(self) -> bool:
        """An idle, unsubscribed control socket has no pending data or EOF."""
        try:
            readable, _, errors = select.select([self._socket], [], [self._socket], 0)
        except (OSError, ValueError):
            return False
        return not readable and not errors

    def close(self) -> None:
        """Closing the owning controller also unregisters its ephemeral service."""
        self._socket.close()

    def _exchange(self, command: bytes, lines: int) -> list[bytes]:
        deadline = time.monotonic() + Constants.TOR_CONTROL_TIMEOUT_SEC
        self._socket.sendall(command + b'\r\n')
        result = bytearray()
        while len(result) < Constants.TOR_CONTROL_REPLY_MAX_BYTES:
            received = recv_before(
                self._socket,
                Constants.TOR_CONTROL_REPLY_MAX_BYTES - len(result),
                deadline,
            )
            if not received:
                break
            result.extend(received)
            if result.endswith(b'\r\n'):
                reply = bytes(result[:-2]).split(b'\r\n')
                if len(reply) == lines and reply[-1].startswith(b'250 '):
                    return reply
                if not reply[-1].startswith(b'250-') or len(reply) >= lines:
                    break
        raise OSError('Unexpected Tor control reply.')

    def authenticate(self, cookie_path: Path) -> None:
        with cookie_path.open('rb') as cookie_file:
            cookie = cookie_file.read(33)
        if len(cookie) != 32:
            raise OSError('Invalid Tor control cookie.')
        nonce = secrets.token_bytes(32)
        (reply,) = self._exchange(
            b'AUTHCHALLENGE SAFECOOKIE ' + nonce.hex().encode(), 1
        )
        match = re.fullmatch(
            rb'250 AUTHCHALLENGE SERVERHASH=([a-fA-F0-9]{64}) SERVERNONCE=([a-fA-F0-9]{64})',
            reply,
        )
        if match is None:
            raise OSError('Invalid Tor control challenge.')
        transcript = cookie + nonce + bytes.fromhex(match[2].decode('ascii'))
        expected = hmac.digest(
            b'Tor safe cookie authentication server-to-controller hash',
            transcript,
            'sha256',
        )
        if not hmac.compare_digest(expected, bytes.fromhex(match[1].decode('ascii'))):
            raise OSError('Tor control identity mismatch.')
        proof = hmac.digest(
            b'Tor safe cookie authentication controller-to-server hash',
            transcript,
            'sha256',
        )
        if self._exchange(b'AUTHENTICATE ' + proof.hex().encode(), 1) != [b'250 OK']:
            raise OSError('Tor control authentication failed.')

    def register(self, raw_secret: bytes, expected_public: bytes, port: int) -> str:
        prefix = b'== ed25519v1-secret: type0 ==\0\0\0'
        if not raw_secret.startswith(prefix) or len(raw_secret) != len(prefix) + 64:
            raise ValueError('Invalid Tor identity.')
        key = base64.b64encode(raw_secret[len(prefix) :])
        reply, ok = self._exchange(
            b'ADD_ONION ED25519-V3:'
            + key
            + f' Flags=DiscardPK Port=80,{Constants.LOCALHOST}:{port}'.encode(),
            2,
        )
        if ok != b'250 OK' or not reply.startswith(b'250-ServiceID='):
            raise OSError('Tor did not register the service.')
        onion = reply.removeprefix(b'250-ServiceID=').decode('ascii')
        if not hmac.compare_digest(
            decode_tor_v3_onion_public_key(onion), expected_public
        ):
            raise OSError('Tor service identity mismatch.')
        return onion

    def rotate(self) -> None:
        if self._exchange(b'SIGNAL NEWNYM', 1) != [b'250 OK']:
            raise OSError('Tor circuit rotation failed.')
