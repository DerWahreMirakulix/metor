"""Actual Terminal peer for native GUI interoperability acceptance on POSIX.

Every method is blocking and must run outside the GUI event loop. Input enters
only through a controlling PTY; no frontend command or result is substituted.
"""

import sys

from frontend_e2e_runtime import EncryptedFrontendRuntime
from terminal_pty import TerminalProcess


_GUI_ALIAS: str = 'GuiCounterpart'


class GuiTerminalPeer:
    """Own a real Terminal process attached to the native GUI fixture's peer."""

    def __init__(self, runtime: EncryptedFrontendRuntime) -> None:
        """Retain the existing two-peer fixture without starting another Core."""
        self.runtime = runtime
        self.child: TerminalProcess | None = None
        self._ready = False

    def start(self) -> None:
        """Authenticate the Terminal and select DROP before any LIVE connection."""
        if self.child is not None:
            raise AssertionError('The native GUI Terminal counterpart already exists.')
        peer = self.runtime.peer
        assert peer is not None
        child = TerminalProcess(
            [
                sys.executable,
                '-m',
                'metor',
                '-p',
                peer.endpoint_profile_name,
                'chat',
                '--ui',
                'terminal',
                '--no-start-daemon',
            ],
            environment=self.runtime.environment(),
            cwd=self.runtime.data_parent,
        )
        self.child = child
        try:
            child.wait_text('Enter Master Password: ')
            child.write(peer.password.encode('utf-8') + b'\r')
            child.wait_text('Your onion address:')
            child.wait_text('No telephone calls.')
            assert peer.password not in child.output
            marker = child.line(f'/contacts add {_GUI_ALIAS} {self.runtime.onion}')
            child.wait_text(f"Contact '{_GUI_ALIAS}' added successfully", after=marker)
            self._focus_drop()
            self._ready = True
        except BaseException:
            child.close()
            self.child = None
            raise

    def _focus_drop(self) -> TerminalProcess:
        """Require actual DROP focus before admitting a fixture-authored message."""
        child = self.child
        assert child is not None
        marker = child.line(f'/switch {_GUI_ALIAS}')
        child.wait_text(f'{_GUI_ALIAS} [Drop]', after=marker)
        return child

    def send_drop(self, text: str) -> None:
        """Submit one text message with the real Terminal's Enter handling."""
        self._focus_drop().line(text)

    def wait_text(self, text: str) -> None:
        """Require content from the GUI to appear in the actual Terminal output."""
        assert self.child is not None
        self.child.wait_text(text)

    def close(self) -> None:
        """Require a natural exit and restore terminal state before reaping it."""
        child = self.child
        self.child = None
        if child is None:
            return
        try:
            if self._ready and child.process.poll() is None:
                child.line('/exit')
            assert child.wait_exit() == 0
            child.assert_restored()
        finally:
            child.close()
