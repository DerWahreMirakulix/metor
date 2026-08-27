"""Facade exports for the managed daemon runtime helpers."""

from metor.core.daemon.managed.factory import (
    CorruptedDaemonStorageError,
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    RuntimeStatusCallback,
    create_managed_daemon,
)
from metor.core.daemon.managed.notify import (
    FileSink,
    NotificationPayload,
    NotificationService,
    Sink,
    WebhookSink,
    build_sink,
    get_sink_type,
    register_sink_type,
)
from metor.core.daemon.managed.status import DaemonStatus


__all__ = [
    'CorruptedDaemonStorageError',
    'DaemonStatus',
    'FileSink',
    'InvalidDaemonPasswordError',
    'NotificationPayload',
    'NotificationService',
    'PlaintextLockedDaemonError',
    'RuntimeStatusCallback',
    'Sink',
    'WebhookSink',
    'build_sink',
    'create_managed_daemon',
    'get_sink_type',
    'register_sink_type',
]
