"""Shared daemon lifetime contracts and real local IPC process behavior."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import cast
from unittest.mock import PropertyMock, patch

from metor.application.frontend.host import create_local_frontend_host
from metor.application.runtime.daemon import (
    DaemonStartDiagnostics,
    start_managed_daemon_process,
)
from metor.client.ipc import IpcClient
from metor.client.session import MetorClient
from metor.core.api import (
    DaemonLockedEvent,
    FrontendLeaseCommand,
    FrontendLeaseEvent,
    InitCommand,
    InitEvent,
    LockCommand,
    PrepareProfileExitCommand,
    ProfileExitPreparedEvent,
)
from metor.core.daemon.managed import read_frontend_lifetime_token
from metor.core.daemon.managed.frontend_lifetime import FrontendLifetime
from metor.data import ProfileManager
from metor.shared import Constants as SharedConstants
from metor.utils import Constants
from metor.versioning import IPC_PROTOCOL_MIN_SUPPORTED, IPC_PROTOCOL_VERSION


class FrontendLifetimeStateTests(unittest.TestCase):
    """Exercise exact socket replacement, stale credentials and bounded grace."""

    def test_both_release_orders_and_stale_socket_cannot_remove_replacement(
        self,
    ) -> None:
        """The final frontend alone starts shutdown, regardless of creation order."""
        for order in (('a', 'b'), ('b', 'a')):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as root:
                clock = [100.0]
                with patch(
                    'metor.core.daemon.managed.frontend_lifetime.time.monotonic',
                    side_effect=lambda: clock[0],
                ):
                    lifetime = FrontendLifetime(Path(root), automatic=True)
                    lifetime.publish()
                    token = read_frontend_lifetime_token(Path(root))
                    self.assertIsNotNone(token)
                    assert token is not None
                    ids = {
                        name: secrets.token_hex(
                            SharedConstants.FRONTEND_LIFETIME_ID_BYTES
                        )
                        for name in order
                    }
                    sockets = {name: cast(socket.socket, object()) for name in order}
                    lifetime.ready()
                    for name in order:
                        self.assertEqual(
                            lifetime.register(ids[name], token, sockets[name]),
                            'joined',
                        )
                    replacement = cast(socket.socket, object())
                    self.assertEqual(
                        lifetime.register(ids['a'], token, replacement), 'joined'
                    )
                    lifetime.disconnect(sockets['a'])
                    self.assertEqual(
                        lifetime.release(ids['a'], token, sockets['a']), 'released'
                    )
                    active = {'a': replacement, 'b': sockets['b']}
                    self.assertEqual(
                        lifetime.release(ids[order[0]], token, active[order[0]]),
                        'released',
                    )
                    clock[0] += Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC + 1
                    self.assertFalse(lifetime.should_stop())
                    self.assertEqual(
                        lifetime.release(ids[order[1]], token, active[order[1]]),
                        'released',
                    )
                    clock[0] += Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC + 1
                    self.assertTrue(lifetime.should_stop())
                    self.assertEqual(
                        lifetime.register(ids['a'], token, replacement), 'stopping'
                    )

    def test_crash_reconnect_suspend_and_old_daemon_token(self) -> None:
        """Disconnected leases expire, but a reconnect survives a suspend gap."""
        with tempfile.TemporaryDirectory() as root:
            clock = [100.0]
            with patch(
                'metor.core.daemon.managed.frontend_lifetime.time.monotonic',
                side_effect=lambda: clock[0],
            ):
                first = FrontendLifetime(Path(root), automatic=True)
                first.publish()
                old_token = read_frontend_lifetime_token(Path(root))
                assert old_token is not None
                first.ready()
                frontend_id = secrets.token_hex(
                    SharedConstants.FRONTEND_LIFETIME_ID_BYTES
                )
                original = cast(socket.socket, object())
                replacement = cast(socket.socket, object())
                self.assertEqual(
                    first.register(frontend_id, old_token, original), 'joined'
                )
                first.disconnect(original)
                clock[0] += Constants.FRONTEND_DISCONNECT_GRACE_SEC / 2
                self.assertEqual(
                    first.register(frontend_id, old_token, replacement), 'joined'
                )
                first.disconnect(original)
                clock[0] += Constants.FRONTEND_DISCONNECT_GRACE_SEC + 1
                self.assertFalse(first.should_stop())
                first.disconnect(replacement)
                clock[0] += Constants.FRONTEND_SUSPEND_GAP_SEC + 100
                self.assertFalse(first.should_stop())
                for _ in range(int(Constants.FRONTEND_DISCONNECT_GRACE_SEC) + 1):
                    clock[0] += 1
                    self.assertFalse(first.should_stop())
                for _ in range(int(Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC) + 1):
                    clock[0] += 1
                    first.should_stop()
                self.assertTrue(first.should_stop())

                second = FrontendLifetime(Path(root), automatic=True)
                second.publish()
                self.assertEqual(
                    second.register(frontend_id, old_token, replacement), 'denied'
                )
                first.clear_published_token()
                self.assertNotEqual(read_frontend_lifetime_token(Path(root)), old_token)

    def test_repeated_polling_gaps_cannot_renew_a_dead_frontend_forever(self) -> None:
        """Suspend grace has one finite budget across disconnect and final exit."""
        with tempfile.TemporaryDirectory() as root:
            clock = [100.0]
            with (
                patch(
                    'metor.core.daemon.managed.frontend_lifetime.time.monotonic',
                    side_effect=lambda: clock[0],
                ),
                patch.object(Constants, 'FRONTEND_MAX_SUSPEND_EXTENSION_SEC', 12.0),
            ):
                lifetime = FrontendLifetime(Path(root), automatic=True)
                lifetime.publish()
                token = read_frontend_lifetime_token(Path(root))
                assert token is not None
                frontend_id = secrets.token_hex(
                    SharedConstants.FRONTEND_LIFETIME_ID_BYTES
                )
                connection = cast(socket.socket, object())
                lifetime.ready()
                self.assertEqual(
                    lifetime.register(frontend_id, token, connection), 'joined'
                )
                lifetime.disconnect(connection)
                clock[0] += Constants.FRONTEND_SUSPEND_GAP_SEC + 1
                self.assertFalse(lifetime.should_stop())
                stopped = False
                for _ in range(20):
                    clock[0] += Constants.FRONTEND_SUSPEND_GAP_SEC + 1
                    stopped = lifetime.should_stop()
                    if stopped:
                        break
                self.assertTrue(stopped)

    def test_manual_daemon_never_gains_a_frontend_shutdown_deadline(self) -> None:
        """A later start flag cannot turn an independent instance into auto mode."""
        with tempfile.TemporaryDirectory() as root:
            lifetime = FrontendLifetime(Path(root), automatic=False)
            lifetime.publish()
            frontend_id = secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
            connection = cast(socket.socket, object())
            self.assertEqual(
                lifetime.register(frontend_id, None, connection), 'independent'
            )
            self.assertEqual(
                lifetime.release(frontend_id, None, connection), 'independent'
            )
            self.assertFalse(lifetime.should_stop())

    def test_retained_lease_capacity_has_a_typed_retryable_result(self) -> None:
        """A token holder cannot grow disconnected lease state without a bound."""
        with tempfile.TemporaryDirectory() as root:
            lifetime = FrontendLifetime(Path(root), automatic=True)
            lifetime.publish()
            token = read_frontend_lifetime_token(Path(root))
            assert token is not None
            connection = cast(socket.socket, object())
            identities = [
                secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
                for _ in range(Constants.FRONTEND_MAX_LEASES + 1)
            ]
            for frontend_id in identities[:-1]:
                self.assertEqual(
                    lifetime.register(frontend_id, token, connection), 'joined'
                )
                lifetime.disconnect(connection)
            self.assertEqual(
                lifetime.register(identities[-1], token, connection), 'full'
            )
            self.assertEqual(
                lifetime.register(identities[0], token, connection), 'joined'
            )

    def test_local_client_without_a_token_uses_init_only(self) -> None:
        """A current independent daemon needs no frontend lease command."""
        client = MetorClient(1, local_lifetime=True)
        reply = InitEvent(
            negotiated_version=IPC_PROTOCOL_VERSION,
            daemon_current_version=IPC_PROTOCOL_VERSION,
            daemon_min_supported=IPC_PROTOCOL_MIN_SUPPORTED,
        )
        with (
            patch.object(
                MetorClient,
                'is_connected',
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(client, 'request', return_value=reply) as request,
        ):
            self.assertIs(client.bootstrap(), reply)
        self.assertEqual(request.call_count, 1)
        self.assertIsInstance(request.call_args.args[0], InitCommand)


class FrontendLifetimeProcessTests(unittest.TestCase):
    """Run locked disposable daemons over actual loopback IPC without Tor."""

    def setUp(self) -> None:
        """Create a private encrypted profile used only by this test process."""
        self._temporary = tempfile.TemporaryDirectory(prefix='metor-lifetime-')
        self._root = Path(self._temporary.name)
        self._old_parent = os.environ.get('METOR_DATA_DIR_PARENT')
        os.environ['METOR_DATA_DIR_PARENT'] = str(self._root)
        self._data_patch = patch.object(Constants, 'DATA', self._root / '.metor')
        self._data_patch.start()
        self.assertTrue(
            ProfileManager.add_profile_folder(
                'lifetime-test', master_password='disposable-test-password'
            ).success
        )
        self._profile = ProfileManager('lifetime-test')
        self._processes: list[subprocess.Popen[bytes]] = []

    def tearDown(self) -> None:
        """Stop every child and remove all profile bytes after the assertion."""
        for process in self._processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        self._data_patch.stop()
        if self._old_parent is None:
            os.environ.pop('METOR_DATA_DIR_PARENT', None)
        else:
            os.environ['METOR_DATA_DIR_PARENT'] = self._old_parent
        self._temporary.cleanup()

    def _start(self, automatic: bool) -> DaemonStartDiagnostics:
        """Launch one real locked daemon and record exact child ownership."""
        diagnostics = DaemonStartDiagnostics()
        self.assertTrue(
            start_managed_daemon_process(
                self._profile,
                start_locked=True,
                automatic_lifetime=automatic,
                diagnostics=diagnostics,
            ),
            diagnostics.phase,
        )
        if diagnostics.process is not None:
            self._processes.append(diagnostics.process)
        return diagnostics

    def _connect(self) -> IpcClient:
        """Open one actual IPC socket without unlocking protected content."""
        port = self._profile.get_daemon_port()
        self.assertIsNotNone(port)
        assert port is not None
        client = IpcClient(
            port=port,
            timeout=Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC,
            on_event=lambda _event: None,
            on_disconnect=lambda: None,
        )
        self.assertTrue(client.connect(start_listener=False))
        return client

    def _lease(
        self,
        client: IpcClient,
        frontend_id: str,
        token: str | None,
        *,
        release: bool = False,
    ) -> str:
        """Exchange one typed lifetime command on a real socket."""
        client.send_command(
            FrontendLeaseCommand(frontend_id=frontend_id, token=token, release=release)
        )
        event = client.read_event(timeout=Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC)
        self.assertIsInstance(event, FrontendLeaseEvent)
        assert isinstance(event, FrontendLeaseEvent)
        return event.state

    def test_two_frontends_close_in_either_order(self) -> None:
        """The daemon survives the first release and exits after the last."""
        for closing_order in ((0, 1), (1, 0)):
            with self.subTest(closing_order=closing_order):
                diagnostics = self._start(automatic=True)
                process = diagnostics.process
                assert process is not None
                token = read_frontend_lifetime_token(
                    self._profile.paths.get_config_dir()
                )
                self.assertIsNotNone(token)
                assert token is not None
                clients = [self._connect(), self._connect()]
                ids = [
                    secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
                    for _ in clients
                ]
                try:
                    for client, frontend_id in zip(clients, ids):
                        self.assertEqual(
                            self._lease(client, frontend_id, token), 'joined'
                        )
                    first, last = closing_order
                    clients[first].send_command(PrepareProfileExitCommand())
                    prepared = clients[first].read_event(
                        timeout=Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC
                    )
                    self.assertIsInstance(prepared, ProfileExitPreparedEvent)
                    self.assertEqual(
                        self._lease(clients[last], ids[last], token), 'joined'
                    )
                    self.assertEqual(
                        self._lease(clients[first], ids[first], token, release=True),
                        'released',
                    )
                    clients[first].stop()
                    time.sleep(Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC + 0.5)
                    self.assertIsNone(process.poll())
                    self.assertEqual(
                        self._lease(clients[last], ids[last], token, release=True),
                        'released',
                    )
                    clients[last].stop()
                    process.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                    self.assertIsNone(self._profile.get_daemon_port())
                finally:
                    for client in clients:
                        client.stop()

    def test_explicit_global_lock_is_visible_to_both_frontends(self) -> None:
        """A security lock broadcasts while ordinary local release remains separate."""
        diagnostics = self._start(automatic=True)
        process = diagnostics.process
        assert process is not None
        token = read_frontend_lifetime_token(self._profile.paths.get_config_dir())
        assert token is not None
        clients = [self._connect(), self._connect()]
        ids = [
            secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
            for _ in clients
        ]
        try:
            for client, frontend_id in zip(clients, ids):
                self.assertEqual(self._lease(client, frontend_id, token), 'joined')
            clients[0].send_command(LockCommand())
            for client in clients:
                event = client.read_event(
                    timeout=Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC
                )
                self.assertIsInstance(event, DaemonLockedEvent)
            self.assertIsNone(process.poll())
            for client, frontend_id in zip(clients, ids):
                self.assertEqual(
                    self._lease(client, frontend_id, token, release=True),
                    'released',
                )
        finally:
            for client in clients:
                client.stop()
        process.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)

    def test_manual_daemon_is_borrowed_even_with_start_flag(self) -> None:
        """A host start override joins an existing manual instance without takeover."""
        diagnostics = self._start(automatic=False)
        process = diagnostics.process
        assert process is not None
        host = create_local_frontend_host(self._profile, start_daemon_override=True)

        class Interactions:
            """Fail if an already running daemon asks for startup input."""

            def confirm_daemon_start(self) -> bool:
                raise AssertionError('Unexpected start prompt')

            def request_session_auth_secret(self) -> None:
                raise AssertionError('Unexpected secret prompt')

            def show_status(self, message: str) -> None:
                raise AssertionError(message)

        result = host.bootstrap(Interactions())
        self.assertFalse(result.daemon_started_by_launcher)
        self.assertIsNone(result.lifetime_token)
        client = self._connect()
        frontend_id = secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
        self.assertEqual(self._lease(client, frontend_id, None), 'independent')
        client.stop()
        host.close()
        time.sleep(Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC + 0.5)
        self.assertIsNone(process.poll())

    def test_crashed_frontend_reconnects_without_owning_daemon_process(self) -> None:
        """An OS-closed socket retains a short slot that an exact client can replace."""
        diagnostics = self._start(automatic=True)
        process = diagnostics.process
        assert process is not None
        token = read_frontend_lifetime_token(self._profile.paths.get_config_dir())
        assert token is not None
        frontend_id = secrets.token_hex(SharedConstants.FRONTEND_LIFETIME_ID_BYTES)
        port = self._profile.get_daemon_port()
        assert port is not None
        crash_code = (
            'import os,sys,secrets; '
            'from metor.client.ipc import IpcClient; '
            'from metor.core.api import FrontendLeaseCommand; '
            'token=sys.stdin.read(); '
            'client=IpcClient(port=int(sys.argv[1]),timeout=2.0,'
            'on_event=lambda event:None,on_disconnect=lambda:None); '
            'assert client.connect(start_listener=False); '
            'client.send_command(FrontendLeaseCommand(frontend_id=sys.argv[2],token=token)); '
            'event=client.read_event(timeout=2.0); '
            'assert event.state=="joined"; '
            'sys.stdout.write("joined"); sys.stdout.flush(); os._exit(17)'
        )
        crashed = subprocess.Popen(
            [sys.executable, '-I', '-c', crash_code, str(port), frontend_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        output, _ = crashed.communicate(
            input=token.encode('ascii'),
            timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC,
        )
        self.assertEqual(crashed.returncode, 17)
        self.assertEqual(output, b'joined')
        self.assertIsNone(process.poll())
        replacement = self._connect()
        try:
            self.assertEqual(self._lease(replacement, frontend_id, token), 'joined')
            self.assertEqual(
                self._lease(replacement, frontend_id, token, release=True),
                'released',
            )
        finally:
            replacement.stop()
        process.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)

    def test_concurrent_frontend_starts_publish_one_daemon(self) -> None:
        """The shared launch lock makes one contender borrow the winner."""
        barrier = threading.Barrier(2)
        diagnostics = [DaemonStartDiagnostics(), DaemonStartDiagnostics()]
        results: list[bool | None] = [None, None]
        failures: list[BaseException] = []

        def start(index: int) -> None:
            try:
                barrier.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                results[index] = start_managed_daemon_process(
                    self._profile,
                    start_locked=True,
                    automatic_lifetime=True,
                    diagnostics=diagnostics[index],
                )
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=start, args=(index,)) for index in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, [type(error).__name__ for error in failures])
        self.assertEqual(results, [True, True])
        spawned = [item.process for item in diagnostics if item.process is not None]
        self.assertEqual(len(spawned), 1)
        self._processes.extend(spawned)
        self.assertEqual(self._profile.get_daemon_pid(), spawned[0].pid)

    def test_manual_and_frontend_starts_publish_one_daemon(self) -> None:
        """Foreground and automatic starts serialize through the same profile lock."""
        barrier = threading.Barrier(2)
        diagnostics = DaemonStartDiagnostics()
        results: list[bool] = []
        failures: list[BaseException] = []
        manual: list[subprocess.Popen[bytes]] = []

        def start_automatic() -> None:
            try:
                barrier.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                results.append(
                    start_managed_daemon_process(
                        self._profile,
                        start_locked=True,
                        automatic_lifetime=True,
                        diagnostics=diagnostics,
                    )
                )
            except BaseException as error:
                failures.append(error)

        def start_manual() -> None:
            try:
                barrier.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                process = subprocess.Popen(
                    [
                        sys.executable,
                        '-I',
                        '-m',
                        'metor',
                        '-p',
                        self._profile.profile_name,
                        'daemon',
                        '--non-interactive',
                        '--locked',
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=os.environ.copy(),
                )
                manual.append(process)
                self._processes.append(process)
            except BaseException as error:
                failures.append(error)

        threads = [
            threading.Thread(target=start_automatic),
            threading.Thread(target=start_manual),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, [type(error).__name__ for error in failures])
        self.assertEqual(results, [True])
        self.assertEqual(len(manual), 1)
        if diagnostics.process is not None:
            self._processes.append(diagnostics.process)
        active_pid = self._profile.get_daemon_pid()
        self.assertIn(
            active_pid,
            [manual[0].pid, diagnostics.process.pid if diagnostics.process else None],
        )
        deadline = time.monotonic() + Constants.FRONTEND_FINAL_RELEASE_GRACE_SEC
        while (
            sum(
                process.poll() is None
                for process in (manual[0], diagnostics.process)
                if process is not None
            )
            > 1
            and time.monotonic() < deadline
        ):
            time.sleep(Constants.LOCK_SLEEP_SEC)
        self.assertEqual(
            sum(
                process.poll() is None
                for process in (manual[0], diagnostics.process)
                if process is not None
            ),
            1,
        )

    def test_direct_children_cannot_bypass_singleton_writer_lock(self) -> None:
        """Even a direct hidden child flag cannot open two profile writers."""
        command = [
            sys.executable,
            '-I',
            '-m',
            'metor',
            '-p',
            self._profile.profile_name,
            'daemon',
            '--non-interactive',
            '--locked',
            '--parent-start-lock-held',
        ]
        children = [
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
            for _ in range(2)
        ]
        self._processes.extend(children)
        deadline = time.monotonic() + Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC
        while self._profile.get_daemon_port() is None and time.monotonic() < deadline:
            time.sleep(Constants.LOCK_SLEEP_SEC)
        self.assertIn(self._profile.get_daemon_pid(), [child.pid for child in children])
        loser = next(
            child for child in children if child.pid != self._profile.get_daemon_pid()
        )
        loser.wait(timeout=Constants.MAX_DERIVED_DAEMON_START_WAIT_SEC)
        self.assertEqual(sum(child.poll() is None for child in children), 1)


if __name__ == '__main__':
    unittest.main()
