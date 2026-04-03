"""
Package initializer for the Data layer.
Exposes core data managers, settings, parsers, and domain enums via a unified Facade.
"""

# 1. Base Data Layer
from metor.data.settings import (
    Settings,
    SettingKey,
    SettingSpec,
    SettingValue,
    SettingValidationError,
)
from metor.data.sql import DatabaseCorruptedError, SqlManager, SqlParam

# 2. Application Data Layer (Depends on Base Layer)
from metor.data.contact import ContactManager
from metor.data.history.codes import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
)
from metor.data.history.manager import HistoryManager
from metor.data.message import (
    MessageManager,
    MessageStatus,
    MessageDirection,
    MessageType,
)

__all__ = [
    'ContactManager',
    'HistoryActor',
    'HistoryManager',
    'HistoryEvent',
    'HistoryReasonCode',
    'MessageManager',
    'MessageStatus',
    'MessageDirection',
    'MessageType',
    'Settings',
    'SettingKey',
    'SettingSpec',
    'SettingValue',
    'SettingValidationError',
    'DatabaseCorruptedError',
    'SqlManager',
    'SqlParam',
]
