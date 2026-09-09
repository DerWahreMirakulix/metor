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
) -> None:
    """Destroys PMK access before best-effort encrypted-file cleanup.

    Args:
        pm (ProfileManager): Profile whose storage must be destroyed.
        prepare_runtime (Optional[Callable]): Session/network shutdown hook.
        clear_runtime_keys (Optional[Callable]): Runtime key-release hook.
        protector (Optional[KeyProtector]): Injected PMK protector.
        cleanup (Callable[[Path], None]): Defense-in-depth filesystem cleanup.

    Returns:
        None
    """
    if prepare_runtime is not None:
        prepare_runtime()
    SqlManager.close_connection(pm.paths.get_db_file())
    active_protector = protector or PasswordKeyProtector(pm.paths.get_keyslot_file())
    try:
        if clear_runtime_keys is not None:
            clear_runtime_keys()
    finally:
        active_protector.destroy()
    cleanup(pm.paths.get_config_dir())
