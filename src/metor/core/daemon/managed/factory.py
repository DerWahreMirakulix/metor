"""Public helpers for constructing one managed daemon runtime."""

from typing import Callable, Dict, Optional, Union

from metor.core import TorManager
from metor.core.api import EventType, JsonValue
from metor.data import SqlManager
from metor.data.profile import ProfileManager

# Local Package Imports
from metor.core.daemon import InvalidMasterPasswordError
from metor.core.daemon.managed.bootstrap import (
    CorruptedStorageError,
    build_runtime,
)
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.status import DaemonStatus


RuntimeStatusCallback = Callable[
    [Union[EventType, DaemonStatus], Dict[str, JsonValue]],
    None,
]
RuntimeLogCallback = Callable[[str], None]

__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonStatus',
    'InvalidDaemonPasswordError',
    'RuntimeStatusCallback',
    'create_managed_daemon',
]


class InvalidDaemonPasswordError(Exception):
    """Raised when daemon startup received an invalid master password."""


class CorruptedDaemonStorageError(Exception):
    """Raised when daemon startup hits corrupted encrypted storage."""


def create_managed_daemon(
    pm: ProfileManager,
    password: Optional[str] = None,
    start_locked: bool = False,
    status_callback: Optional[RuntimeStatusCallback] = None,
    sql_log_callback: Optional[RuntimeLogCallback] = None,
    tor_log_callback: Optional[RuntimeLogCallback] = None,
) -> Daemon:
    """
    Creates one configured daemon instance for the active profile.

    Args:
        pm (ProfileManager): The active profile manager.
        password (Optional[str]): The master password for unlocked startup.
        start_locked (bool): Whether to start only the IPC surface until unlock.
        status_callback (Optional[RuntimeStatusCallback]): Optional status callback.
        sql_log_callback (Optional[RuntimeLogCallback]): Optional SQL diagnostics callback.
        tor_log_callback (Optional[RuntimeLogCallback]): Optional Tor diagnostics callback.

    Raises:
        InvalidDaemonPasswordError: If the supplied password cannot unlock storage.
        CorruptedDaemonStorageError: If encrypted storage is corrupted.

    Returns:
        Daemon: The configured daemon instance.
    """
    pm.initialize()

    if sql_log_callback is not None:
        SqlManager.set_log_callback(sql_log_callback)
    if tor_log_callback is not None:
        TorManager.set_log_callback(tor_log_callback)

    if start_locked:
        return Daemon(
            pm,
            status_callback=status_callback,
            start_locked=True,
        )

    try:
        runtime = build_runtime(pm, password)
    except InvalidMasterPasswordError as exc:
        raise InvalidDaemonPasswordError() from exc
    except CorruptedStorageError as exc:
        raise CorruptedDaemonStorageError() from exc

    return Daemon(
        pm,
        runtime.km,
        runtime.tm,
        runtime.cm,
        runtime.hm,
        runtime.mm,
        session_auth=runtime.session_auth,
        status_callback=status_callback,
    )
