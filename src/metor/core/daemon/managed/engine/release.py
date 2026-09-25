"""Compatibility imports for the shared runtime release coordinator."""

from metor.core.daemon.managed.runtime_release import (
    RuntimeReleaseResult,
    release_resources,
)

__all__ = ['RuntimeReleaseResult', 'release_resources']
