"""Offline Tor control interoperability and binary-free failure checks."""

import base64
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from private_fixtures import PrivateTemporaryDirectory

from metor.core.key import KeyManager
from metor.core.tor import TorManager, _torrc_path
from metor.core.tor_control import OnionServiceControl
from metor.data.profile import ProfileManager
from metor.utils import Constants


class TorControlTests(unittest.TestCase):
    def test_untrusted_challenge_ends_before_any_profile_key_is_sent(self) -> None:
        with PrivateTemporaryDirectory() as directory:
            cookie = Path(directory) / 'control_auth_cookie'
            cookie.write_bytes(os.urandom(32))
            stream = Mock()
            stream.recv.return_value = (
                b'250 AUTHCHALLENGE SERVERHASH='
                + b'00' * 32
                + b' SERVERNONCE='
                + b'11' * 32
                + b'\r\n'
            )
            with patch('socket.create_connection', return_value=stream):
                control = OnionServiceControl(1)
                with self.assertRaisesRegex(OSError, 'identity mismatch'):
                    control.authenticate(cookie)
                control.close()
            self.assertEqual(stream.sendall.call_count, 1)
            self.assertTrue(
                stream.sendall.call_args.args[0].startswith(
                    b'AUTHCHALLENGE SAFECOOKIE '
                )
            )

    def test_real_offline_tor_registers_same_identity_after_restart(self) -> None:
        # Resolve the binary provisioned for this job. Other CLI tests initialize
        # the process-wide settings under their own isolated environment.
        configured = os.environ.get('METOR_TOR_PATH', '').strip()
        with patch.object(Constants, 'TOR_PATH', configured):
            try:
                executable = TorManager._resolve_tor_command()
            except (PermissionError, FileNotFoundError):
                if configured:
                    raise
                self.skipTest('No trusted native Tor executable available.')
        with (
            PrivateTemporaryDirectory() as directory,
            patch.object(Constants, 'DATA', Path(directory)),
        ):
            pm = ProfileManager('onion-test')
            pm.initialize()
            km = KeyManager(pm, 'synthetic-test-password')
            self.addCleanup(km.clear_sensitive_state)
            km.generate_keys()
            manager = TorManager(pm, km)
            identities = []
            for abrupt_exit in (True, False):
                manager._reserve_ports()
                data = pm.paths.get_tor_data_dir()
                config = (
                    'DisableNetwork 1\nSocksPort 0\nCookieAuthentication 1\n'
                    f'DataDirectory {_torrc_path(data)}\nControlPort {manager.control_port}\n'
                    'Log err stderr\n'
                )
                child = subprocess.Popen(
                    [
                        executable,
                        '-f',
                        '-',
                        '__OwningControllerProcess',
                        str(os.getpid()),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                manager._tm_proc = child
                try:
                    assert child.stdin is not None
                    child.stdin.write(config.encode('ascii'))
                    child.stdin.close()
                    deadline = time.monotonic() + Constants.TOR_CONTROL_TIMEOUT_SEC
                    while True:
                        self.assertIsNone(child.poll(), 'Offline Tor failed to start.')
                        try:
                            assert manager.control_port is not None
                            with socket.create_connection(
                                (Constants.LOCALHOST, manager.control_port), timeout=0.1
                            ):
                                pass
                            if (data / 'control_auth_cookie').exists():
                                break
                        except OSError:
                            pass
                        if time.monotonic() >= deadline:
                            self.fail('Offline Tor control listener not ready.')
                        time.sleep(0.025)
                    manager._register_service()
                    identities.append(manager.onion)
                    self.assertTrue(manager._is_process_running())
                    if abrupt_exit:
                        child.kill()
                        child.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
                        self.assertFalse(manager._is_process_running())

                    self.assertEqual(manager.get_address()[2]['onion'], manager.onion)
                    self.assertFalse(
                        (
                            pm.paths.get_hidden_service_dir() / Constants.TOR_SECRET_KEY
                        ).exists()
                    )
                finally:
                    manager._terminate_process()
            self.assertIsNotNone(identities[0])
            self.assertEqual(identities[0], identities[1])

    def test_control_reply_must_match_the_local_public_identity(self) -> None:
        with patch('socket.create_connection'):
            control = OnionServiceControl(1)
        from hashlib import sha3_256

        public = bytes(range(32))
        raw = (
            public
            + sha3_256(b'.onion checksum' + public + b'\x03').digest()[:2]
            + b'\x03'
        )
        service = base64.b32encode(raw).lower()
        with patch.object(
            control, '_exchange', return_value=[b'250-ServiceID=' + service, b'250 OK']
        ):
            with self.assertRaisesRegex(OSError, 'identity mismatch'):
                control.register(
                    b'== ed25519v1-secret: type0 ==\0\0\0' + bytes(64), bytes(32), 8080
                )
