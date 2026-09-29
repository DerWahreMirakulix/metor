"""Daemon-owned lifetime leases for locally launched long-lived frontends."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import os
from pathlib import Path
import secrets
import socket
import stat
import threading
import time

from metor.shared import Constants as SharedConstants
from metor.utils import Constants, FileLock, open_private_binary_file


LEASE_TOKEN_BYTES = SharedConstants.FRONTEND_LIFETIME_TOKEN_BYTES
FRONTEND_ID_BYTES = SharedConstants.FRONTEND_LIFETIME_ID_BYTES


def _valid_hex(value: str, byte_count: int) -> bool:
    """Validate one bounded opaque identity before it reaches lease state."""
    return (
        isinstance(value, str)
        and len(value) == 2 * byte_count
        and all(character in '0123456789abcdef' for character in value)
    )


def _read_frontend_lifetime_token_unlocked(profile_directory: Path) -> str | None:
    """Read a token while the caller holds the token-file lock."""
    path = profile_directory / Constants.FRONTEND_LIFETIME_FILE
    descriptor: int | None = None
    try:
        if os.name == 'nt':
            from metor.utils.security import _open_windows_file
            from metor.utils.windows_acl import validate_private_windows_dacl
            import msvcrt

            descriptor = _open_windows_file(path)
            if descriptor is None:
                return None
            validate_private_windows_dacl(
                getattr(msvcrt, 'get_osfhandle')(descriptor), directory=False
            )
        else:
            no_follow = getattr(os, 'O_NOFOLLOW', None)
            if no_follow is None:
                return None
            descriptor = os.open(path, os.O_RDONLY | no_follow)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            return None
        if os.name != 'nt':
            get_uid = getattr(os, 'getuid', None)
            if get_uid is None or (
                metadata.st_uid != get_uid() or metadata.st_mode & 0o077
            ):
                return None
        with os.fdopen(descriptor, 'rb') as handle:
            descriptor = None
            payload = handle.read(2 * LEASE_TOKEN_BYTES + 1)
        token = payload.decode('ascii')
        return token if _valid_hex(token, LEASE_TOKEN_BYTES) else None
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_frontend_lifetime_token(profile_directory: Path) -> str | None:
    """Read the exact daemon instance's owner-only bearer token for the local host.

    The Base host may deliver this token to an installed frontend. The SDK and
    frontend implementations never open profile runtime files themselves.
    """
    path = profile_directory / Constants.FRONTEND_LIFETIME_FILE
    with FileLock(path):
        return _read_frontend_lifetime_token_unlocked(profile_directory)


@dataclass
class _FrontendLease:
    """One opaque frontend instance and its current socket or reconnect deadline."""

    connection: socket.socket | None
    deadline: float | None = None


class FrontendLifetime:
    """Serialize join, release and final shutdown for one concrete daemon instance.

    A bearer token grants only lifetime participation. It never authenticates a
    profile session or unlocks protected content. Socket replacement is fenced
    by a random frontend ID and by the current daemon's token.
    """

    def __init__(self, profile_directory: Path, *, automatic: bool) -> None:
        """Create one independent or automatically managed daemon lifetime."""
        self._path = profile_directory / Constants.FRONTEND_LIFETIME_FILE
        self._automatic = automatic
        self._token = secrets.token_hex(LEASE_TOKEN_BYTES) if automatic else None
        self._lock = threading.Lock()
        self._leases: dict[str, _FrontendLease] = {}
        self._deadline = (
            time.monotonic() + Constants.FRONTEND_FIRST_REGISTRATION_GRACE_SEC
            if automatic
            else None
        )
        self._last_tick = time.monotonic()
        self._idle_suspend_extension_used = 0.0
        self._closing = False

    @property
    def automatic(self) -> bool:
        """Report this instance's immutable startup mode."""
        return self._automatic

    def publish(self) -> None:
        """Publish the instance token before IPC becomes reachable."""
        with FileLock(self._path):
            if self._token is None:
                self._path.unlink(missing_ok=True)
                return
            with open_private_binary_file(self._path) as handle:
                handle.write(self._token.encode('ascii'))

    def register(
        self, frontend_id: str, token: str | None, connection: socket.socket
    ) -> str:
        """Join or renew a frontend, replacing only its own prior socket."""
        if not self._automatic:
            return 'independent'
        if not _valid_hex(frontend_id, FRONTEND_ID_BYTES):
            return 'denied'
        if token is None or not _valid_hex(token, LEASE_TOKEN_BYTES):
            return 'denied'
        with self._lock:
            if self._closing:
                return 'stopping'
            if self._token is None or not hmac.compare_digest(token, self._token):
                return 'denied'
            if (
                frontend_id not in self._leases
                and len(self._leases) >= Constants.FRONTEND_MAX_LEASES
            ):
                return 'full'
            self._leases[frontend_id] = _FrontendLease(connection)
            self._deadline = None
            self._idle_suspend_extension_used = 0.0
            return 'joined'

    def ready(self) -> None:
        """Start the first-registration grace when IPC is actually available."""
        with self._lock:
            now = time.monotonic()
            self._last_tick = now
            if self._automatic and not self._leases and not self._closing:
                self._deadline = now + Constants.FRONTEND_FIRST_REGISTRATION_GRACE_SEC
                self._idle_suspend_extension_used = 0.0

    def release(
        self, frontend_id: str, token: str | None, connection: socket.socket
    ) -> str:
        """Release only an exact active frontend socket; duplicates are harmless."""
        with self._lock:
            if not self._automatic:
                return 'independent'
            if self._closing:
                return 'stopping'
            if (
                token is None
                or self._token is None
                or not hmac.compare_digest(token, self._token)
            ):
                return 'denied'
            current = self._leases.get(frontend_id)
            if current is not None and current.connection is connection:
                del self._leases[frontend_id]
                if not self._leases:
                    self._deadline = (
                        time.monotonic() + Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC
                    )
                    self._idle_suspend_extension_used = 0.0
            return 'released'

    def disconnect(self, connection: socket.socket) -> None:
        """Retain a crashed or disconnected client's slot briefly for reconnect."""
        with self._lock:
            now = time.monotonic()
            changed = False
            for lease in self._leases.values():
                if lease.connection is connection:
                    lease.connection = None
                    lease.deadline = now + Constants.FRONTEND_DISCONNECT_GRACE_SEC
                    changed = True
            if changed and not any(
                lease.connection is not None for lease in self._leases.values()
            ):
                self._idle_suspend_extension_used = 0.0

    def should_stop(self) -> bool:
        """Atomically fence new joins when the final bounded grace expires."""
        if not self._automatic:
            return False
        with self._lock:
            if self._closing:
                return True
            now = time.monotonic()
            gap = now - self._last_tick
            self._last_tick = now
            if gap > Constants.FRONTEND_SUSPEND_GAP_SEC:
                extension = min(
                    gap,
                    max(
                        0.0,
                        Constants.FRONTEND_MAX_SUSPEND_EXTENSION_SEC
                        - self._idle_suspend_extension_used,
                    ),
                )
                if self._deadline is not None:
                    self._deadline += extension
                for lease in self._leases.values():
                    if lease.deadline is not None:
                        lease.deadline += extension
                if self._deadline is not None or any(
                    lease.deadline is not None for lease in self._leases.values()
                ):
                    self._idle_suspend_extension_used += extension
            for frontend_id, lease in tuple(self._leases.items()):
                if lease.deadline is not None and lease.deadline <= now:
                    del self._leases[frontend_id]
            if not self._leases and self._deadline is None:
                self._deadline = now + Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC
            if (
                not self._leases
                and self._deadline is not None
                and now >= self._deadline
            ):
                self._closing = True
            return self._closing

    def begin_shutdown(self) -> None:
        """Prevent any new frontend from joining once release has begun."""
        with self._lock:
            self._closing = True

    def clear_published_token(self) -> None:
        """Remove only this daemon's token, preserving a replacement instance."""
        if self._token is None:
            return
        with FileLock(self._path):
            if _read_frontend_lifetime_token_unlocked(self._path.parent) == self._token:
                self._path.unlink(missing_ok=True)
