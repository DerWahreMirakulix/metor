"""Profile migration and lifecycle gates against competing recovery and startup."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from metor.data import SettingKey, Settings, SqlManager
from metor.data.profile import ProfileManager, ProfileOperationType, ProfileSecurityMode
from metor.core.key import KeyManager
from metor.application.frontend.identity import profile_address
from metor.client import FrontendProfileAddressRequest
from metor.utils import Constants, FileLock


class ProfileMigrationConcurrencyTests(unittest.TestCase):
    """Stable sibling locks survive generation swaps and serialize recovery."""

    def setUp(self) -> None:
        """Creates an isolated encrypted profile for actual filesystem transitions."""
        temporary = TemporaryDirectory(prefix='metor-migration-race-')
        self.addCleanup(temporary.cleanup)
        data = patch.object(Constants, 'DATA', Path(temporary.name))
        data.start()
        self.addCleanup(data.stop)
        self.assertTrue(
            ProfileManager.add_profile_folder(
                'migrated', master_password='old-password'
            ).success
        )
        self.profile = ProfileManager('migrated')
        self.addCleanup(SqlManager.close_connection, self.profile.paths.get_db_file())

    def test_profile_lookup_cannot_recover_an_active_migration(self) -> None:
        """Opening a profile waits for commit instead of deleting its prepared stage."""
        entered, release, observer_started, observer_done = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        errors: list[BaseException] = []
        migrated: list[bool] = []
        observed: list[bool] = []

        def checkpoint(stage: str) -> None:
            """Pauses after the journal and copied target both exist."""
            if stage == 'during_secret_transformation':
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('Fixture release timed out.')

        def migrate() -> None:
            """Runs the actual encrypted-to-plaintext transaction."""
            try:
                result = ProfileManager.migrate_profile_security(
                    'migrated',
                    ProfileSecurityMode.PLAINTEXT,
                    current_password='old-password',
                )
                migrated.append(result.success)
            except BaseException as exc:
                errors.append(exc)

        def observe() -> None:
            """Constructs an ordinary reader while the transaction is prepared."""
            observer_started.set()
            try:
                observed.append(ProfileManager('migrated').uses_plaintext_storage())
            except BaseException as exc:
                errors.append(exc)
            finally:
                observer_done.set()

        original_get_bool = Settings.get_bool

        def allow_plaintext(key: SettingKey, *args: object, **kwargs: object) -> bool:
            """Enables only the deliberate plaintext migration capability."""
            if key is SettingKey.ALLOW_PLAINTEXT_PROFILES:
                return True
            return original_get_bool(key)

        worker = threading.Thread(target=migrate)
        observer = threading.Thread(target=observe)
        with (
            patch.object(Settings, 'get_bool', side_effect=allow_plaintext),
            patch(
                'metor.data.profile.migration.orchestrator._migration_checkpoint',
                side_effect=checkpoint,
            ),
        ):
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                observer.start()
                self.assertTrue(observer_started.wait(1))
                self.assertFalse(observer_done.wait(0.05))
                self.assertTrue(
                    (Constants.DATA / '.migrated.security-migration.staged').exists()
                )
                with self.assertRaises(TimeoutError):
                    with FileLock(
                        self.profile.paths.get_daemon_start_lock_file(), timeout=0.01
                    ):
                        pass
            finally:
                release.set()
                worker.join(3)
                if observer.ident is not None:
                    observer.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(observer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(migrated, [True])
        self.assertEqual(observed, [True])

    def test_lifecycle_mutations_hold_start_gate_before_runtime_check(self) -> None:
        """Removal and rename cannot race a new daemon past their offline check."""
        for operation in ('rename', 'remove'):
            with self.subTest(operation=operation):
                name = f'profile-{operation}'
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        name, master_password='password'
                    ).success
                )
                profile = ProfileManager(name)
                checked: list[bool] = []

                def is_offline(_profile: ProfileManager) -> bool:
                    """Confirms a competing startup cannot enter during the check."""
                    with self.assertRaises(TimeoutError):
                        with FileLock(
                            profile.paths.get_daemon_start_lock_file(), timeout=0.01
                        ):
                            pass
                    checked.append(True)
                    return False

                with patch.object(ProfileManager, 'is_daemon_running', is_offline):
                    result = (
                        ProfileManager.rename_profile_folder(name, f'{name}-renamed')
                        if operation == 'rename'
                        else ProfileManager.remove_profile_folder(name)
                    )
                self.assertTrue(result.success)
                self.assertEqual(checked, [True])

    def test_unpublished_instance_refuses_all_destructive_profile_mutations(
        self,
    ) -> None:
        """Parent loss or cleared PID does not expose the child-owned profile."""
        with FileLock(self.profile.paths.get_daemon_instance_lock_file()):
            results = (
                ProfileManager.remove_profile_folder('migrated'),
                ProfileManager.rename_profile_folder('migrated', 'renamed'),
                ProfileManager.migrate_profile_security(
                    'migrated', ProfileSecurityMode.PLAINTEXT, 'old-password'
                ),
            )
        self.assertEqual(
            [result.operation_type for result in results],
            [
                ProfileOperationType.CANNOT_REMOVE_RUNNING,
                ProfileOperationType.CANNOT_RENAME_RUNNING,
                ProfileOperationType.CANNOT_MIGRATE_RUNNING,
            ],
        )
        self.assertTrue(self.profile.exists())
        self.assertTrue(self.profile.uses_encrypted_storage())
        self.assertFalse((Constants.DATA / 'renamed').exists())

    def test_creation_is_fenced_until_key_and_database_initialization_finishes(
        self,
    ) -> None:
        """A newly visible directory does not admit daemon startup before it is complete."""
        original = KeyManager.generate_keys
        checked: list[bool] = []

        def generate_under_gate(manager: KeyManager) -> None:
            """Checks real external startup exclusion during protected creation."""
            profile = ProfileManager('created')
            self.assertTrue(profile.exists())
            for lock in (
                profile.paths.get_daemon_start_lock_file(),
                profile.paths.get_daemon_instance_lock_file(),
            ):
                with self.assertRaises(TimeoutError):
                    with FileLock(lock, timeout=0.01):
                        pass
            checked.append(True)
            original(manager)

        with patch.object(KeyManager, 'generate_keys', generate_under_gate):
            result = ProfileManager.add_profile_folder(
                'created', master_password='creation-password'
            )
        self.assertTrue(result.success)
        self.assertEqual(checked, [True])
        ProfileManager('created').validate_integrity()

    def test_frontend_address_refuses_unpublished_instance_before_opening_keys(
        self,
    ) -> None:
        """The direct host address path shares the same Core runtime exclusion."""
        with (
            FileLock(self.profile.paths.get_daemon_instance_lock_file()),
            patch('metor.application.frontend.identity.KeyManager') as key_manager,
        ):
            result = profile_address(
                FrontendProfileAddressRequest('migrated', 'selected'), 'old-password'
            )
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'address_cant_generate_running')
        key_manager.assert_not_called()

    def test_frontend_address_keeps_runtime_gate_until_keys_are_cleared(self) -> None:
        """The direct host credential owner remains exclusive throughout its cleanup."""
        original = KeyManager.clear_sensitive_state
        cleared: list[bool] = []

        def clear_under_gate(manager: KeyManager) -> None:
            """Confirms exclusion at the real protected-key release boundary."""
            with self.assertRaises(TimeoutError):
                with FileLock(
                    self.profile.paths.get_daemon_instance_lock_file(), timeout=0.01
                ):
                    pass
            original(manager)
            cleared.append(True)

        with patch.object(KeyManager, 'clear_sensitive_state', clear_under_gate):
            profile_address(
                FrontendProfileAddressRequest('migrated', 'selected', False),
                'old-password',
            )
        self.assertEqual(cleared, [True])


if __name__ == '__main__':
    unittest.main()
