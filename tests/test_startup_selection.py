"""Disposable profile-selection and first-run frontend regression tests."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from metor.application import create_local_frontend_host
from metor.client import FrontendLaunchContext, LoadedFrontend
from metor.cli.entry import run_cli
from metor.data import ProfileManager, SettingKey, Settings
from metor.data.profile.catalog import resolve_initial_profile
from metor.ui.gui.runtime import GuiController
from metor.utils import Constants


class StartupSelectionTests(unittest.TestCase):
    """Use only temporary profile data; no daemon or physical device is started."""

    def setUp(self) -> None:
        """Select one isolated profile root for each test.

        Args:
            None
        Returns:
            None
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        data_patch = patch.object(Constants, 'DATA', self.root)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def _add_remote(self, name: str, port: int) -> None:
        """Add a disposable remote entry without Tor or microphone activity.

        Args:
            name: Local catalog name.
            port: Fixture endpoint number.
        Returns:
            None
        """
        result = ProfileManager.add_profile_folder(name, is_remote=True, port=port)
        self.assertTrue(result.success, result.operation_type.value)

    def test_empty_catalog_opens_graphical_creation_and_terminal_reports_it(
        self,
    ) -> None:
        """Empty GUI selection stays graphical and Terminal refuses pre-chat entry.

        Args:
            None
        Returns:
            None
        """
        self.assertIsNone(resolve_initial_profile())
        host = create_local_frontend_host(None)
        controller = GuiController(FrontendLaunchContext(None, host))
        self.assertEqual(controller.state.route.view, 'V03')
        self.assertEqual(controller.state.status, 'No profiles exist yet.')
        self.assertIsNone(host.profile_state())
        with (
            patch('metor.cli.entry.initialize_runtime_environment'),
            patch('sys.stderr.write') as write,
        ):
            status = run_cli(['chat', '--ui', 'terminal'])
        self.assertEqual(status, 1)
        self.assertIn('No profiles exist yet.', write.call_args.args[0])

    def test_first_success_and_final_removal_reconcile_default(self) -> None:
        """Failed creation preserves the default, and the survivor becomes it.

        Args:
            None
        Returns:
            None
        """
        failed = ProfileManager.add_profile_folder('broken')
        self.assertFalse(failed.success)
        self.assertIsNone(resolve_initial_profile())
        self._add_remote('alpha', 44101)
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'alpha')
        self._add_remote('beta', 44102)
        self.assertEqual(resolve_initial_profile(), 'alpha')
        renamed = ProfileManager.rename_profile_folder('alpha', 'gamma')
        self.assertTrue(renamed.success)
        self.assertEqual(resolve_initial_profile(), 'gamma')
        self.assertTrue(ProfileManager.remove_profile_folder('gamma').success)
        self.assertEqual(resolve_initial_profile(), 'beta')
        self.assertTrue(ProfileManager.remove_profile_folder('beta').success)
        self.assertIsNone(resolve_initial_profile())
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), '')

    def test_missing_explicit_profile_keeps_gui_picker_and_damaged_entry(self) -> None:
        """Valid missing and unsafe entries remain visible recovery states.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('healthy', 44103)
        missing = create_local_frontend_host('requested')
        controller = GuiController(FrontendLaunchContext('requested', missing))
        self.assertEqual(controller.state.route.view, 'V02')
        self.assertIn('requested', controller.state.status)
        self.assertEqual(resolve_initial_profile('requested'), 'requested')
        (self.root / 'damaged').symlink_to(
            self.root / 'healthy', target_is_directory=True
        )
        damaged = create_local_frontend_host('damaged')
        damaged_controller = GuiController(FrontendLaunchContext('damaged', damaged))
        self.assertEqual(damaged_controller.state.route.view, 'V02')
        self.assertIn('damaged', damaged_controller.state.status.lower())
        states = damaged.list_profiles()
        self.assertEqual({state.profile for state in states}, {'damaged', 'healthy'})
        self.assertIsNotNone(
            next(state.issue for state in states if state.profile == 'damaged')
        )

    def test_concurrent_first_creations_choose_one_persisted_default(self) -> None:
        """Cross-thread catalog serialization preserves one first-winner default.

        Args:
            None
        Returns:
            None
        """
        barrier = threading.Barrier(3)

        def create(name: str, port: int) -> bool:
            """Wait for a shared start and create one independent fixture entry.

            Args:
                name: Fixture profile name.
                port: Fixture endpoint number.
            Returns:
                bool: Whether creation succeeded.
            """
            barrier.wait()
            return ProfileManager.add_profile_folder(
                name, is_remote=True, port=port
            ).success

        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(create, 'left', 44104)
            right = executor.submit(create, 'right', 44105)
            barrier.wait()
            self.assertTrue(left.result())
            self.assertTrue(right.result())
        default = Settings.get_str(SettingKey.DEFAULT_PROFILE)
        self.assertIn(default, {'left', 'right'})
        self.assertEqual(resolve_initial_profile(), default)

    def test_shell_launched_gui_keeps_empty_and_missing_selection_graphical(
        self,
    ) -> None:
        """The CLI launches a usable GUI shell without terminal input or a daemon.

        Args:
            None
        Returns:
            None
        """
        seen: list[tuple[str | None, str]] = []

        def enter(context: FrontendLaunchContext) -> int:
            """Observe the actual common launch handoff and first GUI route.

            Args:
                context: Shared launch context after CLI parsing.
            Returns:
                int: Successful deliberate test close.
            """
            controller = GuiController(context)
            seen.append((context.profile, controller.state.route.view))
            return 0

        frontend = LoadedFrontend(Mock(frontend_id='gui'), enter)
        with (
            patch('metor.cli.entry.initialize_runtime_environment'),
            patch('metor.cli.entry.load_frontend', return_value=frontend),
            patch('builtins.input', side_effect=AssertionError('terminal input')),
            patch('getpass.getpass', side_effect=AssertionError('terminal password')),
        ):
            self.assertEqual(run_cli(['chat', '--ui', 'gui']), 0)
            self.assertEqual(run_cli(['chat', '--ui', 'gui', '-p', 'future']), 0)
        self.assertEqual(seen, [(None, 'V03'), ('future', 'V03')])

    def test_ambiguous_catalog_requires_selection_and_singleton_repairs_default(
        self,
    ) -> None:
        """An invalid default does not silently select from several profiles.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('first', 44106)
        self._add_remote('second', 44107)
        Settings.set(SettingKey.DEFAULT_PROFILE, '')
        self.assertIsNone(resolve_initial_profile())
        picker = GuiController(
            FrontendLaunchContext(None, create_local_frontend_host())
        )
        self.assertEqual(picker.state.route.view, 'V02')
        self.assertEqual(resolve_initial_profile('second'), 'second')
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), '')
        self.assertTrue(ProfileManager.remove_profile_folder('second').success)
        Settings.set(SettingKey.DEFAULT_PROFILE, 'stale')
        self.assertEqual(resolve_initial_profile(), 'first')
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'first')
