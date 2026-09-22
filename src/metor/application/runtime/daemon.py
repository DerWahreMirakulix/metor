"""Application-layer helpers for managed local daemon startup and logging."""

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional, TextIO

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
MAX_STARTUP_SECRET_BYTES = 4096


class DaemonProfileMissingError(ValueError):
    """Raised when daemon startup targets a profile that does not exist."""


class RemoteDaemonProfileError(ValueError):
    """Raised when local daemon startup targets a remote-only profile."""


@dataclass(frozen=True)
class DaemonStartPreparation:
    """Validated facts required by interactive and detached startup adapters."""

    already_running: bool
    encrypted: bool
    session_auth_required: bool


__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonProfileMissingError',
    'DaemonStartPreparation',
    'DaemonStatus',
    'InvalidDaemonPasswordError',
    'PlaintextLockedDaemonError',
    'RemoteDaemonProfileError',
    'RuntimeStatusCallback',
    'configure_daemon_runtime_logging',
    'read_startup_secret',
    'prepare_managed_daemon_start',
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
        'metor',
        '-p',
        pm.profile_name,
        'daemon',
        '--non-interactive',
    ]
    if start_locked:
        command.append('--locked')
    if startup_session_auth_stdin:
        command.append('--startup-session-auth-stdin')
    return command


def read_startup_secret(stream: TextIO) -> Optional[str]:
    """Reads one bounded startup secret from the existing stdin pipe.

    Args:
        stream (TextIO): Existing child standard-input pipe.

    Returns:
        Optional[str]: One bounded secret, or None at clean end-of-file.
    """
    line: str = stream.readline(MAX_STARTUP_SECRET_BYTES + 2)
    if line == '':
        return None
    secret: str = line.rstrip('\r\n')
    if len(secret.encode('utf-8')) > MAX_STARTUP_SECRET_BYTES:
        raise ValueError('Startup session-auth secret is too long.')
    if not secret:
        return None
    return secret


def prepare_managed_daemon_start(
    pm: ProfileManager,
    *,
    start_locked: bool,
) -> DaemonStartPreparation:
    """Validates one daemon start and returns its credential requirements.

    Args:
        pm (ProfileManager): Exact local profile selected for startup.
        start_locked (bool): Whether startup must defer credential submission.

    Returns:
        DaemonStartPreparation: Validated launch and credential requirements.
    """
    if not pm.exists():
        raise DaemonProfileMissingError(f"Profile '{pm.profile_name}' does not exist.")
    Settings.validate_integrity()
    pm.validate_integrity()
    if pm.is_remote():
        raise RemoteDaemonProfileError('Cannot start a daemon on a remote profile!')

    already_running: bool = pm.is_daemon_running()
    plaintext: bool = pm.uses_plaintext_storage()
    if start_locked and plaintext:
        raise PlaintextLockedDaemonError()
    return DaemonStartPreparation(
        already_running=already_running,
        encrypted=pm.uses_encrypted_storage(),
        session_auth_required=(
            not start_locked
            and plaintext
            and pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH)
        ),
    )


def _stop_failed_daemon_process(process: subprocess.Popen[bytes]) -> None:
    """Best-effort bounded cleanup for a child whose startup did not complete.

    Args:
        process (subprocess.Popen[bytes]): Child whose startup failed.

    Returns:
        None
    """
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        except (OSError, subprocess.SubprocessError):
            return
    except (OSError, subprocess.SubprocessError):
        return


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
    preparation: DaemonStartPreparation = prepare_managed_daemon_start(
        pm,
        start_locked=start_locked,
    )
    if preparation.already_running:
        return True
    if preparation.session_auth_required and session_auth_password is None:
        return False

    secret_payload: Optional[bytes] = None
    if session_auth_password is not None:
        if '\n' in session_auth_password or '\r' in session_auth_password:
            raise ValueError('Startup session-auth secret must be one line.')
        encoded_secret: bytes = session_auth_password.encode('utf-8')
        if len(encoded_secret) > MAX_STARTUP_SECRET_BYTES:
            raise ValueError('Startup session-auth secret is too long.')
        secret_payload = encoded_secret + b'\n'

    command: list[str] = _build_daemon_launch_command(
        pm,
        start_locked=start_locked,
        startup_session_auth_stdin=secret_payload is not None,
    )
    stdin_target: int = (
        subprocess.PIPE if secret_payload is not None else subprocess.DEVNULL
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

    if secret_payload is not None:
        if process.stdin is None:
            _stop_failed_daemon_process(process)
            return False
        secret_write_failed: bool = False
        try:
            written = process.stdin.write(secret_payload)
            if written is None or written != len(secret_payload):
                raise OSError('Incomplete startup secret write.')
            process.stdin.flush()
        except OSError:
            secret_write_failed = True
        except BaseException:
            _stop_failed_daemon_process(process)
            raise
        finally:
            try:
                process.stdin.close()
            except OSError:
                secret_write_failed = True
        if secret_write_failed:
            _stop_failed_daemon_process(process)
            return False

    try:
        deadline: float = time.monotonic() + _build_daemon_start_timeout(pm)
        while time.monotonic() < deadline:
            daemon_port: Optional[int] = pm.get_daemon_port()
            if daemon_port is not None:
                return True

            if process.poll() is not None:
                return False

            time.sleep(Constants.LOCK_SLEEP_SEC)

        ready: bool = pm.get_daemon_port() is not None
    except BaseException:
        _stop_failed_daemon_process(process)
        raise
    if not ready:
        _stop_failed_daemon_process(process)
    return ready


def run_managed_daemon(
    pm: ProfileManager,
    password: Optional[str] = None,
    session_auth_password: Optional[str] = None,
    start_locked: bool = False,
    status_callback: Optional[RuntimeStatusCallback] = None,
    sql_log_callback: Optional[RuntimeLogCallback] = None,
    tor_log_callback: Optional[RuntimeLogCallback] = None,
    preparation: Optional[DaemonStartPreparation] = None,
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
    prepared: DaemonStartPreparation = preparation or prepare_managed_daemon_start(
        pm,
        start_locked=start_locked,
    )
    if prepared.already_running:
        return
    if prepared.encrypted and not start_locked and password is None:
        raise InvalidDaemonPasswordError()
    if prepared.session_auth_required and session_auth_password is None:
        raise ValueError('Session-auth password is required for daemon startup.')

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
