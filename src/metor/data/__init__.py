"""
Package initializer for the Data layer.
Exposes core data managers, settings, and domain enums via a unified Facade.
"""

# 1. Base Data Layer (No external/child dependencies)
from metor.data.settings import Settings, SettingKey
from metor.data.sql import SqlManager

# 2. Application Data Layer (Depends on Base Layer and Profile)
from metor.data.contact import ContactManager
from metor.data.history import HistoryManager, HistoryEvent
from metor.data.message import (
    MessageManager,
    MessageStatus,
    MessageDirection,
    MessageType,
)

__all__ = [
    'ContactManager',
    'HistoryManager',
    'HistoryEvent',
    'MessageManager',
    'MessageStatus',
    'MessageDirection',
    'MessageType',
    'Settings',
    'SettingKey',
    'SqlManager',
]
