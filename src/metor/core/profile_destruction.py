"""Central key-first profile destruction lifecycle."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from metor.core.profile_keys import KeyProtector, PasswordKeyProtector
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import secure_remove_path


class DestructionPhase(str, Enum):
    """Externally reportable phases of key-first profile destruction."""

    PREPARATION = 'preparation'
    DATABASE_CLOSE = 'database_close'
    RUNTIME_KEY_RELEASE = 'runtime_key_release'
    KEY_DESTRUCTION = 'key_destruction'
    MILESTONE_NOTIFICATION = 'milestone_notification'
    CLEANUP = 'cleanup'


@dataclass(frozen=True)
class ProfileDestructionResult:
    """Completed phase state for a successful destructive transaction."""

    runtime_prepared: bool
    database_closed: bool
    runtime_keys_cleared: bool
    key_destroyed: bool
    cleanup_completed: bool


def destroy_profile_storage(
    pm: ProfileManager,
    *,
    prepare_runtime: Optional[Callable[[], object]] = None,
    clear_runtime_keys: Optional[Callable[[], None]] = None,
    protector: Optional[KeyProtector] = None,
    cleanup: Callable[[Path], None] = secure_remove_path,
    key_destroyed_callback: Optional[Callable[[], None]] = None,
    failure_callback: Optional[Callable[[str, bool], None]] = None,
) -> ProfileDestructionResult:
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
        ProfileDestructionResult: Truthful completion state for every phase.
    """
    errors: dict[DestructionPhase, Exception] = {}
    runtime_prepared = True
    if prepare_runtime is not None:
        try:
            if prepare_runtime() is False:
                raise RuntimeError('Runtime preparation did not complete safely.')
        except Exception as exc:
            runtime_prepared = False
            errors[DestructionPhase.PREPARATION] = exc
    database_closed = True
    try:
        SqlManager.close_connection(pm.paths.get_db_file())
    except Exception as exc:
        database_closed = False
        errors[DestructionPhase.DATABASE_CLOSE] = exc
    runtime_keys_cleared = True
    if clear_runtime_keys is not None:
        try:
            clear_runtime_keys()
        except Exception as exc:
            runtime_keys_cleared = False
            errors[DestructionPhase.RUNTIME_KEY_RELEASE] = exc
    key_destroyed = False
    try:
        active_protector = protector or PasswordKeyProtector(
            pm.paths.get_keyslot_file()
        )
        active_protector.destroy()
    except Exception as exc:
        errors[DestructionPhase.KEY_DESTRUCTION] = exc
    else:
        key_destroyed = True
    if key_destroyed and key_destroyed_callback is not None:
        try:
            key_destroyed_callback()
        except Exception as exc:
            errors[DestructionPhase.MILESTONE_NOTIFICATION] = exc
    cleanup_completed = False
    if key_destroyed:
        try:
            cleanup(pm.paths.get_config_dir())
            cleanup_completed = True
        except Exception as exc:
            errors[DestructionPhase.CLEANUP] = exc

    result = ProfileDestructionResult(
        runtime_prepared=runtime_prepared,
        database_closed=database_closed,
        runtime_keys_cleared=runtime_keys_cleared,
        key_destroyed=key_destroyed,
        cleanup_completed=cleanup_completed,
    )
    if errors:
        priority = (
            DestructionPhase.KEY_DESTRUCTION,
            DestructionPhase.PREPARATION,
            DestructionPhase.DATABASE_CLOSE,
            DestructionPhase.RUNTIME_KEY_RELEASE,
            DestructionPhase.MILESTONE_NOTIFICATION,
            DestructionPhase.CLEANUP,
        )
        phase = next(candidate for candidate in priority if candidate in errors)
        if failure_callback is not None:
            try:
                failure_callback(phase.value, key_destroyed)
            except Exception:
                pass
        raise errors[phase]
    return result
