"""
Module containing shared utility functions used across the application.
"""


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
