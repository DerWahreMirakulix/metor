"""
Package initializer for the Metor background daemon.
Exposes the main Engine to the rest of the application as 'Daemon' for backwards compatibility.
"""

from metor.core.daemon.engine import DaemonEngine as Daemon

__all__ = ['Daemon']
