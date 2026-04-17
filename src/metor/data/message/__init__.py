"""Facade exports for the message persistence package."""

from typing import TYPE_CHECKING

from metor.data.message.models import (
    MessageClearOperationType,
    MessageClearResult,
    MessageDirection,
    MessageStatus,
    MessageType,
    QueuedMessageResult,
    StoredMessageRecord,
)

if TYPE_CHECKING:
    from metor.data.message.manager import MessageManager


__all__ = [
    'MessageClearOperationType',
    'MessageClearResult',
    'MessageDirection',
    'MessageManager',
    'MessageStatus',
    'MessageType',
    'QueuedMessageResult',
    'StoredMessageRecord',
]


def __getattr__(name: str) -> object:
    """
    Lazily resolves heavy facade exports to avoid package import cycles.

    Args:
        name (str): The requested export name.

    Raises:
        AttributeError: If the export is unknown.

    Returns:
        object: The resolved export.
    """
    if name == 'MessageManager':
        from metor.data.message.manager import MessageManager

        return MessageManager

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
