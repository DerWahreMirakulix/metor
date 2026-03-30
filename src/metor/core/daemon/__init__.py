"""
Package initializer for the Metor background daemon.
Exports the main Daemon orchestrator and the ephemeral HeadlessDaemon for CLI data processing.
"""

from metor.core.daemon.engine import Daemon
from metor.core.daemon.headless import HeadlessDaemon

__all__ = ['Daemon', 'HeadlessDaemon']
