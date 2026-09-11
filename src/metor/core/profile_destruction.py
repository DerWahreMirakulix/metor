"""Central key-first profile destruction lifecycle."""

from pathlib import Path
from typing import Callable, Optional

from metor.core.profile_keys import KeyProtector, PasswordKeyProtector
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import secure_remove_path


def destroy_profile_storage(
    pm: ProfileManager,
    *,
    prepare_runtime: Optional[Callable[[], object]] = None,
    clear_runtime_keys: Optional[Callable[[], None]] = None,
    protector: Optional[KeyProtector] = None,
    cleanup: Callable[[Path], None] = secure_remove_path,
    key_destroyed_callback: Optional[Callable[[], None]] = None,
    failure_callback: Optional[Callable[[str, bool], None]] = None,
) -> None:
    """Destroys PMK access before best-effort encrypted-file cleanup.

    Args:
        pm (ProfileManager): Profile whose storage must be destroyed.
        prepare_runtime (Optional[Callable]): Session/network shutdown hook.
        clear_runtime_keys (Optional[Callable]): Runtime key-release hook.
        protector (Optional[KeyProtector]): Injected PMK protector.
        cleanup (Callable[[Path], None]): Defense-in-depth filesystem cleanup.
        key_destroyed_callback (Optional[Callable]): Irreversible-milestone hook.
        failure_callback (Optional[Callable]): Failure phase and key-state hook.

    Returns:
        None
    """
    preparation_error: Optional[Exception] = None
    if prepare_runtime is not None:
        try:
            prepare_runtime()
        except Exception as exc:
            preparation_error = exc
    SqlManager.close_connection(pm.paths.get_db_file())
    active_protector = protector or PasswordKeyProtector(pm.paths.get_keyslot_file())
    try:
        try:
            if clear_runtime_keys is not None:
                clear_runtime_keys()
        finally:
            active_protector.destroy()
    except Exception:
        if failure_callback is not None:
            failure_callback('key_destruction', False)
        raise
    if key_destroyed_callback is not None:
        key_destroyed_callback()
    cleanup_error: Optional[Exception] = None
    try:
        cleanup(pm.paths.get_config_dir())
    except Exception as exc:
        cleanup_error = exc
    if preparation_error is not None:
        if failure_callback is not None:
            failure_callback('preparation', True)
        raise preparation_error
    if cleanup_error is not None:
        if failure_callback is not None:
            failure_callback('cleanup', True)
        raise cleanup_error
