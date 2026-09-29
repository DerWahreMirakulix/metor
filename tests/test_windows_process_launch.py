"""Windows child-process contracts at the actual creation boundaries."""

import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from metor.core.daemon.managed.quick_unlock import QuickUnlockStore
from metor.core.tor_windows import launch_tor_without_console
from metor.utils import Constants


_TOR_CONFIG = {
    'SocksPort': '10241',
    'ControlPort': '10242',
    'CookieAuthentication': '1',
    'DataDirectory': 'C:/test/tor-data',
    'HiddenServiceDir': 'C:/test/hidden-service',
    'HiddenServicePort': '80 127.0.0.1:10243',
}


class WindowsProcessLaunchTests(unittest.TestCase):
    """Check flags, bounded bootstrap, and argument/data separation."""

    def test_tor_spawn_suppresses_console_at_real_popen_boundary(self) -> None:
        """Tor receives the window flag and configuration stays on stdin."""
        child = Mock()
        child.pid = 1234
        child.stdin = io.BytesIO()
        child.stdout = io.BytesIO(b'Bootstrapped 100% (done)\n')
        child.poll.return_value = None
        updates: list[str] = []
        with (
            patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True),
            patch(
                'metor.core.tor_windows.subprocess.Popen', return_value=child
            ) as spawn,
        ):
            result = launch_tor_without_console(
                tor_cmd='C:/trusted/tor.exe',
                config=_TOR_CONFIG,
                init_msg_handler=updates.append,
            )

        self.assertIs(result, child)
        self.assertEqual(spawn.call_args.kwargs['creationflags'], 0x08000000)
        self.assertEqual(spawn.call_args.args[0][0], 'C:/trusted/tor.exe')
        self.assertNotIn('DataDirectory', repr(spawn.call_args.args[0]))
        self.assertEqual(updates, ['Bootstrapped 100%'])
        self.assertNotIn('hidden-service', repr(updates))
        child.kill.assert_not_called()

    def test_tor_failed_bootstrap_reaps_its_child(self) -> None:
        """A failed Tor bootstrap cannot leave the spawned process behind."""
        child = Mock()
        child.stdin = io.BytesIO()
        child.stdout = io.BytesIO(b'[err] bootstrap failed\n')
        child.poll.return_value = None
        with (
            patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True),
            patch('metor.core.tor_windows.subprocess.Popen', return_value=child),
            self.assertRaises(OSError),
        ):
            launch_tor_without_console(tor_cmd='C:/trusted/tor.exe', config=_TOR_CONFIG)
        child.kill.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=Constants.TOR_KILL_TIMEOUT_SEC)

    def test_tor_rejects_config_injection_before_spawn(self) -> None:
        """Configuration values cannot add arbitrary Tor directives."""
        with (
            patch('metor.core.tor_windows.subprocess.Popen') as spawn,
            self.assertRaises(ValueError),
        ):
            launch_tor_without_console(
                tor_cmd='C:/trusted/tor.exe',
                config={**_TOR_CONFIG, 'DataDirectory': 'C:/test\nRunAsDaemon 1'},
            )
        spawn.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixture is Linux-only')
    def test_bootstrap_reader_with_real_child_process(self) -> None:
        """The bounded bootstrap pipe works with a real child and exits cleanly."""
        with TemporaryDirectory() as directory:
            child_path = Path(directory) / 'fake-tor'
            child_path.write_text(
                f'#!{sys.executable}\n'
                'import sys\n'
                'configuration = sys.stdin.read()\n'
                'assert "Log NOTICE stdout" in configuration\n'
                'print("Bootstrapped 100% (done)", flush=True)\n',
                encoding='utf-8',
            )
            child_path.chmod(0o700)
            with patch.object(subprocess, 'CREATE_NO_WINDOW', 0, create=True):
                process = launch_tor_without_console(
                    tor_cmd=str(child_path), config=_TOR_CONFIG
                )
            self.assertEqual(process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC), 0)

    def test_windows_acl_helper_suppresses_its_console(self) -> None:
        """A later PowerShell ACL operation cannot open a separate window."""
        completed = Mock(returncode=0)
        with (
            patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True),
            patch(
                'metor.core.daemon.managed.quick_unlock.subprocess.run',
                return_value=completed,
            ) as run,
        ):
            result = QuickUnlockStore._run_acl_helper(
                Path('C:/test/credential'), 'Write-Output ok', 'test'
            )
        self.assertIs(result, completed)
        self.assertEqual(run.call_args.kwargs['creationflags'], 0x08000000)
        self.assertEqual(run.call_args.args[0][0], 'powershell.exe')
        self.assertNotIn('C:/test/credential', repr(run.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
