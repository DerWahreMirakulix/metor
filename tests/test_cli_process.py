"""Actual CLI processes against temporary encrypted Core and loopback peers.

Processes import the selected environment's packages from an unrelated working
directory. Only the explicit test Tor adapter is substituted: IPC, password
proofs, queued DROP content, receipt lookup and persistence are production code.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from metor.core.api import (
    Delivery,
    GetContactsListCommand,
    GetMessageOutcomeCommand,
    GetMessagesCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    MessagesDataEvent,
    TextContent,
    ContactsDataEvent,
)
from metor.shared import escape_terminal_text
from metor.utils import Constants

from frontend_e2e_runtime import EncryptedFrontendRuntime


PROCESS_WAIT_SECONDS: float = Constants.DEFAULT_IPC_TIMEOUT
DELIVERY_POLL_SECONDS: float = Constants.WORKER_SLEEP_SEC


class CliProcessTests(unittest.TestCase):
    """Verify observable process output, status, side effects and actual IPC."""

    def setUp(self) -> None:
        """Prepare an unrelated working directory and fresh host data root."""
        temporary = TemporaryDirectory(prefix='metor-cli-process-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = {
            **os.environ,
            'METOR_DATA_DIR_PARENT': str(self.root),
            'PYTHONUNBUFFERED': '1',
        }

    def run_cli(
        self,
        *arguments: str,
        input_text: str = '',
        runtime: EncryptedFrontendRuntime | None = None,
        authenticate: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Launch the actual CLI module without handler mocks or shell parsing.

        Args:
            arguments: Literal process arguments including any option boundary.
            input_text: Explicit stdin for credential creation or cancellation.
            runtime: Optional actual protected daemon endpoint.
            authenticate: Whether to provide the disposable endpoint password.
        Returns:
            subprocess.CompletedProcess[str]: Observed process result.
        """
        environment = self.environment
        argv = list(arguments)
        if runtime is not None:
            environment = runtime.environment()
            argv = ['-p', runtime.endpoint_profile_name, *argv]
            if authenticate:
                input_text = runtime.password + '\n'
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, '-m', 'metor', *argv],
            input=input_text,
            text=True,
            capture_output=True,
            cwd=self.root,
            env=environment,
            timeout=PROCESS_WAIT_SECONDS,
            check=False,
        )
        self.assertNotIn('Traceback (most recent call last)', result.stderr)
        if runtime is not None:
            self.assertNotIn(runtime.password, result.stdout + result.stderr)
        report = os.environ.get('METOR_CLI_E2E_REPORT')
        if report:
            with Path(report).open('a', encoding='utf-8') as stream:
                stream.write(
                    json.dumps(
                        {
                            'case': self.id(),
                            'command': arguments[0] if arguments else 'quickstart',
                            'exit_code': result.returncode,
                            'elapsed_seconds': time.monotonic() - started,
                            'actual_core': runtime is not None,
                        }
                    )
                    + '\n'
                )
        return result

    def test_help_version_and_ui_discovery_have_no_profile_side_effects(self) -> None:
        """First-run discovery works before any profile or daemon exists."""
        for arguments, expected in (
            ([], 'Quick Start'),
            (['--help'], 'Contact Management'),
            (['chat', '--help'], '--ui FRONTEND'),
            (['chat', '--list-uis'], 'terminal\tmetor-ui-terminal'),
            (['--version'], '.'),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)
                self.assertFalse((self.root / Constants.DATA_DIR).exists())
        installed_check = os.environ.get('METOR_E2E_REQUIRE_INSTALLED') == '1'
        if installed_check:
            probe = subprocess.run(
                [
                    sys.executable,
                    '-c',
                    'from pathlib import Path; import metor.cli.entry as m; '
                    'print(Path(m.__file__).resolve())',
                ],
                capture_output=True,
                text=True,
                cwd=self.root,
                env=self.environment,
                timeout=PROCESS_WAIT_SECONDS,
                check=False,
            )
            self.assertEqual(probe.returncode, 0)
            checkout = Path(__file__).resolve().parents[1]
            self.assertFalse(Path(probe.stdout.strip()).is_relative_to(checkout))

    def test_missing_profile_and_invalid_launcher_exit_without_creating_profile(
        self,
    ) -> None:
        """Invalid invocations are bounded failures with readable recovery hints."""
        for arguments, expected, status in (
            (['contacts', 'list'], "Profile 'default' does not exist", 1),
            (['chat', '--ui', 'missing-e2e-ui'], 'missing-e2e-ui', 2),
            (['chat', '--ui', 'terminal', '--simulator'], 'gui frontend', 2),
            (['chat', '--unexpected'], 'Unexpected chat arguments', 2),
            (['send'], 'metor send', 1),
            (['unknown-e2e-command'], 'metor help', 1),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, status)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertFalse((self.root / Constants.DATA_DIR / 'default').exists())

    def test_rejected_password_creation_never_reports_success_or_creates_profile(
        self,
    ) -> None:
        """Mismatch, empty input and EOF fail without a partial protected profile."""
        for name, input_text, expected in (
            ('Mismatch', 'first\nsecond\n', 'passwords do not match'),
            ('Empty', '\n\n', 'master password must not be empty'),
            ('Cancelled', '', 'Profile creation aborted'),
        ):
            with self.subTest(name=name):
                result = self.run_cli('profiles', 'add', name, input_text=input_text)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stdout)
                self.assertNotIn('successfully created', result.stdout)
                self.assertFalse((self.root / Constants.DATA_DIR / name).exists())

    def test_encrypted_profile_lifecycle_and_local_settings_persist_across_processes(
        self,
    ) -> None:
        """Independent commands create, rename, select and read the same profile."""
        password = 'disposable-cli-profile-password'
        created = self.run_cli(
            'profiles', 'add', 'MixedCase', input_text=password + '\n' + password + '\n'
        )
        self.assertEqual(created.returncode, 0)
        self.assertIn('successfully created', created.stdout)
        self.assertNotIn(password, created.stdout + created.stderr)
        renamed = self.run_cli('profiles', 'rename', 'MixedCase', 'RenamedCase')
        self.assertEqual(renamed.returncode, 0)
        self.assertIn('RenamedCase', renamed.stdout)
        selected = self.run_cli('profiles', 'set-default', 'RenamedCase')
        self.assertEqual(selected.returncode, 0)
        listed = self.run_cli('profiles', 'list')
        self.assertEqual(listed.returncode, 0)
        self.assertIn('RenamedCase', listed.stdout)
        updated = self.run_cli('config', 'set', 'client.ipc_timeout', '5.5')
        self.assertEqual(updated.returncode, 0)
        read = self.run_cli('config', 'get', 'client.ipc_timeout')
        self.assertEqual(read.returncode, 0)
        self.assertIn('5.5', read.stdout)
        refused = self.run_cli('send', 'Nobody', 'retained input')
        self.assertEqual(refused.returncode, 1)
        self.assertIn('daemon must be running', refused.stdout)
        missing_clear = self.run_cli('profiles', 'clear', 'Absent')
        self.assertEqual(missing_clear.returncode, 1)
        self.assertIn("Profile 'Absent' does not exist", missing_clear.stdout)

    def test_plaintext_refusal_has_specific_reason_and_failure_status(self) -> None:
        """The deployment restriction survives typed IPC instead of a generic error."""
        result = self.run_cli('profiles', 'add', 'Unsafe', '--plaintext')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Plaintext profiles are disabled', result.stdout)
        self.assertNotIn('Internal daemon error', result.stdout)

    def test_unreachable_forwarded_daemon_fails_instead_of_claiming_success(
        self,
    ) -> None:
        """A closed loopback tunnel produces a useful nonzero CLI outcome."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind((Constants.LOCALHOST, 0))
            port = int(reservation.getsockname()[1])
        created = self.run_cli(
            'profiles', 'add', 'Forwarded', '--remote', '--port', str(port)
        )
        self.assertEqual(created.returncode, 0)
        result = self.run_cli('-p', 'Forwarded', 'contacts', 'list')
        self.assertEqual(result.returncode, 1)
        self.assertIn('SSH tunnel', result.stdout)

    def test_connection_close_before_result_is_unknown_and_never_success(self) -> None:
        """Actual EOF after receiving a command does not fabricate its confirmation."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((Constants.LOCALHOST, 0))
            listener.listen(1)
            listener.settimeout(PROCESS_WAIT_SECONDS)
            port = int(listener.getsockname()[1])
            seen = threading.Event()

            def close_after_frame() -> None:
                """Read a real request and lose its result at the transport boundary."""
                with listener.accept()[0] as connection:
                    connection.settimeout(PROCESS_WAIT_SECONDS)
                    data = bytearray()
                    while b'\n' not in data:
                        part = connection.recv(Constants.TCP_BUFFER_SIZE)
                        if not part:
                            break
                        data.extend(part)
                    seen.set()

            self.assertEqual(
                self.run_cli(
                    'profiles', 'add', 'Uncertain', '--remote', '--port', str(port)
                ).returncode,
                0,
            )
            worker = threading.Thread(target=close_after_frame)
            worker.start()
            try:
                result = self.run_cli('-p', 'Uncertain', 'contacts', 'list')
                self.assertTrue(seen.is_set())
                self.assertEqual(result.returncode, 1)
                self.assertIn('outcome is unknown', result.stdout)
                self.assertNotIn('executed successfully', result.stdout)
            finally:
                worker.join(PROCESS_WAIT_SECONDS)
                self.assertFalse(worker.is_alive())

    def test_actual_authentication_cancel_preserves_core_and_exits_nonzero(
        self,
    ) -> None:
        """EOF and an empty password cannot become a successful protected action."""
        with EncryptedFrontendRuntime(paired=False) as runtime:
            observer = runtime.client()
            for input_text in ('', '\n'):
                with self.subTest(input_text=input_text):
                    result = self.run_cli(
                        'contacts',
                        'add',
                        'Denied',
                        runtime.onion,
                        input_text=input_text,
                        runtime=runtime,
                        authenticate=False,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('Aborted.', result.stdout)
            contacts = observer.request(GetContactsListCommand(), ContactsDataEvent)
            self.assertEqual(contacts.saved, [])

    def test_actual_contacts_drop_receipts_and_literal_content_without_live(
        self,
    ) -> None:
        """CLI argv reaches real Core storage and peer delivery once per send."""
        with EncryptedFrontendRuntime(paired=True) as runtime:
            assert runtime.peer is not None
            observer = runtime.client()
            recipient = runtime.peer.client()
            add = self.run_cli(
                'contacts', 'add', 'Straße', runtime.peer.onion, runtime=runtime
            )
            self.assertEqual(add.returncode, 0)
            rename = self.run_cli(
                'contacts', 'rename', 'strasse', 'STRASSE', runtime=runtime
            )
            self.assertEqual(rename.returncode, 0)
            self.assertEqual(
                observer.request(GetContactsListCommand(), ContactsDataEvent)
                .saved[0]
                .alias,
                'STRASSE',
            )
            payloads = [
                'first process DROP',
                '--help --version --daemon-child --ui gui -- second process DROP',
                'literal \x1b]0;unsafe-title\x07 \x1b[2J third process DROP',
            ]
            for payload in payloads:
                result = self.run_cli('send', 'strasse', '--', payload, runtime=runtime)
                self.assertEqual(result.returncode, 0)
                self.assertIn('successfully queued', result.stdout)
                self.assertNotIn(payload, result.stdout)
            sender_page = observer.request(
                GetMessagesCommand(target=runtime.peer.onion), MessagesDataEvent
            )
            sent = [
                entry
                for entry in sender_page.messages
                if entry.direction is MessageDirectionCode.OUT
            ]
            self.assertEqual(len(sent), len(payloads))
            self.assertEqual(len({entry.msg_id for entry in sent}), len(payloads))
            self.assertCountEqual(
                [
                    entry.content.text
                    for entry in sent
                    if isinstance(entry.content, TextContent)
                ],
                payloads,
            )
            for entry in sent:
                self.assertIs(entry.delivery, Delivery.DROP)
                assert entry.msg_id is not None
                outcome = observer.request(
                    GetMessageOutcomeCommand(runtime.peer.onion, entry.msg_id),
                    MessageOutcomeEvent,
                )
                self.assertIsNotNone(outcome)
            deadline = time.monotonic() + PROCESS_WAIT_SECONDS
            while True:
                received = recipient.request(
                    GetMessagesCommand(target=runtime.onion), MessagesDataEvent
                )
                if len(received.messages) == len(payloads):
                    break
                self.assertLess(
                    time.monotonic(), deadline, 'Actual DROP delivery did not finish'
                )
                time.sleep(DELIVERY_POLL_SECONDS)
            self.assertCountEqual(
                [
                    entry.content.text
                    for entry in received.messages
                    if isinstance(entry.content, TextContent)
                ],
                payloads,
            )
            for entry in sent:
                assert entry.msg_id is not None
                while True:
                    outcome = observer.request(
                        GetMessageOutcomeCommand(runtime.peer.onion, entry.msg_id),
                        MessageOutcomeEvent,
                    )
                    if outcome.status in (
                        MessageStatusCode.DELIVERED,
                        MessageStatusCode.READ,
                    ):
                        break
                    self.assertLess(
                        time.monotonic(), deadline, 'Actual DROP receipt did not finish'
                    )
                    time.sleep(DELIVERY_POLL_SECONDS)
            self.assertEqual(observer.runtime_snapshot().live_contexts, [])
            rendered = self.run_cli('messages', 'STRASSE', runtime=runtime)
            self.assertEqual(rendered.returncode, 0)
            self.assertIn(escape_terminal_text(payloads[-1]), rendered.stdout)
            self.assertNotIn('\x1b]0;', rendered.stdout)
            self.assertNotIn('\x1b[2J', rendered.stdout)

    def test_invalid_trailing_operands_never_mutate_actual_contacts(self) -> None:
        """Typographical extra operands cannot silently clear or rename contacts."""
        with EncryptedFrontendRuntime(paired=False) as runtime:
            observer = runtime.client()
            self.assertEqual(
                self.run_cli(
                    'contacts', 'add', 'Kept', runtime.onion, runtime=runtime
                ).returncode,
                0,
            )
            for arguments in (
                ['contacts', 'clear', 'unexpected'],
                ['contacts', 'rename', 'Kept', 'Changed', 'unexpected'],
                ['contacts', 'rm', 'Kept', 'unexpected'],
                ['contacts', 'list', 'unexpected'],
                ['config', 'sync', 'unexpected'],
                ['settings', 'set', 'client.ipc_timeout', '5.5', 'unexpected'],
                ['profiles', 'clear', runtime.profile_name, 'unexpected'],
            ):
                with self.subTest(arguments=arguments):
                    result = self.run_cli(*arguments, runtime=runtime)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('Enter Master Password', result.stderr)
                    contacts = observer.request(
                        GetContactsListCommand(), ContactsDataEvent
                    )
                    self.assertEqual(
                        [entry.alias for entry in contacts.saved], ['Kept']
                    )


if __name__ == '__main__':
    unittest.main()
