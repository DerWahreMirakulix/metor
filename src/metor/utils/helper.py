"""
Module containing shared utility functions used across the application.
"""

import stat
import secrets
from pathlib import Path


def clean_onion(onion: str) -> str:
    """
    Strips whitespace and the '.onion' suffix from a given onion address.

    Args:
        onion (str): The raw onion address string.

    Returns:
        str: The cleaned 56-character onion address.
    """
    onion = onion.strip().lower()
    if onion.endswith('.onion'):
        onion = onion[:-6]
    return onion


def ensure_onion_format(onion: str) -> str:
    """
    Ensures the given onion address has the correct '.onion' suffix.

    Args:
        onion (str): The onion address string.

    Returns:
        str: The fully formatted onion address.
    """
    clean: str = clean_onion(onion)
    return f'{clean}.onion'


def get_header_string(text: str) -> str:
    """
    Creates a simple header string with the given text.

    Args:
        text (str): The header text to display.

    Returns:
        str: The formatted header string.
    """
    return f'--- {text} ---'


def get_divider_string(length: int = 30, add_spaces: bool = False) -> str:
    """
    Generates a divider string consisting of dashes.

    Args:
        length (int): The number of dashes in the divider.
        add_space (bool): Whether to add a space between the dashes.

    Returns:
        str: The divider string.
    """
    divider = '-' * length
    if add_spaces:
        divider = ' '.join(divider)
    return divider


def secure_shred_file(file_path: Path) -> None:
    """
    Securely overwrites a file with cryptographic random bytes before deleting it.
    Note: File shredding may be ineffective on modern SSDs due to wear-leveling.

    Args:
        file_path (Path): The path to the file to be shredded.

    Returns:
        None
    """
    if not file_path.exists() or not file_path.is_file():
        return

    try:
        # Ensure we have write permissions
        file_path.chmod(stat.S_IWRITE)

        # Overwrite with random bytes matching the exact file size
        with file_path.open('ba+') as f:
            length: int = f.tell()
            f.seek(0)
            f.write(secrets.token_bytes(length))

        # Unlink from filesystem
        file_path.unlink()
    except Exception:
        pass
