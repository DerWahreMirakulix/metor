"""Stable lifecycle exclusion for offline profile mutations and daemon startup."""

from contextlib import ExitStack, contextmanager
from typing import Iterator

from metor.utils import Constants, FileLock

# Local Package Imports
from .paths import Paths


@contextmanager
def offline_profile_guard(paths: Paths) -> Iterator[bool]:
    """Fences startup and claims an offline profile without waiting for daemon exit.

    Catalog mutations acquire the catalog lock first; runtime-only operations
    must not acquire it while holding this guard. A child owns the external
    instance lock throughout initialization, execution and shutdown, including
    before it publishes a PID and after its spawning parent exits unexpectedly.
    Migration/recovery locks are acquired only after this guard.

    Yields:
        bool: Whether no live instance owns the profile and mutation may proceed.
    """
    with FileLock(paths.get_daemon_start_lock_file()), ExitStack() as instance_scope:
        try:
            instance_scope.enter_context(
                FileLock(
                    paths.get_daemon_instance_lock_file(),
                    timeout=Constants.PROFILE_MUTATION_INSTANCE_LOCK_TIMEOUT_SEC,
                )
            )
        except TimeoutError:
            yield False
        else:
            yield True
