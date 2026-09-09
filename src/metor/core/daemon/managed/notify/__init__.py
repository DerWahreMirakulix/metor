"""Facade exports for the detached notification sink subsystem."""

from metor.core.daemon.managed.notify.notification import (
    NotificationPayload,
    NotificationService,
    Sink,
    build_sink,
    get_sink_type,
    register_sink_type,
)

# Importing sinks registers the built-in file and webhook sink types.
from metor.core.daemon.managed.notify.sinks import FileSink, WebhookSink


__all__ = [
    'FileSink',
    'NotificationPayload',
    'NotificationService',
    'Sink',
    'WebhookSink',
    'build_sink',
    'get_sink_type',
    'register_sink_type',
]
