"""
Module handling OPSEC and security-critical file operations.
Mitigates Data-At-Rest risks via cryptographic file shredding.
"""

import stat
import secrets
from pathlib import Path


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
