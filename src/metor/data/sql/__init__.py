"""Facade exports for centralized SQL persistence and SQLCipher backend loading."""

from metor.data.sql.backends import (
    SQLCIPHER_BACKEND,
    SqlCipherConnection,
    SqlCipherCursor,
    SqlCipherDbApi,
    SqlParam,
    _load_sqlcipher_dbapi,
)
from metor.data.sql.history import HistoryRepository
from metor.data.sql.manager import DatabaseCorruptedError, SqlManager
from metor.data.sql.message import MessageReceiptRow, MessageRepository
from metor.data.sql.peer import PeerRepository, PeerRow


__all__ = [
    'DatabaseCorruptedError',
    'HistoryRepository',
    'MessageReceiptRow',
    'MessageRepository',
    'PeerRepository',
    'PeerRow',
    'SQLCIPHER_BACKEND',
    'SqlCipherConnection',
    'SqlCipherCursor',
    'SqlCipherDbApi',
    'SqlManager',
    'SqlParam',
    '_load_sqlcipher_dbapi',
]
