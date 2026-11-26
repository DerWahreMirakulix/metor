"""Public facade for the managed daemon engine subsystem."""

from .daemon import (
    Daemon,
    DaemonLifecycle,
    RuntimeStartFailure,
    RuntimeStartupError,
    safe_start_category,
)

__all__ = [
    'Daemon',
    'DaemonLifecycle',
    'RuntimeStartFailure',
    'RuntimeStartupError',
    'safe_start_category',
]
