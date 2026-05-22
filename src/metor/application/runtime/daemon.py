"""Application-layer helpers for managed local daemon startup and logging."""

import os
import subprocess
import sys
import time
from typing import Callable, Optional

from metor.core.daemon.managed import (
    CorruptedDaemonStorageError,
    DaemonStatus,
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    RuntimeStatusCallback,
    create_managed_daemon,
)
from metor.data import SettingKey, Settings
from metor.data.profile import ProfileManager
from metor.utils import Constants


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
    'start_managed_daemon_process',
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


def _build_daemon_launch_command(
    pm: ProfileManager,
    *,
    start_locked: bool,
    startup_session_auth_stdin: bool,
) -> list[str]:
    """
    Builds the detached CLI command used to launch one managed daemon process.

    Args:
        pm (ProfileManager): The active profile manager.
        start_locked (bool): Whether the daemon should expose IPC only until unlock.
        startup_session_auth_stdin (bool): Whether the child should read one startup-only session-auth password from stdin.

    Returns:
        list[str]: The detached child-process argv.
    """
    command: list[str] = [
        sys.executable,
        '-m',
        'metor.main',
        '-p',
        pm.profile_name,
    ]
    if start_locked:
        command.append('--locked')
    if startup_session_auth_stdin:
        command.append('--startup-session-auth-stdin')
    command.append('daemon')
    return command


def _build_daemon_start_timeout(pm: ProfileManager) -> float:
    """
    Resolves the local wait window for daemon IPC readiness after background spawn.

    Args:
        pm (ProfileManager): The active profile manager.

    Returns:
        float: The readiness timeout in seconds.
    """
    ipc_timeout: float = pm.config.get_float(SettingKey.IPC_TIMEOUT)
    tor_timeout: float = pm.config.get_float(SettingKey.TOR_TIMEOUT)
    return max(ipc_timeout, tor_timeout + Constants.LISTENER_READY_TIMEOUT)


def start_managed_daemon_process(
    pm: ProfileManager,
    *,
    start_locked: bool = False,
    session_auth_password: Optional[str] = None,
) -> bool:
    """
    Spawns one detached managed-daemon CLI process and waits for IPC readiness.

    Args:
        pm (ProfileManager): The active profile manager.
        start_locked (bool): Whether the daemon should start in locked IPC-only mode.
        session_auth_password (Optional[str]): Optional startup-only plaintext session-auth password delivered over stdin.

    Raises:
        PlaintextLockedDaemonError: If locked startup is requested for a plaintext profile.
        ValueError: If global or profile integrity validation fails.

    Returns:
        bool: True when the managed daemon published a reachable IPC port.
    """
    Settings.validate_integrity()
    pm.validate_integrity()

    if pm.is_remote():
        return False

    if start_locked and pm.uses_plaintext_storage():
        raise PlaintextLockedDaemonError()

    if pm.is_daemon_running():
        return True

    command: list[str] = _build_daemon_launch_command(
        pm,
        start_locked=start_locked,
        startup_session_auth_stdin=session_auth_password is not None,
    )
    stdin_target: int = (
        subprocess.PIPE if session_auth_password is not None else subprocess.DEVNULL
    )

    with open(os.devnull, 'wb') as sink:
        if os.name == 'nt':
            detached_flags: int = getattr(subprocess, 'DETACHED_PROCESS', 0)
            new_group_flags: int = getattr(
                subprocess,
                'CREATE_NEW_PROCESS_GROUP',
                0,
            )
            process: subprocess.Popen[bytes] = subprocess.Popen(
                command,
                stdin=stdin_target,
                stdout=sink,
                stderr=sink,
                creationflags=detached_flags | new_group_flags,
            )
        else:
            process = subprocess.Popen(
                command,
                stdin=stdin_target,
                stdout=sink,
                stderr=sink,
                start_new_session=True,
            )

    if session_auth_password is not None:
        if process.stdin is None:
            return False
        try:
            process.stdin.write(f'{session_auth_password}\n'.encode('utf-8'))
            process.stdin.flush()
        except OSError:
            return False
        finally:
            process.stdin.close()

    deadline: float = time.monotonic() + _build_daemon_start_timeout(pm)
    while time.monotonic() < deadline:
        daemon_port: Optional[int] = pm.get_daemon_port()
        if daemon_port is not None:
            return True

        if process.poll() is not None:
            return False

        time.sleep(Constants.LOCK_SLEEP_SEC)

    return pm.get_daemon_port() is not None


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
