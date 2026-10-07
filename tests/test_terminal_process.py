"""Real Terminal PTY, authenticated IPC and encrypted peer messaging acceptance."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from frontend_e2e_runtime import EncryptedFrontendRuntime, FIXTURE_WAIT_SECONDS
from metor.client import MetorRequestRejectedError
from metor.core.api import (
    AcceptCommand,
    ConnectedEvent,
    ConfigUpdatedEvent,
    InvalidTargetEvent,
    ContactsDataEvent,
    Delivery,
    GetContactsListCommand,
    GetMessagesCommand,
    MarkReadCommand,
    MessageDirectionCode,
    MessagesDataEvent,
    MessageStatusCode,
    SetConfigCommand,
    TextContent,
    UnreadMessagesEvent,
)
from terminal_pty import PTY_POLL_SECONDS, TerminalProcess


_FRAGMENT_DELAY_SECONDS: float = PTY_POLL_SECONDS * 2
_COMPACT_COLUMNS: int = 42


@unittest.skipUnless(os.name == 'posix', 'POSIX controlling PTY acceptance')
class TerminalStartupProcessTests(unittest.TestCase):
    """Verify frontend selection failures through the actual public entry point."""

    def test_empty_profile_guidance_has_nonzero_status_and_no_traceback(self) -> None:
        """An empty customer installation gives a concrete profile-creation next step."""
        with TemporaryDirectory(prefix='metor-terminal-empty-') as temporary:
            root = Path(temporary)
            child = TerminalProcess(
                [
                    sys.executable,
                    '-m',
                    'metor',
                    'chat',
                    '--ui',
                    'terminal',
                    '--no-start-daemon',
                ],
                environment={**os.environ, 'METOR_DATA_DIR_PARENT': temporary},
                cwd=root,
            )
            self.addCleanup(child.close)
            child.wait_text(
                'No profiles exist yet. Create one with `metor profiles add NAME`.'
            )
            self.assertEqual(child.wait_exit(), 1)
            self.assertNotIn('Traceback', child.output)
            self.assertFalse((root / '.metor' / 'profiles').exists())


@unittest.skipUnless(os.name == 'posix', 'POSIX controlling PTY acceptance')
class TerminalProcessTests(unittest.TestCase):
    """Drive user keys through the actual frontend and verify actual Core outcomes.

    Tor/SOCKS routes are controlled loopback adapters. Terminal input, renderer,
    SDK serialization/auth, daemon handlers, SQLCipher and signed peer frames
    remain actual production paths. Every child starts outside the checkout.
    """

    def setUp(self) -> None:
        """Start two isolated real encrypted Core runtimes and one observer per peer."""
        self.runtime = self.enterContext(EncryptedFrontendRuntime(paired=True))
        self.observer = self.runtime.client()
        assert self.runtime.peer is not None
        self.peer = self.runtime.peer.client()
        self.timings: dict[str, float] = {}
        self.children: list[TerminalProcess] = []
        self.addCleanup(self._report)

    def _report(self) -> None:
        """Optionally persist synthetic acceptance evidence outside the repository."""
        configured = os.environ.get('METOR_TERMINAL_E2E_REPORT')
        if configured:
            for index, child in enumerate(self.children):
                if child.process.poll() is not None and child.process.poll() < 0:
                    diagnostic = Path(configured).with_name(
                        self._testMethodName + f'-{index}.terminal.log'
                    )
                    diagnostic.write_text(
                        child.output.replace(self.runtime.password, '[redacted]'),
                        encoding='utf-8',
                    )
            report = {
                'test': self.id(),
                'timings_seconds': self.timings,
                'children': [
                    {
                        'status': child.process.poll(),
                        'output_characters': len(child.output),
                    }
                    for child in self.children
                ],
                'boundary': 'real Terminal PTY and Core IPC; controlled loopback Tor adapter',
            }
            with Path(configured).open('a', encoding='utf-8') as output:
                output.write(json.dumps(report, ensure_ascii=True) + '\n')

    def _launch(self, *, authenticate: bool = True) -> TerminalProcess:
        """Launch the public installed frontend with actual hidden password input."""
        started = time.monotonic()
        child = TerminalProcess(
            [
                sys.executable,
                '-m',
                'metor',
                '-p',
                self.runtime.endpoint_profile_name,
                'chat',
                '--ui',
                'terminal',
                '--no-start-daemon',
            ],
            environment=self.runtime.environment(),
            cwd=self.runtime.data_parent,
        )
        self.addCleanup(child.close)
        self.children.append(child)
        child.wait_text('Enter Master Password: ')
        if authenticate:
            child.write(self.runtime.password.encode('utf-8') + b'\r')
            child.wait_text('Your onion address:')
            child.wait_text('No telephone calls.')
            self.timings['authenticated_startup'] = time.monotonic() - started
            self.assertNotIn(self.runtime.password, child.output)
            child.wait_text('\x1b[?2004h', raw=True)
        return child

    def _wait_messages(
        self,
        *,
        incoming: bool,
        texts: list[str],
        status: MessageStatusCode | None = None,
    ) -> MessagesDataEvent:
        """Verify exact durable outcomes through the independently authenticated SDK."""
        assert self.runtime.peer is not None
        client = self.observer if incoming else self.peer
        target = self.runtime.peer.onion if incoming else self.runtime.onion
        deadline = time.monotonic() + FIXTURE_WAIT_SECONDS
        while time.monotonic() < deadline:
            for child in self.children:
                child.poll_output()
            try:
                archive = client.request(GetMessagesCommand(target), MessagesDataEvent)
            except MetorRequestRejectedError as rejected:
                if not isinstance(rejected.event, InvalidTargetEvent):
                    raise
                time.sleep(PTY_POLL_SECONDS)
                continue
            observed = [
                row.content.text
                for row in archive.messages
                if isinstance(row.content, TextContent)
                and row.direction is MessageDirectionCode.IN
                and (status is None or row.status is status)
            ]
            if all(observed.count(text) == 1 for text in texts):
                return archive
            time.sleep(PTY_POLL_SECONDS)
        self.fail('Actual peer archive did not contain the exact expected messages.')

    def _add_and_focus(self, child: TerminalProcess, alias: str = 'McAlice') -> None:
        """Create the actual mixed-case contact through terminal keys and open DROP."""
        assert self.runtime.peer is not None
        marker = child.line(f'/contacts add {alias} {self.runtime.peer.onion}')
        child.wait_text(f"Contact '{alias}' added successfully", after=marker)
        marker = child.line('/switch ' + alias)
        child.wait_text(alias + ' [Drop]', after=marker)

    def _finish(self, child: TerminalProcess) -> None:
        """Exit by command and require terminal and child cleanup."""
        child.line('/exit')
        self.assertEqual(child.wait_exit(), 0)
        child.assert_restored()

    def test_contacts_repeated_drop_async_redraw_read_and_resize(self) -> None:
        """Real peers receive repeated DROPs; async events preserve a draft and focus."""
        child = self._launch()
        marker = child.line('/not-a-command')
        child.wait_text("Unknown command: '/not-a-command'", after=marker)
        marker = child.line('without focus')
        child.wait_text('No active focus. Use /switch or /connect.', after=marker)
        self._add_and_focus(child)
        marker = child.line('/help')
        child.wait_text('/contacts', after=marker)
        child.wait_text(
            'Enter sends; Ctrl-N or Alt-Enter inserts a newline.', after=marker
        )
        marker = child.line('/call start McAlice')
        child.wait_text('Terminal cannot start or accept call audio', after=marker)
        marker = child.line('/calls')
        child.wait_text('No telephone calls.', after=marker)
        for text in ('drop before any live session', 'another immediate drop'):
            started = time.monotonic()
            child.line(text)
            self._wait_messages(incoming=False, texts=[text])
            self.timings[text.replace(' ', '_')] = time.monotonic() - started
        self.observer.request(
            SetConfigCommand('daemon.send_read_receipts', True), ConfigUpdatedEvent
        )
        child.write(b'draft prefix suffix' + b'\x1b[D' * len('suffix'))
        child.wait_text('draft prefix suffix')
        marker = len(child.output)
        rename = TerminalProcess(
            [
                sys.executable,
                '-m',
                'metor',
                '-p',
                self.runtime.endpoint_profile_name,
                'contacts',
                'rename',
                'McAlice',
                'McALICE',
            ],
            environment=self.runtime.environment(),
            cwd=self.runtime.data_parent,
        )
        self.addCleanup(rename.close)
        self.children.append(rename)
        rename.wait_text('Enter Master Password: ')
        rename.write(self.runtime.password.encode('utf-8') + b'\r')
        rename.wait_text("Alias renamed from 'McAlice' to 'McALICE'.")
        self.assertEqual(rename.wait_exit(), 0)
        rename.assert_restored(cursor=False)
        child.wait_text('McALICE [Drop]', after=marker)
        child.wait_text('draft prefix suffix', after=marker)
        marker = len(child.output)
        self.peer.send_text(
            self.runtime.onion, Delivery.DROP, 'actual inbound drop', 'terminal-inbound'
        )
        self.timings['inbound_drop_visible'] = child.wait_text(
            'actual inbound drop', after=marker
        )
        child.wait_text('draft prefix suffix', after=marker)
        self._wait_messages(
            incoming=True, texts=['actual inbound drop'], status=MessageStatusCode.READ
        )
        child.resize(rows=40, columns=_COMPACT_COLUMNS)
        marker = len(child.output)
        child.write(b'survives \r')
        self._wait_messages(incoming=False, texts=['draft prefix survives suffix'])
        contacts = self.observer.request(GetContactsListCommand(), ContactsDataEvent)
        self.assertEqual([entry.alias for entry in contacts.saved], ['McALICE'])
        child.line('/clear')
        child.wait_text('Your onion address:', after=marker)
        marker = child.line('/switch ..')
        child.wait_text('Removed focus from', after=marker)
        self._finish(child)

    def test_fragmented_unicode_arrows_paste_and_backspace(self) -> None:
        """Read boundaries cannot lose UTF-8, turn arrows into text or submit paste."""
        child = self._launch()
        self._add_and_focus(child)
        child.write(b'Gr\xc3')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'\xbc\xc3\x9fe\r')
        self._wait_messages(incoming=False, texts=['Grüße'])
        child.write(b'correctx\x7f\r')
        self._wait_messages(incoming=False, texts=['correct'])
        child.write(b'\x1b[20')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'0~paste line one\nline two\x1b[20')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'1~')
        child.wait_text('line two')
        child.write(b'\r')
        self._wait_messages(incoming=False, texts=['paste line one\nline two'])
        child.write(b'\x1b[200~single CRLF\r\nbody\x1b[201~')
        child.wait_text('body')
        child.write(b'\r')
        self._wait_messages(incoming=False, texts=['single CRLF\nbody'])
        child.write(b'\x1b[200~split CRLF\r')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'\nbody\x1b[201~')
        child.wait_text('split CRLF')
        child.write(b'\r')
        self._wait_messages(incoming=False, texts=['split CRLF\nbody'])
        child.write(b'Alt-Enter first\x1b\rsecond\r')
        self._wait_messages(incoming=False, texts=['Alt-Enter first\nsecond'])
        unsafe_paste = 'Grüße OSC \x1b]0;terminal-paste-title\x07 CSI \x1b[2J C1 \x9b2J TAB \t\nline end'
        marker = len(child.output)
        child.write(b'\x1b[200~' + unsafe_paste.encode('utf-8') + b'\x1b[201~')
        child.wait_text(r'OSC \x1b]0;terminal-paste-title\x07', after=marker)
        self.assertNotIn('\x1b]0;terminal-paste-title\x07', child.output[marker:])
        self.assertNotIn('\x9b2J', child.output[marker:])
        # Edit an ordinary character through the safely expanded draft display.
        child.write(b'\x1b[D!\r')
        expected_paste = unsafe_paste[:-1] + '!' + unsafe_paste[-1]
        self._wait_messages(incoming=False, texts=[expected_paste])
        child.write(b'arw')
        child.write(b'\x1b[')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'Do\r')
        self._wait_messages(incoming=False, texts=['arow'])
        child.write(b'\x1b[')
        time.sleep(_FRAGMENT_DELAY_SECONDS)
        child.write(b'A\x0eagain')
        child.wait_text('again')
        marker = len(child.output)
        self.peer.send_text(
            self.runtime.onion,
            Delivery.DROP,
            'history interruption',
            'terminal-history',
        )
        child.wait_text('history interruption', after=marker)
        child.wait_text('again', after=marker)
        child.write(b'\r')
        self._wait_messages(incoming=False, texts=['arow\nagain'])
        self._finish(child)

    def test_live_invitation_message_read_receipt_and_end(self) -> None:
        """Actual Terminal LIVE consent, peer consumption and receipt use the same IPC path."""
        child = self._launch()
        self._add_and_focus(child)
        self.assertTrue(self.peer.register_live_consumer())
        self.peer.request(
            SetConfigCommand('daemon.send_read_receipts', True), ConfigUpdatedEvent
        )
        marker = child.line('/connect McAlice')
        deadline = time.monotonic() + FIXTURE_WAIT_SECONDS
        while time.monotonic() < deadline:
            child.poll_output()
            snapshot = self.peer.runtime_snapshot()
            assert snapshot is not None
            if snapshot.pending:
                break
            time.sleep(PTY_POLL_SECONDS)
        else:
            self.fail('The actual peer did not receive the Terminal LIVE invitation.')
        request = snapshot.pending[0]
        self.assertEqual(request.onion, self.runtime.onion)
        self.peer.request(
            AcceptCommand(request.onion, request.action_handle), ConnectedEvent
        )
        self.timings['live_connected_visible'] = child.wait_text(
            "Connected to 'McAlice'.", after=marker
        )
        marker = child.line('actual live receipt roundtrip')
        deadline = time.monotonic() + FIXTURE_WAIT_SECONDS
        while time.monotonic() < deadline:
            child.poll_output()
            snapshot = self.peer.runtime_snapshot()
            assert snapshot is not None
            context = next(
                (
                    entry
                    for entry in snapshot.live_contexts
                    if entry.onion == self.runtime.onion
                ),
                None,
            )
            if context is not None and context.unseen_count:
                break
            time.sleep(PTY_POLL_SECONDS)
        else:
            self.fail('The real peer did not retain the Terminal LIVE message.')
        read = self.peer.request(
            MarkReadCommand(self.runtime.onion, Delivery.LIVE), UnreadMessagesEvent
        )
        assert read is not None
        self.assertEqual(
            [
                entry.content.text
                for entry in read.messages
                if isinstance(entry.content, TextContent)
            ],
            ['actual live receipt roundtrip'],
        )
        self.timings['live_read_receipt_visible'] = child.wait_text(
            'McAlice read the message.', after=marker
        )
        marker = child.line('/end McAlice')
        child.wait_text("Disconnected from 'McAlice'.", after=marker)
        child.wait_text('\n$ ', after=marker)
        marker = child.line('after ending live')
        child.wait_text('No active focus. Use /switch or /connect.', after=marker)
        self._finish(child)

    def test_unavailable_daemon_reports_actionable_guidance(self) -> None:
        """A saved forwarded endpoint that stops gives a bounded clean failure."""
        self.runtime.daemon.stop()
        child = TerminalProcess(
            [
                sys.executable,
                '-m',
                'metor',
                '-p',
                self.runtime.endpoint_profile_name,
                'chat',
                '--ui',
                'terminal',
                '--no-start-daemon',
            ],
            environment=self.runtime.environment(),
            cwd=self.runtime.data_parent,
        )
        self.addCleanup(child.close)
        self.children.append(child)
        child.wait_text('Could not connect to Daemon. Is it running?')
        self.assertEqual(child.wait_exit(), 1)
        child.assert_restored()

    def test_ctrl_d_exits_empty_prompt_and_does_not_send_a_draft(self) -> None:
        """EOF is a normal terminal exit; existing drafts are never implicitly sent."""
        child = self._launch()
        self._add_and_focus(child)
        child.write(b'unsent draft\x04')
        child.wait_text('unsent draft')
        self.assertIsNone(child.process.poll())
        child.write(b'\x7f' * len('unsent draft'))
        child.write(b'\x04')
        self.assertEqual(child.wait_exit(), 0)
        child.assert_restored()
        assert self.runtime.peer is not None
        archive = self.observer.request(
            GetMessagesCommand(self.runtime.peer.onion), MessagesDataEvent
        )
        self.assertEqual(archive.messages, [])

    def test_ctrl_c_and_authentication_cancellation_restore_terminal(self) -> None:
        """Actual Ctrl-C/EOF have bounded clean exits before and after authentication."""
        child = self._launch()
        child.write(b'\x03')
        self.assertEqual(child.wait_exit(), 0)
        child.assert_restored()
        for key in (b'\x03', b'\x04'):
            with self.subTest(key=key):
                child = self._launch(authenticate=False)
                child.write(key)
                self.assertNotEqual(child.wait_exit(), 0)
                child.assert_restored()
                self.assertNotIn(self.runtime.password, child.output)


if __name__ == '__main__':
    unittest.main()
