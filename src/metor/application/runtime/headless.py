"""Application-layer helpers for ephemeral local headless daemon execution."""

from typing import Callable, Optional, TypeVar

from metor.core.daemon.headless import HeadlessDaemon
from metor.data import Settings
from metor.data.profile import ProfileManager


ResultT = TypeVar('ResultT')


def run_with_headless_daemon(
    pm: ProfileManager,
    password: Optional[str],
    port_handler: Callable[[int], ResultT],
) -> ResultT:
    """
    Starts one ephemeral headless daemon and executes a callback against its port.

    Args:
        pm (ProfileManager): The active profile manager.
        password (Optional[str]): The optional master password.
        port_handler (Callable[[int], ResultT]): Callback executed with the IPC port.

    Returns:
        ResultT: The callback result.
    """
    Settings.validate_integrity()
    pm.validate_integrity()

    with HeadlessDaemon(pm, password) as headless_daemon:
        return port_handler(headless_daemon.port)
