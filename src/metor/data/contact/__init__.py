"""Facade exports for the contact persistence package."""

from metor.data.contact.manager import ContactManager
from metor.data.contact.models import (
    ContactAliasChange,
    ContactOperationResult,
    ContactOperationType,
    ContactRecord,
    ContactRemoval,
    ContactsSnapshot,
)


__all__ = [
    'ContactAliasChange',
    'ContactManager',
    'ContactOperationResult',
    'ContactOperationType',
    'ContactRecord',
    'ContactRemoval',
    'ContactsSnapshot',
]
