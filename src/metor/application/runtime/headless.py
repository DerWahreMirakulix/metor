"""Application-layer helpers for ephemeral local headless daemon execution."""

import socket
from typing import Callable, Optional, TypeVar

from metor.core.daemon.headless import HeadlessDaemon
from metor.data.profile import ProfileManager


ResultT = TypeVar('ResultT')


def run_with_headless_daemon(
    pm: ProfileManager,
    password: Optional[str],
    socket_handler: Callable[[socket.socket], ResultT],
) -> ResultT:
    """
    Starts one ephemeral daemon and lends its private IPC socket to the callback.

    Args:
        pm (ProfileManager): The active profile manager.
        password (Optional[str]): The optional master password.
        socket_handler: Callback using the private connected IPC socket. The
            runtime closes the channel and joins the worker before returning.

    Returns:
        ResultT: The callback result.
    """
    with HeadlessDaemon(pm, password) as headless_daemon:
        return socket_handler(headless_daemon.client_socket)
