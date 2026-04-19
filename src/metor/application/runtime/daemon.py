"""Application-layer helpers for managed local daemon startup and logging."""

from typing import Callable, Optional

from metor.core.daemon.managed import (
    CorruptedDaemonStorageError,
    DaemonStatus,
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    RuntimeStatusCallback,
    create_managed_daemon,
)
from metor.data import Settings
from metor.data.profile import ProfileManager


RuntimeLogCallback = Callable[[str], None]
_default_sql_log_callback: Optional[RuntimeLogCallback] = None
_default_tor_log_callback: Optional[RuntimeLogCallback] = None

__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonStatus',
    'InvalidDaemonPasswordError',
    'PlaintextLockedDaemonError',
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
    session_auth_password: Optional[str] = None,
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
        session_auth_password (Optional[str]): Optional plaintext-profile session-auth password.
        start_locked (bool): Whether to start only the IPC surface until unlock.
        status_callback (Optional[RuntimeStatusCallback]): Optional status callback.
        sql_log_callback (Optional[RuntimeLogCallback]): Optional SQL diagnostics callback.
        tor_log_callback (Optional[RuntimeLogCallback]): Optional Tor diagnostics callback.

    Raises:
        InvalidDaemonPasswordError: If the supplied password cannot unlock storage.
        CorruptedDaemonStorageError: If encrypted storage is corrupted.
        PlaintextLockedDaemonError: If locked mode is requested for a plaintext profile.

    Returns:
        None
    """
    Settings.validate_integrity()
    pm.validate_integrity()

    daemon = create_managed_daemon(
        pm,
        password=password,
        session_auth_password=session_auth_password,
        start_locked=start_locked,
        status_callback=status_callback,
        sql_log_callback=sql_log_callback or _default_sql_log_callback,
        tor_log_callback=tor_log_callback or _default_tor_log_callback,
    )
    daemon.run()
