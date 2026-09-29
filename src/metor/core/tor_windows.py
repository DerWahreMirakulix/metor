"""Start the trusted Windows Tor executable without creating a console window.

Stem's launch helper starts both its version probe and Tor with a bare Popen.
Windows console executables then create a window when Metor was started through
the graphical entry point. This small Windows path keeps Tor configuration on
stdin and applies the process flag at the actual Tor creation boundary.
"""

import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping

from metor.utils import Constants


_BOOTSTRAP = re.compile(rb'Bootstrapped ([0-9]{1,3})%')
_CONFIG_KEYS = frozenset(
    {
        'SocksPort',
        'ControlPort',
        'CookieAuthentication',
        'DataDirectory',
        'HiddenServiceDir',
        'HiddenServicePort',
    }
)


def _tor_config_bytes(config: Mapping[str, str]) -> bytes:
    """Serialize only Metor's fixed Tor settings, with no command injection.

    Args:
        config: Tor settings constructed by the daemon, never from raw IPC.
    Returns:
        bytes: Bounded configuration for Tor's standard input.
    """
    if set(config) != _CONFIG_KEYS:
        raise ValueError('Unexpected Tor configuration key.')
    lines: list[str] = []
    for key, value in config.items():
        if type(value) is not str or not value or '\n' in value or '\r' in value:
            raise ValueError('Invalid Tor configuration value.')
        lines.append(f'{key} {value}\n')
    lines.append('Log NOTICE stdout\n')
    payload = ''.join(lines).encode('utf-8')
    if len(payload) > Constants.WINDOWS_TOR_CONFIG_MAX_BYTES:
        raise ValueError('Tor configuration exceeds its size limit.')
    return payload


def launch_tor_without_console(
    *,
    tor_cmd: str,
    config: Mapping[str, str],
    init_msg_handler: Callable[[str], None] | None = None,
) -> subprocess.Popen[bytes]:
    """Launch and supervise Windows Tor bootstrap with a bounded wait.

    A background reader drains the child's pipe for its whole lifetime. Only
    bootstrap percentages reach the optional diagnostics callback. The caller
    owns the returned process and terminates it during daemon shutdown.

    Args:
        tor_cmd: Previously resolved local Tor executable.
        config: Fixed Tor configuration supplied through stdin.
        init_msg_handler: Optional callback for non-sensitive bootstrap status.
    Returns:
        subprocess.Popen[bytes]: Bootstrapped Tor process.
    Raises:
        OSError: Spawn, configuration delivery, timeout, or bootstrap failed.
    """
    payload = _tor_config_bytes(config)
    creation_flags: int = int(getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if os.name == 'nt' and creation_flags == 0:
        raise OSError('Windows console suppression is unavailable.')
    process = subprocess.Popen(
        [tor_cmd, '-f', '-', '__OwningControllerProcess', str(os.getpid())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )
    try:
        if process.stdin is None or process.stdout is None:
            raise OSError('Tor pipes are unavailable.')
        process.stdin.write(payload)
        process.stdin.close()

        completed: queue.Queue[bool] = queue.Queue(maxsize=1)

        def read_bootstrap() -> None:
            """Drain Tor output and signal the first completed bootstrap."""
            assert process.stdout is not None
            try:
                while chunk := process.stdout.readline(
                    Constants.WINDOWS_TOR_LOG_LINE_MAX_BYTES
                ):
                    match = _BOOTSTRAP.search(chunk)
                    if match is None:
                        continue
                    percent = int(match.group(1))
                    if init_msg_handler is not None:
                        try:
                            init_msg_handler(f'Bootstrapped {percent}%')
                        except Exception:
                            pass
                    if percent >= 100:
                        try:
                            completed.put_nowait(True)
                        except queue.Full:
                            pass
            finally:
                try:
                    process.stdout.close()
                except OSError:
                    pass
                try:
                    completed.put_nowait(False)
                except queue.Full:
                    pass

        threading.Thread(
            target=read_bootstrap,
            name='metor-tor-output',
            daemon=True,
        ).start()
        deadline = time.monotonic() + Constants.WINDOWS_TOR_BOOTSTRAP_TIMEOUT_SEC
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError('Tor bootstrap timed out.')
            try:
                if completed.get(
                    timeout=min(remaining, Constants.TOR_BOOTSTRAP_POLL_SEC)
                ):
                    return process
                raise OSError('Tor exited before bootstrap completed.')
            except queue.Empty:
                if process.poll() is not None:
                    raise OSError('Tor exited before bootstrap completed.')
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        raise
