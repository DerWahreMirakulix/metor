"""Isolated public host profile-catalog operations and selection boundaries."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from metor.application import create_local_frontend_host
from metor.client import (
    FrontendBootstrapError,
    FrontendLaunchContext,
    FrontendBootstrapReason,
    FrontendProfileAction,
    FrontendProfileChange,
    FrontendProfileCreateRequest,
    FrontendProfileManagement,
    OneUseSecretProvider,
)
from metor.data import ProfileManager, Settings, SettingKey
from metor.utils import Constants
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class ProfileHostTests(unittest.TestCase):
    """Uses temporary profile folders only; no daemon, Tor or user profile is started."""

    def setUp(self) -> None:
        """Creates an isolated active host selection and existing catalog entries.

        Args:
            None
        Returns:
            None
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        change = patch.object(Constants, 'DATA', self.root)
        change.start()
        self.addCleanup(change.stop)
        for name in ('active', 'default', 'standby'):
            ProfileManager(name).initialize()
        self.host = create_local_frontend_host('active', False)

    def test_catalog_pages_and_mutations_retain_exact_selection(self) -> None:
        """Default/rename/remove use the public host and refuse an abandoned selection.

        Args:
            None
        Returns:
            None
        """
        self.assertIsInstance(self.host, FrontendProfileManagement)
        first = self.host.profile_catalog(limit=2)
        self.assertEqual(
            [entry.profile for entry in first.entries], ['active', 'default']
        )
        self.assertEqual(
            (first.selected_profile, first.default_profile), ('active', 'default')
        )
        second = self.host.profile_catalog(after=first.next_after, limit=2)
        self.assertEqual([entry.profile for entry in second.entries], ['standby'])
        self.assertIsNone(second.next_after)
        selected = self.host.manage_profile(
            FrontendProfileChange(FrontendProfileAction.SET_DEFAULT, 'active', 'active')
        )
        self.assertTrue(selected.success)
        self.assertEqual(self.host.profile_catalog().default_profile, 'active')
        refused = self.host.manage_profile(
            FrontendProfileChange(FrontendProfileAction.REMOVE, 'active', 'active')
        )
        self.assertFalse(refused.success)
        self.assertTrue(ProfileManager('active').exists())
        stale = self.host.manage_profile(
            FrontendProfileChange(FrontendProfileAction.REMOVE, 'standby', 'default')
        )
        self.assertEqual(stale.code, 'selection_changed')
        self.assertTrue(ProfileManager('standby').exists())
        renamed = self.host.manage_profile(
            FrontendProfileChange(
                FrontendProfileAction.RENAME, 'standby', 'active', 'renamed'
            )
        )
        self.assertTrue(renamed.success)
        self.assertFalse(ProfileManager('standby').exists())
        self.assertTrue(ProfileManager('renamed').exists())
        removed = self.host.manage_profile(
            FrontendProfileChange(FrontendProfileAction.REMOVE, 'renamed', 'active')
        )
        self.assertTrue(removed.success)
        self.assertFalse(ProfileManager('renamed').exists())
        self.assertEqual(self.host.profile_state().profile, 'active')

    def test_creation_keeps_active_selection_and_consumes_secret(self) -> None:
        """A real protected creation does not switch or bootstrap the current runtime.

        Args:
            None
        Returns:
            None
        """
        secret = OneUseSecretProvider('test-new-profile-password')
        result = self.host.create_profile_entry(
            FrontendProfileCreateRequest('created'), secret
        )
        self.assertTrue(result.success, result.code)
        self.assertIsNone(secret.take())
        self.assertTrue(ProfileManager('created').uses_encrypted_storage())
        self.assertEqual(self.host.profile_state().profile, 'active')
        self.assertFalse(self.host.profile_state().daemon_running)
        self.assertTrue(
            any(
                entry.profile == 'created'
                for entry in self.host.profile_catalog().entries
            )
        )

    def test_default_rename_preserves_reference_without_overwriting_a_newer_default(
        self,
    ) -> None:
        """The GUI host follows a renamed default and preserves another writer's new choice.

        Args:
            None
        Returns:
            None
        """
        change = FrontendProfileChange(
            FrontendProfileAction.RENAME, 'default', 'active', 'renamed'
        )
        result = self.host.manage_profile(change)
        self.assertTrue(result.success)
        self.assertEqual(ProfileManager.load_default_profile(), 'renamed')
        original = Settings.set

        def newer(
            key: SettingKey, value: object, *, expected_value: object = None
        ) -> None:
            """Interposes a genuine newer global selection before the guarded rename update.

            Args:
                key: Actual global setting key.
                value: Requested renamed reference.
                expected_value: Original default profile identity.
            Returns:
                None
            """
            original(SettingKey.DEFAULT_PROFILE, 'standby')
            original(key, value, expected_value=expected_value)

        with patch.object(Settings, 'set', side_effect=newer):
            result = self.host.manage_profile(
                FrontendProfileChange(
                    FrontendProfileAction.RENAME, 'renamed', 'active', 'renamed_again'
                )
            )
        self.assertTrue(result.success)
        self.assertTrue(ProfileManager('renamed_again').exists())
        self.assertEqual(ProfileManager.load_default_profile(), 'standby')

    def test_rename_partial_result_does_not_hide_a_completed_directory_change(
        self,
    ) -> None:
        """A failed default-reference write reports the actual completed rename boundary.

        Args:
            None
        Returns:
            None
        """
        with patch.object(Settings, 'set', side_effect=OSError('test write failure')):
            result = self.host.manage_profile(
                FrontendProfileChange(
                    FrontendProfileAction.RENAME, 'default', 'active', 'renamed'
                )
            )
        self.assertFalse(result.success)
        self.assertEqual(result.code, 'renamed_default_unconfirmed')
        self.assertEqual(result.profile, 'renamed')
        self.assertFalse(ProfileManager('default').exists())
        self.assertTrue(ProfileManager('renamed').exists())

    def test_busy_and_running_profiles_refuse_without_side_effects(self) -> None:
        """The host does not wait on a graphical bootstrap prompt or stop a running profile.

        Args:
            None
        Returns:
            None
        """
        with self.host._attempt_lock:
            secret = OneUseSecretProvider('discard-on-busy')
            with self.assertRaises(FrontendBootstrapError) as failure:
                self.host.create_profile_entry(
                    FrontendProfileCreateRequest('busy'), secret
                )
            self.assertIs(failure.exception.reason, FrontendBootstrapReason.BUSY)
            self.assertIsNone(secret.take())
        self.assertFalse(ProfileManager('busy').exists())
        with patch.object(ProfileManager, 'is_daemon_running', return_value=True):
            for action, new_name in (
                (FrontendProfileAction.REMOVE, None),
                (FrontendProfileAction.RENAME, 'renamed'),
            ):
                with self.subTest(action=action):
                    result = self.host.manage_profile(
                        FrontendProfileChange(action, 'standby', 'active', new_name)
                    )
                    self.assertFalse(result.success)
        self.assertTrue(ProfileManager('standby').exists())

    def test_invalid_names_never_reach_profile_lifecycle(self) -> None:
        """Rejects path-like names instead of silently normalizing a different target.

        Args:
            None
        Returns:
            None
        """
        for value in ('', '../standby', '/tmp/standby', 'stand by'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    FrontendProfileChange(FrontendProfileAction.REMOVE, value, 'active')
                with self.assertRaises(FrontendBootstrapError):
                    self.host.select_profile(value)
                with patch.object(ProfileManager, 'add_profile_folder') as create:
                    secret = OneUseSecretProvider('one-use')
                    result = self.host.create_profile_entry(
                        FrontendProfileCreateRequest(value), secret
                    )
                    self.assertFalse(result.success)
                    self.assertIsNone(secret.take())
                    create.assert_not_called()
        self.assertEqual(self.host.profile_state().profile, 'active')


class GuiProfileCatalogTests(unittest.TestCase):
    """Exercises the GUI host boundary with actual temporary catalogs and lost responses."""

    def setUp(self) -> None:
        """Creates isolated host state and an authorized GUI catalog projection.

        Args:
            None
        Returns:
            None
        """
        self.host_tests = ProfileHostTests()
        self.host_tests.setUp()
        self.addCleanup(self.host_tests.doCleanups)
        self.gui = GuiController(FrontendLaunchContext('active', self.host_tests.host))
        self.addCleanup(self.gui.close)
        self.gui.state.covered = False
        self.gui.state.route = Route('V20')

    def settle(self) -> None:
        """Drains finite catalog reads and operation results through the real mailbox.

        Args:
            None
        Returns:
            None
        """
        for _ in range(10):
            self.gui.poll()
            if self.gui._worker is not None:
                self.gui._worker.join(2)
            self.gui.poll()
            if not self.gui.state.busy:
                return
        self.fail('Catalog operation did not settle')

    def test_unknown_actual_rename_requires_readback_before_another_mutation(
        self,
    ) -> None:
        """A lost host result cannot repeat a completed rename against a changed catalog.

        Args:
            None
        Returns:
            None
        """
        self.gui.profiles.reload()
        self.settle()
        self.assertEqual(self.gui.profiles.page.selected_profile, 'active')
        host = self.host_tests.host
        original = host.manage_profile
        change = FrontendProfileChange(
            FrontendProfileAction.RENAME, 'standby', 'active', 'renamed'
        )

        def lost_result(value: FrontendProfileChange) -> None:
            """Runs the actual host mutation before hiding its result.

            Args:
                value: Exact original profile mutation.
            Returns:
                None
            """
            self.assertTrue(original(value).success)
            raise OSError('Lost host response')

        with patch.object(host, 'manage_profile', side_effect=lost_result) as mutate:
            self.assertTrue(self.gui.profiles.change(change))
            self.settle()
            self.assertTrue(self.gui.profiles.unknown)
            self.assertFalse(self.gui.profiles.change(change))
            mutate.assert_called_once_with(change)
        self.gui.profiles.reload()
        self.settle()
        self.assertFalse(self.gui.profiles.unknown)
        names = [entry.profile for entry in self.gui.profiles.page.entries]
        self.assertIn('renamed', names)
        self.assertNotIn('standby', names)
        self.assertEqual(host.profile_state().profile, 'active')

    def test_startup_selection_uses_host_worker_without_starting_runtime(self) -> None:
        """Startup selection is distinct from an active runtime switch and stays bounded.

        Args:
            None
        Returns:
            None
        """
        self.gui.state.covered = True
        self.gui.state.route = Route('V02')
        self.assertTrue(self.gui.profiles.select('standby'))
        self.settle()
        self.assertEqual(self.gui.state.route, Route('V01'))
        self.assertTrue(self.gui.state.covered)
        self.assertIsNone(self.gui.client)
        self.assertEqual(self.host_tests.host.profile_state().profile, 'standby')
        self.assertFalse(self.host_tests.host.profile_state().daemon_running)

    def test_covered_late_catalog_cannot_repopulate_private_names(self) -> None:
        """A same-generation pre-lock catalog response requires a new authorized read.

        Args:
            None
        Returns:
            None
        """
        page = self.host_tests.host.profile_catalog()
        self.gui.state.covered = True
        self.gui.state.route = Route('V05')
        self.assertTrue(
            self.gui.profiles.install(
                Update(self.gui.state.generation, 'profiles:page', profile_catalog=page)
            )
        )
        self.assertIsNone(self.gui.profiles.page)
