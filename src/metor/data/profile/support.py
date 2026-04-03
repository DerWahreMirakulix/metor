"""Shared helpers for profile catalog and lifecycle services."""


def normalize_profile_name(profile_name: str) -> str:
    """
    Normalizes one profile name to the supported filesystem-safe character set.

    Args:
        profile_name (str): The raw profile name.

    Returns:
        str: The normalized profile name.
    """
    return ''.join(c for c in profile_name if c.isalnum() or c in ('-', '_'))
