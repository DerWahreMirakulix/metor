"""Facade exports for the managed daemon runtime helpers."""

from metor.core.daemon.managed.factory import (
    CorruptedDaemonStorageError,
    InvalidDaemonPasswordError,
    RuntimeStatusCallback,
    create_managed_daemon,
)
from metor.core.daemon.managed.status import DaemonStatus


__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonStatus',
    'InvalidDaemonPasswordError',
    'RuntimeStatusCallback',
    'create_managed_daemon',
]
