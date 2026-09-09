"""Shared CLI-side helpers for sanitizing local runtime validation errors."""


def format_safe_local_runtime_error(exc: ValueError) -> str:
    """
    Converts one local runtime validation error into a user-safe CLI message.

    Args:
        exc (ValueError): The original validation error.

    Returns:
        str: The sanitized CLI-safe error message.
    """
    message: str = str(exc).strip()
    if not message:
        return 'Failed to validate local daemon state.'

    lowered: str = message.lower()
    if any(
        token in lowered
        for token in (
            '/home/',
            '\\',
            '.db',
            '.json',
            'storage',
            'runtime mirror',
            'runtime db',
            'profile path',
            'sqlcipher',
        )
    ):
        return 'Failed to validate local daemon state.'

    return message
