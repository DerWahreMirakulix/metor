"""Exercise the remote SDK over a disposable, loopback-only OpenSSH forward."""

import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock

from frontend_e2e_runtime import EncryptedFrontendRuntime, FixtureAuthProvider
from private_fixtures import PrivateTemporaryDirectory
from metor.client import MetorClient
from metor.data import ProfileManager
from metor.data.profile.ipc_identity import daemon_tls_context, read_daemon_certificate


class SshTunnelTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform.startswith('linux'), 'requires unprivileged Linux OpenSSH'
    )
    def test_pinned_daemon_over_local_forward(self) -> None:
        """Only the paired daemon may receive a credential through a real SSH forward."""
        import pwd

        ssh = shutil.which('ssh')
        keygen = shutil.which('ssh-keygen')
        sshd = os.getenv('METOR_TEST_SSHD') or shutil.which(
            'sshd', path=os.environ.get('PATH', '') + ':/usr/sbin'
        )
        if not (ssh and keygen and sshd) or os.geteuid() == 0:
            if os.environ.get('METOR_REQUIRE_SSH_TEST') == '1':
                self.fail(
                    'The SSH integration gate requires OpenSSH and a non-root account.'
                )
            self.skipTest('Unprivileged OpenSSH client and server unavailable')
        address = '127.0.0.1'
        profile = self.enterContext(EncryptedFrontendRuntime(paired=False))
        root = Path(self.enterContext(PrivateTemporaryDirectory()))
        other = Path(self.enterContext(PrivateTemporaryDirectory()))
        daemon_tls_context(other)
        for name in ('host', 'user'):
            subprocess.run(
                [
                    keygen,
                    '-q',
                    '-t',
                    'ed25519',
                    '-N',
                    '',
                    '-C',
                    'fixture',
                    '-f',
                    str(root / name),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
        username = pwd.getpwuid(os.geteuid()).pw_name
        config = root / 'sshd_config'
        config.write_text(
            f'HostKey "{root / "host"}"\nAuthorizedKeysFile "{root / "user.pub"}"\n'
            # The 0700 fixture can reside under /tmp, outside the account's home.
            'StrictModes no\nUsePAM no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n'
            'AuthenticationMethods publickey\nPermitRootLogin no\nAllowTcpForwarding local\n'
            f'PermitOpen {address}:{profile.port}\n'
            'AllowAgentForwarding no\nAllowStreamLocalForwarding no\nMaxSessions 0\n',
            encoding='ascii',
        )
        known = root / 'known_hosts'
        known.write_text(
            'metor-test ' + (root / 'host.pub').read_text('ascii'), encoding='ascii'
        )
        with socket.socket() as reservation:
            reservation.bind((address, 0))
            local_port = reservation.getsockname()[1]
        # Supplying one accepted TCP connection to sshd's inetd mode keeps it
        # outside system service management and prevents any other SSH sessions.
        with socket.socket() as listener:
            listener.bind((address, 0))
            listener.listen(1)
            listener.settimeout(10)
            client_process = subprocess.Popen(
                [
                    ssh,
                    '-F',
                    '/dev/null',
                    '-N',
                    '-T',
                    '-p',
                    str(listener.getsockname()[1]),
                    '-i',
                    str(root / 'user'),
                    '-o',
                    'IdentityAgent=none',
                    '-o',
                    'IdentitiesOnly=yes',
                    '-o',
                    'StrictHostKeyChecking=yes',
                    '-o',
                    'HostKeyAlias=metor-test',
                    '-o',
                    f'UserKnownHostsFile="{known}"',
                    '-o',
                    'GlobalKnownHostsFile=/dev/null',
                    '-o',
                    'BatchMode=yes',
                    '-o',
                    'ExitOnForwardFailure=yes',
                    '-L',
                    f'{address}:{local_port}:{address}:{profile.port}',
                    f'{username}@{address}',
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.addCleanup(self._stop, client_process)
            accepted, _ = listener.accept()
            with accepted:
                server_process = subprocess.Popen(
                    [sshd, '-i', '-e', '-f', str(config)],
                    stdin=accepted,
                    stdout=accepted,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            self.addCleanup(self._stop, server_process)

        remote = ProfileManager(profile.endpoint_profile_name)
        sdk = MetorClient(
            local_port,
            daemon_certificate=remote.get_daemon_certificate(),
            auth_provider=FixtureAuthProvider(),
            timeout=3,
        )
        self.addCleanup(sdk.disconnect)
        deadline = time.monotonic() + 15
        while not sdk.connect():
            self.assertIsNone(
                client_process.poll(), 'OpenSSH client exited before forwarding'
            )
            self.assertIsNone(
                server_process.poll(), 'OpenSSH server exited before forwarding'
            )
            self.assertLess(
                time.monotonic(), deadline, 'OpenSSH forward did not become ready'
            )
            time.sleep(0.05)
        self.assertIsNotNone(sdk.bootstrap())
        snapshot = sdk.runtime_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.profile, profile.profile_name)
        attempted = Mock()
        wrong = MetorClient(
            local_port,
            daemon_certificate=read_daemon_certificate(other),
            auth_provider=attempted,
            timeout=3,
        )
        self.addCleanup(wrong.disconnect)
        self.assertIsNone(wrong.bootstrap())
        self.assertEqual(attempted.mock_calls, [])

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        """Reap the temporary SSH subprocess and any connection children."""
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(5)
