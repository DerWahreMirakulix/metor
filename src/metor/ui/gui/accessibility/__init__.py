"""Native accessibility integration with synchronous privacy revocation."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bridge import AccessibilityBridge

__all__ = ['AccessibilityBridge']


def __getattr__(name: str) -> object:
    """Loads native integration only when the GUI application requests it.

    Args:
        name: Requested facade symbol.
    Returns:
        object: Native bridge type.
    """
    if name == 'AccessibilityBridge':
        from .bridge import AccessibilityBridge

        return AccessibilityBridge
    raise AttributeError(name)
