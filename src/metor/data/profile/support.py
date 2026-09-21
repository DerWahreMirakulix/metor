"""Shared validation helpers for public profiles and owned profile paths."""

import os
import stat
from pathlib import Path

from metor.shared import Constants


_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT: int = 0x00000400


def is_valid_profile_name(profile_name: object) -> bool:
    """Checks one exact public profile name against the canonical contract.

    Args:
        profile_name (object): Untrusted candidate identity.

    Returns:
        bool: Whether the value is a bounded exact public profile name.
    """
    return (
        isinstance(profile_name, str)
        and 0 < len(profile_name) <= Constants.FRONTEND_PROFILE_NAME_CHARACTERS
        and all(character.isalnum() or character in '-_' for character in profile_name)
    )


def normalize_profile_name(profile_name: str) -> str:
    """
    Returns a valid exact name, or an empty rejection sentinel.

    Args:
        profile_name (str): The raw profile name.

    Returns:
        str: The unchanged valid identity, or an empty string when invalid.
    """
    return profile_name if is_valid_profile_name(profile_name) else ''


def require_profile_name(profile_name: str) -> str:
    """Returns one exact public identity or raises before filesystem access.

    Args:
        profile_name (str): Untrusted candidate identity.

    Returns:
        str: The unchanged validated profile name.

    Raises:
        ValueError: If the profile identity is empty, path-like, or too long.
    """
    if not is_valid_profile_name(profile_name):
        raise ValueError('Invalid public profile name.')
    return profile_name


def validate_profile_directory(path: Path) -> None:
    """Rejects an existing profile root that is not an owned ordinary directory.

    Args:
        path (Path): Expected direct child of the configured profile data root.

    Returns:
        None

    Raises:
        ValueError: If the existing path is a link, reparse point, or non-directory.
    """
    try:
        path_info = os.lstat(path)
    except FileNotFoundError:
        return

    if stat.S_ISLNK(path_info.st_mode):
        raise ValueError('Profile directory cannot be a symbolic link.')
    file_attributes = getattr(path_info, 'st_file_attributes', 0)
    if file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError('Profile directory cannot be a Windows reparse point.')
    if not stat.S_ISDIR(path_info.st_mode):
        raise ValueError('Profile path is not a directory.')
