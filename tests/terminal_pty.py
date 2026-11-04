"""Actual Terminal process driving through a bounded POSIX pseudoterminal."""

import codecs
import errno
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import time
from typing import Mapping

if os.name == 'posix':
    import fcntl
    import pty
    import termios


PTY_TIMEOUT_SECONDS: float = 8.0
PTY_POLL_SECONDS: float = 0.05
PTY_READ_BYTES: int = 65536
PTY_OUTPUT_LIMIT_BYTES: int = 4 * 1024 * 1024
PTY_ROWS: int = 40
PTY_COLUMNS: int = 100
_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])')


def _claim_controlling_terminal() -> None:
    """Make the child session own its terminal so Ctrl-C delivers SIGINT."""
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class TerminalProcess:
    """Drive the unmodified entry point and retain its actual terminal output.

    This fixture owns only the child's PTY and bounded process lifetime. It does
    not call frontend methods, replace renderers, or intercept SDK commands.
    POSIX-specific callers must declare their platform capability explicitly.
    """

    def __init__(
        self, argv: list[str], *, environment: Mapping[str, str], cwd: Path
    ) -> None:
        """Start one actual child with standard streams bound to a controlling PTY."""
        self.master, slave = pty.openpty()
        self._closed = False
        self.output = ''
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        fcntl.ioctl(
            slave,
            termios.TIOCSWINSZ,
            struct.pack('HHHH', PTY_ROWS, PTY_COLUMNS, 0, 0),
        )
        self.original_attributes = termios.tcgetattr(slave)
        try:
            self.process = subprocess.Popen(
                argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=dict(environment),
                preexec_fn=_claim_controlling_terminal,
                close_fds=True,
            )
        except BaseException:
            os.close(self.master)
            raise
        finally:
            os.close(slave)

    @property
    def plain_output(self) -> str:
        """Return text with renderer-owned ANSI sequences removed for assertions."""
        return _ANSI.sub('', self.output).replace('\r', '')

    def write(self, data: bytes) -> None:
        """Send exact input bytes, allowing intentional packet/key fragmentation."""
        os.write(self.master, data)

    def line(self, text: str) -> int:
        """Send one user's Enter-terminated line and return its output marker."""
        marker = len(self.output)
        self.write(text.encode('utf-8') + b'\r')
        return marker

    def _read(self, timeout: float) -> None:
        """Append one bounded output chunk without waiting beyond the caller's deadline."""
        ready, _, _ = select.select([self.master], [], [], max(0.0, timeout))
        if not ready:
            return
        try:
            chunk = os.read(self.master, PTY_READ_BYTES)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return
            raise
        self.output += self._decoder.decode(chunk)
        if len(self.output.encode('utf-8')) > PTY_OUTPUT_LIMIT_BYTES:
            raise AssertionError('Terminal process exceeded the bounded output budget.')

    def poll_output(self) -> None:
        """Drain actual rendering while an independent SDK outcome is awaited."""
        self._read(0.0)

    def wait_text(
        self,
        text: str,
        *,
        after: int = 0,
        timeout: float = PTY_TIMEOUT_SECONDS,
        raw: bool = False,
    ) -> float:
        """Await actual rendered output and report the user-visible latency."""
        started = time.monotonic()
        deadline = started + timeout
        while time.monotonic() < deadline:
            rendered = (
                self.output[after:]
                if raw
                else _ANSI.sub('', self.output[after:]).replace('\r', '')
            )
            if text in rendered:
                return time.monotonic() - started
            self._read(min(PTY_POLL_SECONDS, deadline - time.monotonic()))
            if self.process.poll() is not None:
                rendered = (
                    self.output[after:]
                    if raw
                    else _ANSI.sub('', self.output[after:]).replace('\r', '')
                )
                if text in rendered:
                    return time.monotonic() - started
                break
        raise AssertionError(f'Terminal did not render expected text: {text!r}.')

    def wait_exit(self, *, timeout: float = PTY_TIMEOUT_SECONDS) -> int:
        """Require a bounded natural process exit and retain final terminal restoration."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._read(min(PTY_POLL_SECONDS, deadline - time.monotonic()))
            status = self.process.poll()
            if status is not None:
                self._read(0.0)
                return status
        raise AssertionError(
            'Terminal process did not exit within the acceptance deadline.'
        )

    def resize(self, *, rows: int, columns: int) -> None:
        """Deliver an actual terminal geometry change and the native resize signal."""
        fcntl.ioctl(
            self.master,
            termios.TIOCSWINSZ,
            struct.pack('HHHH', rows, columns, 0, 0),
        )
        self.process.send_signal(signal.SIGWINCH)

    def assert_restored(self, *, cursor: bool = True) -> None:
        """Verify the child restored echo/canonical input and the visible cursor."""
        actual = termios.tcgetattr(self.master)
        relevant = termios.ECHO | termios.ICANON
        if actual[3] & relevant != self.original_attributes[3] & relevant:
            raise AssertionError(
                'Terminal exit did not restore canonical input and echo.'
            )
        if '\x1b[?2004h' in self.output and '\x1b[?2004l' not in self.output:
            raise AssertionError('Terminal exit did not restore bracketed paste mode.')
        if cursor and '\x1b[?25h' not in self.output:
            raise AssertionError('Terminal exit did not restore cursor visibility.')
        if 'Traceback (most recent call last)' in self.output:
            raise AssertionError('Terminal interaction exposed a Python traceback.')

    def close(self) -> None:
        """Reap the owned child even when an acceptance assertion fails."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(PTY_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(PTY_TIMEOUT_SECONDS)
        finally:
            os.close(self.master)
