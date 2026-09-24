"""Real disposable child-lifetime regression for chat-owned local daemons."""

import os
import select
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import psutil

from metor.data import ProfileManager
from metor.utils import Constants

if sys.platform != 'win32':
    import pty


@unittest.skipIf(sys.platform == 'win32', 'POSIX pseudo terminal required')
class ChatOwnedLifetimeTests(unittest.TestCase):
    """Use a locked encrypted fixture so no Tor or user profile is touched."""

    def test_lost_chat_parent_stops_its_exact_child(self) -> None:
        """A killed chat owner leaves no live session daemon behind.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory(prefix='metor-owned-test-') as root:
            profile_root = Path(root) / '.metor'
            with patch.object(Constants, 'DATA', profile_root):
                created = ProfileManager.add_profile_folder(
                    'owned-test', master_password='disposable-test-password'
                )
                self.assertTrue(created.success)
                environment = os.environ.copy()
                environment['METOR_DATA_DIR_PARENT'] = root
                master, slave = pty.openpty()
                chat = subprocess.Popen(
                    [
                        sys.executable,
                        '-I',
                        '-m',
                        'metor',
                        '-p',
                        'owned-test',
                        'chat',
                        '--start-daemon',
                    ],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=root,
                    env=environment,
                    start_new_session=True,
                )
                os.close(slave)
                daemon_pid: int | None = None
                try:
                    captured = b''
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        readable, _, _ = select.select([master], [], [], 0.2)
                        if readable:
                            try:
                                captured += os.read(master, 4096)
                            except OSError:
                                break
                            if b'Enter Master Password to unlock daemon:' in captured:
                                daemon_pid = ProfileManager(
                                    'owned-test'
                                ).get_daemon_pid()
                                break
                        if chat.poll() is not None:
                            break
                    self.assertIsNotNone(daemon_pid)
                    assert daemon_pid is not None
                    owner_args = psutil.Process(daemon_pid).cmdline()
                    self.assertEqual(
                        owner_args[owner_args.index('--chat-owner-pid') + 1],
                        str(chat.pid),
                    )
                    os.kill(chat.pid, signal.SIGKILL)
                    chat.wait(timeout=5)
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        try:
                            alive = (
                                psutil.Process(daemon_pid).status()
                                != psutil.STATUS_ZOMBIE
                            )
                        except psutil.NoSuchProcess:
                            alive = False
                        if not alive:
                            break
                        time.sleep(0.2)
                    self.assertFalse(alive)
                finally:
                    if chat.poll() is None:
                        chat.kill()
                        chat.wait(timeout=5)
                    os.close(master)
                    if daemon_pid is not None:
                        try:
                            daemon = psutil.Process(daemon_pid)
                            if daemon.status() != psutil.STATUS_ZOMBIE:
                                daemon.terminate()
                                daemon.wait(timeout=10)
                        except psutil.NoSuchProcess:
                            pass
