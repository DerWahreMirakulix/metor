"""Catalog and listing helpers for local profile management."""

from pathlib import Path
from typing import List, Optional

from metor.data import SettingKey, Settings, SettingValidationError
from metor.utils import Constants, FileLock

# Local Package Imports
from metor.data.profile.models import (
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSummary,
)
from metor.data.profile.paths import Paths
from metor.data.profile.support import (
    is_valid_profile_name,
    normalize_profile_name,
    validate_profile_directory,
)


def load_default_profile() -> str:
    """
    Retrieves the default profile from the global settings store.

    Args:
        None

    Returns:
        str: The configured default profile name.
    """
    return Settings.get_str(SettingKey.DEFAULT_PROFILE, persist_defaults=False)


def resolve_initial_profile(explicit: str | None = None) -> str | None:
    """Select a valid initial profile and repair a stale singleton default.

    Args:
        explicit: Optional requested name; a missing name remains recoverable by GUI.
    Returns:
        str | None: Explicit name, valid default, singleton, or no selection.
    """
    if explicit is not None:
        return explicit
    profiles = get_all_profiles()
    default = load_default_profile()
    if default in profiles:
        return default
    if len(profiles) == 1:
        try:
            Settings.set(
                SettingKey.DEFAULT_PROFILE, profiles[0], expected_value=default
            )
        except SettingValidationError:
            # Another catalog writer may have selected a valid default first.
            current = load_default_profile()
            if current in profiles:
                return current
            raise
        return profiles[0]
    return None


def valid_default_profile(profiles: list[str] | None = None) -> str | None:
    """Return the configured default only when it belongs to the valid catalog.

    Args:
        profiles: Optional already scanned catalog names.
    Returns:
        str | None: Valid default identity, if any.
    """
    names = profiles if profiles is not None else get_all_profiles()
    default = load_default_profile()
    return default if default in names else None


def set_default_profile(profile_name: str) -> ProfileOperationResult:
    """Serialize an explicit default choice with catalog mutations.

    Args:
        profile_name: Requested default profile.
    Returns:
        ProfileOperationResult: Confirmed choice or validation outcome.
    """
    if not Constants.DATA.exists():
        return _set_default_profile_locked(profile_name)
    with FileLock(Constants.DATA / '.profile-catalog'):
        return _set_default_profile_locked(profile_name)


def _set_default_profile_locked(profile_name: str) -> ProfileOperationResult:
    """
    Sets one new default profile after strict name normalization.

    Args:
        profile_name (str): The requested new default profile name.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    safe_name: str = normalize_profile_name(profile_name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

    try:
        profile_path = Paths(safe_name)
    except ValueError:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

    if not profile_path.exists():
        return ProfileOperationResult(
            False,
            ProfileOperationType.PROFILE_NOT_FOUND,
            {'profile': safe_name},
        )

    Settings.set(SettingKey.DEFAULT_PROFILE, safe_name)
    return ProfileOperationResult(
        True,
        ProfileOperationType.DEFAULT_SET,
        {'profile': safe_name},
    )


def get_all_profiles() -> List[str]:
    """
    Scans the local data directory and returns all valid profile folder names.

    Args:
        None

    Returns:
        List[str]: Sorted list of valid profile names.
    """
    data_dir: Path = Constants.DATA
    if not data_dir.exists():
        return []

    ignored_folders: set[str] = {
        Constants.HIDDEN_SERVICE_DIR,
        Constants.TOR_DATA_DIR,
    }
    profiles: list[str] = []
    for entry in data_dir.iterdir():
        if entry.name in ignored_folders or not is_valid_profile_name(entry.name):
            continue
        try:
            validate_profile_directory(entry)
        except ValueError:
            continue
        profiles.append(entry.name)
    return sorted(profiles)


def get_unavailable_profile_names() -> list[str]:
    """List syntactically valid local names whose storage path is unsafe.

    Args:
        None
    Returns:
        list[str]: Sorted names with inaccessible or invalid directory entries.
    """
    if not Constants.DATA.exists():
        return []
    unavailable: list[str] = []
    for entry in Constants.DATA.iterdir():
        if not is_valid_profile_name(entry.name):
            continue
        try:
            validate_profile_directory(entry)
        except (ValueError, OSError):
            unavailable.append(entry.name)
    return sorted(unavailable)


def get_profile_summaries(
    active_profile: Optional[str] = None,
) -> List[ProfileSummary]:
    """
    Retrieves typed metadata for all local profiles.

    Args:
        active_profile (Optional[str]): The currently active profile, if known.

    Returns:
        List[ProfileSummary]: Typed local profile summaries.
    """
    from metor.data.profile.manager import ProfileManager

    active: str = active_profile if active_profile else load_default_profile()
    summaries: List[ProfileSummary] = []
    for profile_name in get_all_profiles():
        pm = ProfileManager(profile_name)
        summaries.append(
            ProfileSummary(
                name=profile_name,
                is_active=profile_name == active,
                is_remote=pm.is_remote(),
                port=pm.get_static_port(),
            )
        )

    return summaries
