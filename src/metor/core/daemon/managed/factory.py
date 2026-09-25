"""Public helpers for constructing one managed daemon runtime."""

import atexit
from typing import Callable, Dict, Optional, Union

from metor.core.api import EventType, JsonValue
from metor.core.tor import TorManager
from metor.data import SqlManager, SettingKey
from metor.data.profile import ProfileManager

# Local Package Imports
from metor.core.daemon import InvalidMasterPasswordError
from metor.core.daemon.managed.bootstrap import (
    CorruptedStorageError,
    RuntimeBuildCleanupError,
    build_runtime,
    release_uninstalled_runtime,
)
from metor.core.daemon.managed.engine import (
    Daemon,
    RuntimeStartFailure,
    RuntimeStartupError,
    safe_start_category,
)
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
    'PlaintextLockedDaemonError',
    'RuntimeStatusCallback',
    'create_managed_daemon',
]


class InvalidDaemonPasswordError(Exception):
    """Raised when daemon startup received an invalid required auth password."""


class CorruptedDaemonStorageError(Exception):
    """Raised when daemon startup hits corrupted encrypted storage."""


class PlaintextLockedDaemonError(Exception):
    """Raised when a plaintext profile is asked to start in unsupported locked mode."""


def create_managed_daemon(
    pm: ProfileManager,
    password: Optional[str] = None,
    session_auth_password: Optional[str] = None,
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
        Daemon: The configured daemon instance.
    """
    pm.initialize()

    if start_locked and pm.uses_plaintext_storage():
        raise PlaintextLockedDaemonError()

    if sql_log_callback is not None:
        SqlManager.set_log_callback(sql_log_callback)
    if tor_log_callback is not None:
        TorManager.set_log_callback(tor_log_callback)

    require_local_auth: bool = pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH)

    if start_locked:
        return Daemon(
            pm,
            status_callback=status_callback,
            require_session_auth=require_local_auth,
            start_locked=True,
        )

    try:
        runtime = build_runtime(
            pm,
            password,
            enable_session_auth=require_local_auth,
            session_auth_password=session_auth_password,
        )
    except InvalidMasterPasswordError as exc:
        raise InvalidDaemonPasswordError() from exc
    except CorruptedStorageError as exc:
        raise CorruptedDaemonStorageError() from exc
    except RuntimeBuildCleanupError as exc:
        if not exc.retry_cleanup():
            atexit.register(exc.retry_cleanup)
        raise RuntimeStartupError(
            RuntimeStartFailure('runtime_build', 'RuntimeError')
        ) from exc
    except Exception as exc:
        raise RuntimeStartupError(
            RuntimeStartFailure('runtime_build', safe_start_category(exc))
        ) from exc

    try:
        return Daemon(
            pm,
            runtime.km,
            runtime.tm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            runtime.blob_store,
            session_auth=runtime.session_auth,
            require_session_auth=require_local_auth,
            status_callback=status_callback,
        )
    except Exception as exc:
        try:
            release_uninstalled_runtime(pm, runtime)
        except RuntimeBuildCleanupError as cleanup_error:
            if not cleanup_error.retry_cleanup():
                atexit.register(cleanup_error.retry_cleanup)
        if isinstance(exc, RuntimeStartupError):
            raise
        raise RuntimeStartupError(
            RuntimeStartFailure('daemon_construct', safe_start_category(exc))
        ) from exc
