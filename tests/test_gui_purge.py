"""Scoped purge milestones against temporary encrypted profiles, never host power or owner data."""

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import MetorClient, build_session_auth_proof
from metor.core.api import (
    IpcEvent,
    SelfDestructCommand,
    SelfDestructInitiatedEvent,
    SelfDestructRuntimeReleasedEvent,
    SelfDestructKeyDestroyedEvent,
    SelfDestructSafeEvent,
    SelfDestructCompletedEvent,
    SelfDestructCleanupFailedEvent,
)
from metor.core.profile_destruction import destroy_profile_storage
from metor.data.sql import SqlManager


class CombinedDestructionTests(unittest.TestCase):
    """Checks every prerequisite independently without any real storage destruction."""

    def test_database_close_failure_retains_pool_state_for_truthful_retry(
        self,
    ) -> None:
        """A lower connection failure blocks safe milestones and remains retryable.

        Args:
            None

        Returns:
            None
        """
        root = Path(self.enterContext(TemporaryDirectory()))
        db_path = root / 'profile.db'
        path_key = str(db_path)
        connection = Mock()
        connection.close.side_effect = [OSError('injected close failure'), None]
        metadata = Mock()
        producers = Mock()
        pm = Mock()
        pm.paths.get_db_file.return_value = db_path
        pm.paths.get_config_dir.return_value = root
        protector = Mock()
        events: list[str] = []
        failures: list[tuple[str, bool]] = []

        with (
            patch.dict(SqlManager._connections, {path_key: connection}),
            patch.dict(SqlManager._metadata_repositories, {path_key: metadata}),
            patch.dict(SqlManager._producer_repositories, {path_key: producers}),
        ):
            with self.assertRaisesRegex(OSError, 'injected close failure'):
                destroy_profile_storage(
                    pm,
                    prepare_runtime=lambda: events.append('runtime'),
                    clear_runtime_keys=lambda: events.append('memory'),
                    protector=protector,
                    cleanup=lambda _path: events.append('cleanup'),
                    runtime_released_callback=lambda: events.append('runtime_released'),
                    safe_callback=lambda: events.append('safe'),
                    failure_callback=lambda phase, destroyed: failures.append(
                        (phase, destroyed)
                    ),
                )

            self.assertIs(SqlManager._connections[path_key], connection)
            self.assertIs(SqlManager._metadata_repositories[path_key], metadata)
            self.assertIs(SqlManager._producer_repositories[path_key], producers)
            self.assertNotIn('runtime_released', events)
            self.assertNotIn('safe', events)
            self.assertEqual(failures, [('database_close', True)])
            self.assertIn('memory', events)
            self.assertIn('cleanup', events)

            result = destroy_profile_storage(
                pm,
                prepare_runtime=lambda: None,
                clear_runtime_keys=lambda: None,
                protector=protector,
                cleanup=lambda _path: None,
            )

            self.assertTrue(result.database_closed)
            self.assertNotIn(path_key, SqlManager._connections)
            self.assertNotIn(path_key, SqlManager._metadata_repositories)
            self.assertNotIn(path_key, SqlManager._producer_repositories)
            self.assertEqual(connection.close.call_count, 2)

            SqlManager.close_connection(db_path)
            self.assertEqual(connection.close.call_count, 2)

    def test_safe_milestone_requires_all_runtime_and_key_successes(self) -> None:
        """Key removal despite an earlier failure cannot authorize a device power cut.

        Args:
            None
        Returns:
            None
        """
        for failure in ('none', 'runtime', 'database', 'memory', 'key', 'cleanup'):
            with self.subTest(failure=failure):
                order = []
                pm = Mock()
                pm.paths.get_db_file.return_value = Path('/tmp/unused-purge-fixture.db')
                pm.paths.get_config_dir.return_value = Path('/tmp/unused-purge-fixture')

                def step(name: str) -> None:
                    """Records ordered synthetic release and injects one selected phase failure.

                    Args:
                        name: Exact synthetic phase.
                    Returns:
                        None
                    """
                    order.append(name)
                    if failure == name:
                        raise OSError('injected phase failure')

                protector = Mock()
                protector.destroy.side_effect = lambda: step('key')
                with patch.object(
                    SqlManager,
                    'close_connection',
                    side_effect=lambda _path: step('database'),
                ):

                    def run() -> None:
                        """Invokes production ordering with inert storage and release collaborators.

                        Args:
                            None
                        Returns:
                            None
                        """
                        destroy_profile_storage(
                            pm,
                            prepare_runtime=lambda: step('runtime'),
                            clear_runtime_keys=lambda: step('memory'),
                            protector=protector,
                            cleanup=lambda _path: step('cleanup'),
                            key_destroyed_callback=lambda: order.append('key_event'),
                            runtime_released_callback=lambda: order.append(
                                'runtime_event'
                            ),
                            safe_callback=lambda: order.append('safe_event'),
                        )

                    if failure == 'none':
                        run()
                    else:
                        with self.assertRaises(OSError):
                            run()
                self.assertEqual('safe_event' in order, failure in {'none', 'cleanup'})
                self.assertEqual(
                    'runtime_event' in order, failure in {'none', 'key', 'cleanup'}
                )
                self.assertEqual('key_event' in order, failure != 'key')
                self.assertEqual('cleanup' in order, failure != 'key')
                if 'safe_event' in order:
                    self.assertLess(order.index('key_event'), order.index('safe_event'))
                    self.assertLess(order.index('safe_event'), order.index('cleanup'))

    def test_operation_identity_is_optional_but_strict_when_present(self) -> None:
        """Old callers keep their command shape; malformed correlation IDs grant nothing.

        Args:
            None
        Returns:
            None
        """
        self.assertIsNone(SelfDestructCommand().operation_id)
        self.assertEqual(SelfDestructCommand('a' * 32).operation_id, 'a' * 32)
        for value in ('', 'a' * 31, 'A' * 32, 'g' * 32, True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SelfDestructCommand(value)


class PurgeCoreTests(unittest.TestCase):
    """Exercises actual managed teardown, encrypted keyslot removal, IPC and profile scoping."""

    def setUp(self) -> None:
        """Creates an isolated protected runtime and an authenticated milestone consumer.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.events: list[IpcEvent] = []
        self.finished = threading.Event()
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        self.client = MetorClient(
            self.h.daemon._ipc.port, auth_provider=provider, on_event=self.receive
        )
        self.addCleanup(self.client.disconnect)
        initialized = self.client.bootstrap()
        self.assertIn('purge_safe_milestone', initialized.capabilities)
        self.operation = 'a' * 32
        self.keyslot = self.h.pm.paths.get_keyslot_file()
        self.assertTrue(self.keyslot.exists())
        self.unrelated = (
            self.h.pm.paths.get_config_dir().parent / 'unrelated-fixture.txt'
        )
        self.unrelated.write_text('unrelated fixture')

    def receive(self, event: IpcEvent) -> None:
        """Collects public events and waits for an actual terminal cleanup result.

        Args:
            event: Actual current client's public callback.
        Returns:
            None
        """
        self.events.append(event)
        if isinstance(
            event, (SelfDestructCompletedEvent, SelfDestructCleanupFailedEvent)
        ):
            self.finished.set()

    def purge(self) -> list[type[IpcEvent]]:
        """Performs one authorized destruction against only the temporary test profile.

        Args:
            None
        Returns:
            list[type[IpcEvent]]: Observed exact-operation milestones.
        """
        initial = self.client.request(
            SelfDestructCommand(self.operation), SelfDestructInitiatedEvent
        )
        self.assertEqual(initial.operation_id, self.operation)
        self.assertEqual(initial.profile, 'voice-owned')
        self.assertTrue(self.finished.wait(20))
        scoped = [
            event
            for event in self.events
            if getattr(event, 'operation_id', None) == self.operation
        ]
        self.assertTrue(scoped)
        self.assertTrue(all(event.profile == 'voice-owned' for event in scoped))
        self.assertFalse(self.keyslot.exists())
        self.assertEqual(self.unrelated.read_text(), 'unrelated fixture')
        return [type(event) for event in scoped]

    def test_combined_safe_precedes_success_and_preserves_unrelated_files(self) -> None:
        """All runtime release and protected key removal precede a scoped safe milestone.

        Args:
            None
        Returns:
            None
        """
        events = self.purge()
        self.assertEqual(
            events,
            [
                SelfDestructRuntimeReleasedEvent,
                SelfDestructKeyDestroyedEvent,
                SelfDestructSafeEvent,
                SelfDestructCompletedEvent,
            ],
        )
        self.assertFalse(self.h.pm.paths.get_config_dir().exists())

    def test_runtime_release_failure_removes_key_without_claiming_safe(self) -> None:
        """A failed actual runtime abort suppresses both runtime-safe and combined-safe events.

        Args:
            None
        Returns:
            None
        """
        with patch.object(
            self.h.daemon._network,
            'abort_all',
            side_effect=OSError('injected abort failure'),
        ):
            events = self.purge()
        self.assertIn(SelfDestructKeyDestroyedEvent, events)
        self.assertIn(SelfDestructCleanupFailedEvent, events)
        self.assertNotIn(SelfDestructRuntimeReleasedEvent, events)
        self.assertNotIn(SelfDestructSafeEvent, events)

    def test_cleanup_failure_follows_safe_without_restoring_keys(self) -> None:
        """Encrypted file cleanup failure is separate from confirmed profile access destruction.

        Args:
            None
        Returns:
            None
        """

        def destroy(pm: object, **kwargs: object) -> object:
            """Injects cleanup failure only after production runtime and keyslot destruction.

            Args:
                pm: Isolated temporary profile.
                kwargs: Actual production lifecycle callbacks.
            Returns:
                object: Actual destruction result, if successful.
            """
            self.assertIs(pm, self.h.pm)
            return destroy_profile_storage(
                pm,
                cleanup=Mock(side_effect=OSError('injected cleanup failure')),
                **kwargs,
            )

        with patch(
            'metor.core.daemon.managed.engine.lifecycle.destroy_profile_storage',
            side_effect=destroy,
        ):
            events = self.purge()
        self.assertLess(
            events.index(SelfDestructSafeEvent),
            events.index(SelfDestructCleanupFailedEvent),
        )
        self.assertNotIn(SelfDestructCompletedEvent, events)


if __name__ == '__main__':
    unittest.main()
