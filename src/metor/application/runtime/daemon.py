"""Application-layer helpers for managed local daemon startup and logging."""

from typing import Callable, Optional

from metor.core.daemon.managed import (
    CorruptedDaemonStorageError,
    DaemonStatus,
    InvalidDaemonPasswordError,
    RuntimeStatusCallback,
    create_managed_daemon,
)
from metor.data.profile import ProfileManager


RuntimeLogCallback = Callable[[str], None]
_default_sql_log_callback: Optional[RuntimeLogCallback] = None
_default_tor_log_callback: Optional[RuntimeLogCallback] = None

__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonStatus',
    'InvalidDaemonPasswordError',
    'RuntimeStatusCallback',
    'configure_daemon_runtime_logging',
    'run_managed_daemon',
]


def configure_daemon_runtime_logging(
    sql_log_callback: RuntimeLogCallback,
    tor_log_callback: RuntimeLogCallback,
) -> None:
    """
    Installs SQL and Tor runtime log callbacks for managed daemon startup.

    Args:
        sql_log_callback (RuntimeLogCallback): Callback for SQL diagnostics.
        tor_log_callback (RuntimeLogCallback): Callback for Tor diagnostics.

    Returns:
        None
    """
    global _default_sql_log_callback, _default_tor_log_callback
    _default_sql_log_callback = sql_log_callback
    _default_tor_log_callback = tor_log_callback


def run_managed_daemon(
    pm: ProfileManager,
    password: Optional[str] = None,
    start_locked: bool = False,
    status_callback: Optional[RuntimeStatusCallback] = None,
    sql_log_callback: Optional[RuntimeLogCallback] = None,
    tor_log_callback: Optional[RuntimeLogCallback] = None,
) -> None:
    """
    Builds and runs one managed daemon instance for the active profile.

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
        None
    """
    daemon = create_managed_daemon(
        pm,
        password=password,
        start_locked=start_locked,
        status_callback=status_callback,
        sql_log_callback=sql_log_callback or _default_sql_log_callback,
        tor_log_callback=tor_log_callback or _default_tor_log_callback,
    )
    daemon.run()
