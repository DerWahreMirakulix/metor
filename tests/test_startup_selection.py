"""Disposable profile-selection and first-run frontend regression tests."""

import threading
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from metor.application import create_local_frontend_host
from metor.client import (
    FrontendBootstrapError,
    FrontendLaunchContext,
    FrontendSelectionKind,
    LoadedFrontend,
)
from metor.cli.entry import run_cli
from metor.data import ProfileManager, SettingKey, Settings
from metor.data.profile.catalog import resolve_initial_profile, set_default_profile
from metor.ui.gui.runtime import GuiController
from metor.utils import Constants, FileLock


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

    def test_selection_metadata_preserves_request_origin(self) -> None:
        """Separate explicit requests from default and later host selection.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('alpha', 44112)
        implicit = create_local_frontend_host()
        selection = implicit.initial_selection()
        self.assertEqual(selection.kind, FrontendSelectionKind.RESOLVED)
        self.assertIsNone(selection.requested)
        self.assertEqual((selection.profile, selection.default), ('alpha', 'alpha'))
        explicit = create_local_frontend_host('alpha')
        self.assertEqual(explicit.initial_selection().requested, 'alpha')
        direct = create_local_frontend_host(ProfileManager('alpha'))
        self.assertEqual(direct.initial_selection().requested, 'alpha')
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'alpha')

    def test_implicit_catalog_failure_reaches_gui_selection(self) -> None:
        """An early catalog I/O failure remains a graphical unavailable state.

        Args:
            None
        Returns:
            None
        """
        with patch(
            'metor.application.frontend.host.resolve_initial_profile',
            side_effect=OSError('credential=private'),
        ):
            host = create_local_frontend_host()
        selection = host.initial_selection()
        self.assertEqual(selection.kind, FrontendSelectionKind.UNAVAILABLE)
        self.assertIsNone(selection.requested)
        with patch.object(
            host, 'list_profiles', side_effect=AssertionError('unbounded')
        ):
            controller = GuiController(FrontendLaunchContext(None, host))
        self.assertEqual(controller.state.route.view, 'V02')
        self.assertIn('unavailable', controller.state.status)

    def test_repair_holds_catalog_lock_until_default_is_written(self) -> None:
        """A rename cannot enter between singleton inspection and settings repair.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('alpha', 44108)
        Settings.set(SettingKey.DEFAULT_PROFILE, 'stale')
        entered = threading.Event()
        resume = threading.Event()
        original_set = Settings.set

        def delayed_set(
            key: SettingKey, value: str, *, expected_value: str | None = None
        ) -> None:
            """Pause only the resolver at its real settings write boundary.

            Args:
                key: Settings key.
                value: New setting.
                expected_value: Compare-and-swap value.
            Returns:
                None
            """
            if threading.current_thread().name.startswith('resolver'):
                entered.set()
                self.assertTrue(resume.wait(5))
            original_set(key, value, expected_value=expected_value)

        with patch.object(Settings, 'set', side_effect=delayed_set):
            with ThreadPoolExecutor(
                max_workers=2, thread_name_prefix='resolver'
            ) as pool:
                resolution = pool.submit(resolve_initial_profile)
                self.assertTrue(entered.wait(5))
                renamed = pool.submit(
                    ProfileManager.rename_profile_folder, 'alpha', 'beta'
                )
                self.assertFalse(renamed.done())
                resume.set()
                self.assertEqual(resolution.result(), 'alpha')
                self.assertTrue(renamed.result().success)
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'beta')
        self.assertEqual(resolve_initial_profile(), 'beta')

    def _race_repair_with_mutation(
        self, mutate: Callable[[], object], expected_default: str
    ) -> None:
        """Hold singleton repair while one mutation reaches the same lock.

        Args:
            mutate: Catalog operation to run after the resolver reaches settings.
            expected_default: Final persisted default.
        Returns:
            None
        """
        self._add_remote('alpha', 44113)
        Settings.set(SettingKey.DEFAULT_PROFILE, 'stale')
        repairing = threading.Event()
        release = threading.Event()
        mutation_at_lock = threading.Event()
        original_set = Settings.set
        original_enter = FileLock.__enter__

        def delayed_set(
            key: SettingKey, value: str, *, expected_value: str | None = None
        ) -> None:
            """Hold only the real resolver's settings write.

            Args:
                key: Settings key.
                value: New default.
                expected_value: Compare-and-swap expected default.
            Returns:
                None
            """
            if threading.current_thread().name.startswith('resolver'):
                repairing.set()
                self.assertTrue(release.wait(5))
            original_set(key, value, expected_value=expected_value)

        def observed_enter(lock: FileLock) -> FileLock:
            """Signal the competing thread's actual catalog-lock attempt.

            Args:
                lock: Acquiring file lock.
            Returns:
                FileLock: Acquired lock.
            """
            if threading.current_thread().name.startswith(
                'mutator'
            ) and '.profile-catalog.lock' in str(lock.lock_path):
                mutation_at_lock.set()
            return original_enter(lock)

        with (
            patch.object(Settings, 'set', side_effect=delayed_set),
            patch.object(FileLock, '__enter__', observed_enter),
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix='resolver'
            ) as resolver,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix='mutator') as mutator,
        ):
            future = resolver.submit(resolve_initial_profile)
            try:
                self.assertTrue(repairing.wait(5))
                mutation = mutator.submit(mutate)
                self.assertTrue(mutation_at_lock.wait(5))
                self.assertFalse(mutation.done())
            finally:
                release.set()
            self.assertEqual(future.result(), 'alpha')
            self.assertTrue(getattr(mutation.result(), 'success'))
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), expected_default)

    def test_repair_serializes_remove(self) -> None:
        """Removal cannot slip between singleton inspection and repair.

        Args:
            None
        Returns:
            None
        """
        self._race_repair_with_mutation(
            lambda: ProfileManager.remove_profile_folder('alpha'), ''
        )

    def test_repair_serializes_second_creation(self) -> None:
        """A second creation cannot redirect the pending singleton repair.

        Args:
            None
        Returns:
            None
        """
        self._race_repair_with_mutation(
            lambda: ProfileManager.add_profile_folder(
                'beta', is_remote=True, port=44114
            ),
            'alpha',
        )

    def test_resolution_serializes_explicit_default_choice(self) -> None:
        """An intentional new default wins after an in-flight catalog resolution.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('alpha', 44115)
        self._add_remote('beta', 44116)
        entered = threading.Event()
        release = threading.Event()
        at_lock = threading.Event()
        original_load = Settings.get_str
        original_enter = FileLock.__enter__

        def delayed_load(key: SettingKey, *args: object, **kwargs: object) -> str:
            """Hold the resolver while it owns the catalog lock.

            Args:
                key: Requested setting.
                *args: Existing settings options.
                **kwargs: Existing settings options.
            Returns:
                str: Current setting.
            """
            if (
                key is SettingKey.DEFAULT_PROFILE
                and threading.current_thread().name.startswith('resolver')
            ):
                entered.set()
                self.assertTrue(release.wait(5))
            return original_load(key, *args, **kwargs)

        def observed_enter(lock: FileLock) -> FileLock:
            """Signal the explicit default operation at its lock boundary.

            Args:
                lock: Acquiring file lock.
            Returns:
                FileLock: Acquired lock.
            """
            if threading.current_thread().name.startswith('mutator'):
                at_lock.set()
            return original_enter(lock)

        with (
            patch.object(Settings, 'get_str', side_effect=delayed_load),
            patch.object(FileLock, '__enter__', observed_enter),
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix='resolver'
            ) as resolver,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix='mutator') as mutator,
        ):
            resolved = resolver.submit(resolve_initial_profile)
            try:
                self.assertTrue(entered.wait(5))
                choice = mutator.submit(set_default_profile, 'beta')
                self.assertTrue(at_lock.wait(5))
                self.assertFalse(choice.done())
            finally:
                release.set()
            self.assertEqual(resolved.result(), 'alpha')
            self.assertTrue(choice.result().success)
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'beta')

    def test_neutral_frontend_selects_via_host_without_cli_exception(self) -> None:
        """A third frontend can implement a picker using the ordinary launch host.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('alpha', 44109)
        self._add_remote('beta', 44110)
        Settings.set(SettingKey.DEFAULT_PROFILE, '')
        observed: list[FrontendSelectionKind] = []

        def picker(context: FrontendLaunchContext) -> int:
            """Select and revalidate a catalog entry with the common host.

            Args:
                context: Shared launch contract.
            Returns:
                int: Successful test frontend exit.
            """
            observed.append(context.host.initial_selection().kind)
            context.host.select_profile('beta')
            self.assertEqual(context.host.initial_selection().profile, 'beta')
            return 0

        frontend = LoadedFrontend(Mock(frontend_id='other'), picker)
        with (
            patch('metor.cli.entry.initialize_runtime_environment'),
            patch('metor.cli.entry.load_frontend', return_value=frontend),
        ):
            self.assertEqual(run_cli(['chat', '--ui', 'other']), 0)
        self.assertEqual(observed, [FrontendSelectionKind.CHOICE_REQUIRED])
        self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), '')

    def test_close_racing_bootstrap_fences_late_result(self) -> None:
        """Closing during endpoint resolution rejects activation and future selection.

        Args:
            None
        Returns:
            None
        """
        self._add_remote('alpha', 44111)
        host = create_local_frontend_host('alpha')
        entered = threading.Event()
        resume = threading.Event()

        def port(_manager: ProfileManager) -> int:
            """Pause the real host at its endpoint boundary.

            Args:
                _manager: Selected temporary remote profile.
            Returns:
                int: Fixture port.
            """
            entered.set()
            self.assertTrue(resume.wait(5))
            return 44111

        with patch.object(ProfileManager, 'get_daemon_port', port):
            with ThreadPoolExecutor(max_workers=2) as pool:
                bootstrap = pool.submit(host.bootstrap, Mock())
                self.assertTrue(entered.wait(5))
                closing = pool.submit(host.close)
                self.assertTrue(host._closed.wait(5))
                resume.set()
                with self.assertRaises(FrontendBootstrapError):
                    bootstrap.result()
                closing.result()
        with self.assertRaises(FrontendBootstrapError):
            host.select_profile('alpha')
