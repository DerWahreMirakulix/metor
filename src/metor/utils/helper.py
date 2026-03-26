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


def get_header_string(text: str) -> str:
    """
    Creates a simple header string with the given text.

    Args:
        text (str): The header text to display.

    Returns:
        str: The formatted header string.
    """
    return f'--- {text} ---'


def get_divider_string(length: int = 30) -> str:
    """
    Generates a divider string consisting of dashes.

    Args:
        length (int): The number of dashes in the divider.

    Returns:
        str: The divider string.
    """
    return '-' * length
