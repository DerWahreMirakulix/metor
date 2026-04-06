"""Facade exports for daemon-shared bootstrap helpers."""

from metor.core.daemon.bootstrap import (
    InvalidMasterPasswordError,
    verify_master_password,
)


__all__ = [
    'InvalidMasterPasswordError',
    'verify_master_password',
]
