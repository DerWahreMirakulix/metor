"""Catalog and listing helpers for local profile management."""

from pathlib import Path
from typing import List, Optional

from metor.data import SettingKey, Settings
from metor.utils import Constants

# Local Package Imports
from metor.data.profile.models import (
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSummary,
)
from metor.data.profile.support import normalize_profile_name


def load_default_profile() -> str:
    """
    Retrieves the default profile from the global settings store.

    Args:
        None

    Returns:
        str: The configured default profile name.
    """
    return Settings.get_str(SettingKey.DEFAULT_PROFILE)


def set_default_profile(profile_name: str) -> ProfileOperationResult:
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
    return sorted(
        d.name
        for d in data_dir.iterdir()
        if d.is_dir() and d.name not in ignored_folders
    )


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
