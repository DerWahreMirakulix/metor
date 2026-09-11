"""Regression tests for release-critical CLI wiring and SQL backend selection."""

# ruff: noqa: E402

import argparse
import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Sequence, cast
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.release_bundle import (
    PIP_VERSION,
    build_bundle_name,
    clean_packaging_artifacts,
    build_install_guide,
    build_release_wheelhouse,
    build_install_shell_script,
    build_install_windows_script,
)
from metor.data.profile import (
    ProfileManager,
)
from metor.data.profile.config import Config
from metor.data.profile.models import ProfileSecurityMode
from metor.data.sql import SqlCipherDbApi, _load_sqlcipher_dbapi
from metor.data.sql.schema import create_core_schema
from metor.data.settings import Settings, SettingKey
from metor.cli.dispatcher import CliDispatcher
from metor.cli.proxy import CliProxy


class _DummyProfileManager:
    """
    Provides a dummy profile manager test double.
    """

    def is_remote(self) -> bool:
        """
        Reports whether the helper is remote.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


class _DummyUiConfig:
    """
    Provides a dummy UI config test double.
    """

    def __init__(self, value: str) -> None:
        """
        Initializes the dummy UI config helper.

        Args:
            value (str): The value.

        Returns:
            None
        """

        self._value: str = value

    def get_str(self, _key: object) -> str:
        """
        Returns str for the test scenario.

        Args:
            _key (object): The key.

        Returns:
            str: The computed return value.
        """

        return self._value


class _DummyUiProfileManager:
    """
    Provides a dummy UI profile manager test double.
    """

    def __init__(self, value: str) -> None:
        """
        Initializes the dummy UI profile manager helper.

        Args:
            value (str): The value.

        Returns:
            None
        """

        self.config: _DummyUiConfig = _DummyUiConfig(value)
        self.profile_name: str = 'default'

    def is_remote(self) -> bool:
        """
        Reports whether the helper is remote.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


class _FakeSqlCipherModule:
    """
    Provides a fake SQL cipher module test double.
    """

    class Connection:
        """
        Provides a connection helper for test scenarios.
        """

        pass

    class Cursor:
        """
        Provides a cursor helper for test scenarios.
        """

        pass

    class DatabaseError(Exception):
        """
        Provides a database error helper for test scenarios.
        """

        pass

    class OperationalError(Exception):
        """
        Provides a operational error helper for test scenarios.
        """

        pass


class _RecordingCursor:
    """
    Provides a recording cursor test double.
    """

    def __init__(self) -> None:
        """
        Initializes the recording cursor helper.

        Args:
            None

        Returns:
            None
        """

        self.queries: list[str] = []

    def execute(
        self, query: str, _params: tuple[object, ...] = ()
    ) -> '_RecordingCursor':
        """
        Executes execute for the test scenario.

        Args:
            query (str): The query.
            _params (tuple[object, ...]): The params.

        Returns:
            '_RecordingCursor': The computed return value.
        """

        self.queries.append(query)
        return self

    def fetchone(self) -> object:
        """
        Returns one row for the test scenario.

        Args:
            None

        Returns:
            object: The computed return value.
        """

        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        """
        Returns all rows for the test scenario.

        Args:
            None

        Returns:
            list[tuple[object, ...]]: The computed return value.
        """

        return []


def _raise_system_exit(code: int) -> None:
    """
    Raises SystemExit like the real sys.exit for patched exit points.

    Args:
        code (int): The process exit code.

    Returns:
        None
    """
    raise SystemExit(code)


class ReleaseContractTests(unittest.TestCase):
    """
    Covers release contract regression scenarios.
    """

    def _build_args(
        self,
        *,
        plaintext: bool = False,
        remote: bool = False,
        port: int | None = None,
        locked: bool = False,
    ) -> argparse.Namespace:
        """
        Builds args for the surrounding tests.

        Args:
            plaintext (bool): The plaintext.
            remote (bool): The remote.
            port (int | None): The port.
            locked (bool): The locked.

        Returns:
            argparse.Namespace: The computed return value.
        """

        return argparse.Namespace(
            command='profiles',
            subcommand='add',
            profile='default',
            remote=remote,
            port=port,
            locked=locked,
            plaintext=plaintext,
        )

    def test_profiles_add_maps_plaintext_flag_to_plaintext_security_mode(self) -> None:
        """
        Verifies that profiles add maps plaintext flag to plaintext security mode.

        Args:
            None

        Returns:
            None
        """

        dispatcher = CliDispatcher(
            self._build_args(plaintext=True),
            ['alice'],
            cast(ProfileManager, _DummyProfileManager()),
        )

        with (
            patch(
                'metor.cli.dispatcher.profiles.CliProxy.add_profile',
                return_value='ok',
            ) as add_profile,
            patch('builtins.print'),
        ):
            dispatcher.dispatch()

        self.assertIs(
            add_profile.call_args.kwargs['security_mode'],
            ProfileSecurityMode.PLAINTEXT,
        )

    def test_profiles_add_defaults_to_encrypted_security_mode(self) -> None:
        """
        Verifies that profiles add defaults to encrypted security mode.

        Args:
            None

        Returns:
            None
        """

        dispatcher = CliDispatcher(
            self._build_args(),
            ['alice'],
            cast(ProfileManager, _DummyProfileManager()),
        )

        with (
            patch(
                'metor.cli.dispatcher.profiles.CliProxy.add_profile',
                return_value='ok',
            ) as add_profile,
            patch('builtins.print'),
            patch('getpass.getpass', side_effect=['test-pw-123', 'test-pw-123']),
        ):
            dispatcher.dispatch()

        self.assertIs(
            add_profile.call_args.kwargs['security_mode'],
            ProfileSecurityMode.ENCRYPTED,
        )
        self.assertEqual(
            add_profile.call_args.kwargs['master_password'],
            'test-pw-123',
        )

    def test_require_local_auth_defaults_to_enabled(self) -> None:
        """
        Verifies that require local auth defaults to enabled.

        Args:
            None

        Returns:
            None
        """

        spec = Settings.SETTING_SPECS[SettingKey.REQUIRE_LOCAL_AUTH]

        self.assertTrue(spec.default)

    def test_local_auth_failure_limit_defaults_to_existing_threshold(self) -> None:
        """
        Verifies that local auth failure limit defaults to the existing threshold.

        Args:
            None

        Returns:
            None
        """

        spec = Settings.SETTING_SPECS[SettingKey.LOCAL_AUTH_FAILURE_LIMIT]

        self.assertEqual(spec.default, 3)

    def test_settings_defaults_to_list_when_no_subcommand_is_given(self) -> None:
        """
        Verifies that bare settings dispatches to the list action.

        Args:
            None

        Returns:
            None
        """

        dispatcher = CliDispatcher(
            argparse.Namespace(
                command='settings',
                subcommand=None,
                profile='default',
                remote=False,
                port=None,
                locked=False,
                plaintext=False,
            ),
            [],
            cast(ProfileManager, _DummyProfileManager()),
        )

        with (
            patch(
                'metor.cli.dispatcher.base.CliProxy.handle_settings_list',
                return_value='settings-list',
            ) as handle_settings_list,
            patch('builtins.print') as print_mock,
        ):
            dispatcher.dispatch()

        handle_settings_list.assert_called_once_with()
        print_mock.assert_called_once_with('settings-list')

    def test_chat_dispatch_passes_start_daemon_override(self) -> None:
        """
        Verifies that chat dispatch forwards the one-shot daemon-start override.

        Args:
            None

        Returns:
            None
        """

        pm = cast(ProfileManager, _DummyProfileManager())
        dispatcher = CliDispatcher(
            argparse.Namespace(
                command='chat',
                subcommand=None,
                profile='default',
                remote=False,
                port=None,
                locked=False,
                plaintext=False,
                start_daemon=True,
            ),
            [],
            pm,
        )

        with patch(
            'metor.cli.dispatcher.base.CommandHandlers.handle_chat'
        ) as handle_chat:
            dispatcher.dispatch()

        handle_chat.assert_called_once_with(
            pm,
            start_daemon_override=True,
            frontend_id=None,
            list_uis=False,
        )

    def test_config_defaults_to_list_when_no_subcommand_is_given(self) -> None:
        """
        Verifies that bare config dispatches to the list action.

        Args:
            None

        Returns:
            None
        """

        dispatcher = CliDispatcher(
            argparse.Namespace(
                command='config',
                subcommand=None,
                profile='default',
                remote=False,
                port=None,
                locked=False,
                plaintext=False,
            ),
            [],
            cast(ProfileManager, _DummyProfileManager()),
        )

        with (
            patch(
                'metor.cli.dispatcher.base.CliProxy.handle_config_list',
                return_value='config-list',
            ) as handle_config_list,
            patch('builtins.print') as print_mock,
        ):
            dispatcher.dispatch()

        handle_config_list.assert_called_once_with()
        print_mock.assert_called_once_with('config-list')

    def test_plaintext_profiles_no_longer_force_disable_local_auth(self) -> None:
        """
        Verifies that plaintext profiles no longer force disable local auth.

        Args:
            None

        Returns:
            None
        """

        self.assertNotIn(
            SettingKey.REQUIRE_LOCAL_AUTH,
            Config._PLAINTEXT_DISABLED_SETTING_KEYS,
        )

    def test_schema_bootstrap_does_not_drop_legacy_tables(self) -> None:
        """
        Verifies that schema bootstrap does not drop legacy tables.

        Args:
            None

        Returns:
            None
        """

        cursor = _RecordingCursor()

        create_core_schema(cursor)

        self.assertFalse(
            any('DROP TABLE IF EXISTS' in query for query in cursor.queries)
        )

    def test_local_auth_lockout_timeout_has_secure_default(self) -> None:
        """
        Verifies that local auth lockout timeout has secure default.

        Args:
            None

        Returns:
            None
        """

        spec = Settings.SETTING_SPECS[SettingKey.LOCAL_AUTH_LOCKOUT_TIMEOUT]

        self.assertEqual(spec.default, 30.0)

    def test_max_unseen_drop_msgs_has_bounded_default(self) -> None:
        """
        Verifies that max unseen drop msgs has bounded default.

        Args:
            None

        Returns:
            None
        """

        spec = Settings.SETTING_SPECS[SettingKey.MAX_UNSEEN_DROP_MSGS]

        self.assertEqual(spec.default, 20)

    def test_max_ipc_clients_has_bounded_default(self) -> None:
        """
        Verifies that max IPC clients has bounded default.

        Args:
            None

        Returns:
            None
        """

        spec = Settings.SETTING_SPECS[SettingKey.MAX_IPC_CLIENTS]

        self.assertEqual(spec.default, 8)

    def test_ui_settings_get_uses_global_settings_value(self) -> None:
        """
        Verifies that UI settings get uses global settings value.

        Args:
            None

        Returns:
            None
        """

        proxy = CliProxy(cast(ProfileManager, _DummyUiProfileManager('9.5')))

        with patch(
            'metor.cli.proxy.settings.Settings.get_str',
            return_value='7.5',
        ):
            result = proxy.handle_settings_get(SettingKey.IPC_TIMEOUT.value)

        self.assertIn('Global Setting', result)
        self.assertIn('7.5', result)

    def test_ui_config_get_uses_effective_profile_config_value(self) -> None:
        """
        Verifies that UI config get uses effective profile config value.

        Args:
            None

        Returns:
            None
        """

        proxy = CliProxy(cast(ProfileManager, _DummyUiProfileManager('9.5')))

        result = proxy.handle_config_get(SettingKey.IPC_TIMEOUT.value)

        self.assertIn('Profile Config', result)
        self.assertIn('9.5', result)

    def test_release_bundle_name_normalizes_windows_host_labels(self) -> None:
        """
        Verifies that release bundle name normalizes windows host labels.

        Args:
            None

        Returns:
            None
        """

        bundle_name = build_bundle_name('Windows', 'AMD64', 3, 11)

        self.assertEqual(bundle_name, 'metor-wheelhouse-windows-x86_64-py311')

    def test_release_bundle_name_supports_terminal_and_sdk_variants(self) -> None:
        """
        Verifies that release bundle names distinguish daemon and SDK variants.

        Args:
            None

        Returns:
            None
        """
        terminal_bundle = build_bundle_name(
            'Linux', 'x86_64', 3, 11, variant='terminal'
        )
        sdk_bundle = build_bundle_name('Linux', 'x86_64', 3, 11, variant='sdk')

        self.assertEqual(
            terminal_bundle,
            'metor-ui-terminal-wheelhouse-linux-x86_64-py311',
        )
        self.assertEqual(sdk_bundle, 'metor-sdk-wheelhouse-linux-x86_64-py311')

    def test_release_install_guide_uses_offline_bundle_install(self) -> None:
        """
        Verifies that release install guide uses offline bundle install.

        Args:
            None

        Returns:
            None
        """

        guide = build_install_guide('metor-wheelhouse-linux-x86_64-py311')

        self.assertIn('sh install.sh', guide)
        self.assertIn('install.cmd', guide)
        self.assertIn(
            '--no-index --find-links wheelhouse --upgrade pip==26.0.1',
            guide,
        )
        self.assertIn('requires no package index access', guide)

    def test_release_shell_installer_uses_local_wheelhouse(self) -> None:
        """
        Verifies that release shell installer uses local wheelhouse.

        Args:
            None

        Returns:
            None
        """

        script = build_install_shell_script()

        self.assertIn('python3 python', script)
        self.assertIn(
            'sys.version_info >= (3, 11)',
            script,
        )
        self.assertIn(
            '--no-index --find-links "$script_dir/wheelhouse" --upgrade pip==26.0.1',
            script,
        )
        self.assertIn('--no-index --find-links "$script_dir/wheelhouse" metor', script)
        self.assertIn('$venv_dir/bin/metor --help', script)

    def test_release_windows_installer_uses_local_wheelhouse(self) -> None:
        """
        Verifies that release windows installer uses local wheelhouse.

        Args:
            None

        Returns:
            None
        """

        script = build_install_windows_script()

        self.assertIn(
            'VERSION_CHECK=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)',
            script,
        )
        self.assertIn('py -3.11 -m venv', script)
        self.assertIn(
            '--no-index --find-links "%SCRIPT_DIR%wheelhouse" --upgrade pip==26.0.1',
            script,
        )
        self.assertIn('--no-index --find-links "%SCRIPT_DIR%wheelhouse" metor', script)
        self.assertIn('Scripts\\metor.exe --help', script)

    def test_release_builder_downloads_pip_wheel_for_offline_installs(self) -> None:
        """
        Verifies that release builder downloads pip wheel for offline installs.

        Args:
            None

        Returns:
            None
        """

        commands: list[list[str]] = []

        def fake_run_command(command: Sequence[str], cwd: Path) -> None:
            """
            Executes fake run command for the test scenario.

            Args:
                command (Sequence[str]): The command.
                cwd (Path): The cwd.

            Returns:
                None
            """

            del cwd
            commands.append(list(command))

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with (
                patch(
                    'metor.utils.release_bundle.run_command',
                    side_effect=fake_run_command,
                ),
                patch(
                    'metor.utils.release_bundle.archive_bundle',
                    return_value=output_dir / 'bundle.zip',
                ),
            ):
                build_release_wheelhouse(output_dir, skip_pip_upgrade=True)

        self.assertTrue(
            any(
                command[:4] == [sys.executable, '-m', 'pip', 'download']
                and '--only-binary=:all:' in command
                and f'pip=={PIP_VERSION}' in command
                for command in commands
            )
        )

    def test_release_builder_supports_sdk_and_terminal_variants(self) -> None:
        """
        Verifies that release builder targets variant-specific lockfiles and packages.

        Args:
            None

        Returns:
            None
        """
        commands_sdk: list[list[str]] = []
        commands_terminal: list[list[str]] = []

        def fake_run_sdk(command: Sequence[str], cwd: Path) -> None:
            """
            Records fake commands executed for the SDK variant.

            Args:
                command (Sequence[str]): The executed command.
                cwd (Path): Working directory.

            Returns:
                None
            """
            del cwd
            commands_sdk.append(list(command))

        def fake_run_terminal(command: Sequence[str], cwd: Path) -> None:
            """
            Records fake commands executed for the Daemon variant.

            Args:
                command (Sequence[str]): The executed command.
                cwd (Path): Working directory.

            Returns:
                None
            """
            del cwd
            commands_terminal.append(list(command))

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with (
                patch(
                    'metor.utils.release_bundle.run_command',
                    side_effect=fake_run_sdk,
                ),
                patch(
                    'metor.utils.release_bundle.archive_bundle',
                    return_value=output_dir / 'bundle.zip',
                ),
            ):
                build_release_wheelhouse(
                    output_dir, skip_pip_upgrade=True, variant='sdk'
                )

            with (
                patch(
                    'metor.utils.release_bundle.run_command',
                    side_effect=fake_run_terminal,
                ),
                patch(
                    'metor.utils.release_bundle.archive_bundle',
                    return_value=output_dir / 'bundle.zip',
                ),
            ):
                build_release_wheelhouse(
                    output_dir, skip_pip_upgrade=True, variant='terminal'
                )

        self.assertTrue(
            any(
                'requirements/sdk.lock' in command and 'wheel' in command
                for command in commands_sdk
            )
        )
        self.assertTrue(
            any(
                'packaging/sdk' in command and 'wheel' in command
                for command in commands_sdk
            )
        )
        self.assertTrue(
            any(
                'requirements/base.lock' in command and 'wheel' in command
                for command in commands_terminal
            )
        )
        self.assertTrue(
            any(
                'packaging/terminal' in command and 'wheel' in command
                for command in commands_terminal
            )
        )

    def test_project_wheel_uses_terminal_frontend_package(self) -> None:
        """
        Verifies that the wheel contains only the canonical terminal CLI path.

        Args:
            None

        Returns:
            None
        """

        repo_root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            clean_packaging_artifacts(repo_root)
            subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'pip',
                    'wheel',
                    '.',
                    '--no-deps',
                    '--no-build-isolation',
                    '-w',
                    str(output_dir),
                ],
                check=True,
                cwd=repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            wheel_files = sorted(output_dir.glob('metor-*.whl'))

            self.assertEqual(len(wheel_files), 1)

            with ZipFile(wheel_files[0]) as wheel_archive:
                archive_names = set(wheel_archive.namelist())

            self.assertIn('metor/cli/proxy/core.py', archive_names)
            self.assertNotIn('metor/ui/terminal/help.py', archive_names)

    def test_terminal_wheel_contains_only_interactive_frontend(self) -> None:
        """Verifies the Terminal wheel owns its UI and not base runtime modules.

        Args:
            None

        Returns:
            None
        """
        repo_root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            clean_packaging_artifacts(repo_root)
            subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'pip',
                    'wheel',
                    'packaging/terminal',
                    '--no-deps',
                    '--no-build-isolation',
                    '-w',
                    str(output_dir),
                ],
                check=True,
                cwd=repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wheel_files = sorted(output_dir.glob('metor_ui_terminal-*.whl'))
            self.assertEqual(len(wheel_files), 1)
            with ZipFile(wheel_files[0]) as wheel_archive:
                archive_names = set(wheel_archive.namelist())

            self.assertIn('metor/ui/terminal/launcher.py', archive_names)
            self.assertIn('metor/ui/terminal/help.py', archive_names)
            self.assertNotIn('metor/core/profile_keys.py', archive_names)
            self.assertNotIn('metor/data/blob/store.py', archive_names)

    def test_release_bundle_import_avoids_optional_runtime_utils_dependencies(
        self,
    ) -> None:
        """
        Verifies that release bundle import avoids optional runtime utils dependencies.

        Args:
            None

        Returns:
            None
        """

        module_names: tuple[str, ...] = (
            'metor.utils.release_bundle',
            'metor.utils',
            'metor.utils.auth',
            'metor.utils.lock',
            'metor.utils.process',
        )
        saved_modules: dict[str, ModuleType] = {
            name: module
            for name in module_names
            if isinstance(sys.modules.get(name), ModuleType)
            for module in [sys.modules[name]]
        }
        imported_module: ModuleType | None = None

        for name in module_names:
            sys.modules.pop(name, None)

        original_import = __import__

        def guarded_import(
            name: str,
            globals_: dict[str, object] | None = None,
            locals_: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            """
            Executes guarded import for the test scenario.

            Args:
                name (str): The name.
                globals_ (dict[str, object] | None): The globals.
                locals_ (dict[str, object] | None): The locals.
                fromlist (tuple[str, ...]): The fromlist.
                level (int): The level.

            Returns:
                object: The computed return value.
            """

            if name in {
                'metor.utils.auth',
                'metor.utils.lock',
                'metor.utils.process',
                'psutil',
            } or name.startswith('nacl'):
                raise ImportError(f'blocked optional dependency import: {name}')

            return original_import(name, globals_, locals_, fromlist, level)

        try:
            with patch('builtins.__import__', side_effect=guarded_import):
                imported_module = importlib.import_module('metor.utils.release_bundle')
        finally:
            for name in module_names:
                sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                sys.modules[name] = module

        self.assertIsNotNone(imported_module)
        assert imported_module is not None
        self.assertTrue(hasattr(imported_module, 'build_release_wheelhouse'))

    def test_sqlcipher_loader_prefers_sqlcipher3(self) -> None:
        """
        Verifies that sqlcipher loader prefers sqlcipher3.

        Args:
            None

        Returns:
            None
        """

        def importer(module_name: str) -> SqlCipherDbApi:
            """
            Executes importer for the test scenario.

            Args:
                module_name (str): The module name.

            Returns:
                SqlCipherDbApi: The computed return value.
            """

            if module_name == 'sqlcipher3.dbapi2':
                return cast(SqlCipherDbApi, _FakeSqlCipherModule)
            raise AssertionError(f'Unexpected module lookup: {module_name}')

        module, backend = _load_sqlcipher_dbapi(importer)

        self.assertIs(module, _FakeSqlCipherModule)
        self.assertEqual(backend, 'sqlcipher3')

    def test_sqlcipher_loader_falls_back_to_pysqlcipher3(self) -> None:
        """
        Verifies that sqlcipher loader falls back to pysqlcipher3.

        Args:
            None

        Returns:
            None
        """

        def importer(module_name: str) -> SqlCipherDbApi:
            """
            Executes importer for the test scenario.

            Args:
                module_name (str): The module name.

            Returns:
                SqlCipherDbApi: The computed return value.
            """

            if module_name == 'sqlcipher3.dbapi2':
                raise ImportError('sqlcipher3 unavailable')
            if module_name == 'pysqlcipher3.dbapi2':
                return cast(SqlCipherDbApi, _FakeSqlCipherModule)
            raise AssertionError(f'Unexpected module lookup: {module_name}')

        module, backend = _load_sqlcipher_dbapi(importer)

        self.assertIs(module, _FakeSqlCipherModule)
        self.assertEqual(backend, 'pysqlcipher3')

    def test_sqlcipher_loader_raises_helpful_error_when_backends_missing(self) -> None:
        """
        Verifies that sqlcipher loader raises helpful error when backends missing.

        Args:
            None

        Returns:
            None
        """

        def importer(module_name: str) -> SqlCipherDbApi:
            """
            Executes importer for the test scenario.

            Args:
                module_name (str): The module name.

            Returns:
                SqlCipherDbApi: The computed return value.
            """

            raise ImportError(f'missing {module_name}')

        with self.assertRaises(ImportError) as ctx:
            _load_sqlcipher_dbapi(importer)

        message = str(ctx.exception)
        self.assertIn('sqlcipher3-binary on Linux', message)
        self.assertIn('sqlcipher3 on Windows', message)
        self.assertIn('pysqlcipher3', message)

    def test_unknown_command_exits_nonzero(self) -> None:
        """
        Verifies that an unknown CLI command exits with code 1.

        Regression guard: unknown commands printed a clean message but exited 0,
        breaking script error detection.

        Args:
            None

        Returns:
            None
        """
        args = self._build_args()
        args.command = 'gibtsnicht'
        args.subcommand = None
        dispatcher = CliDispatcher(
            args,
            [],
            cast(ProfileManager, _DummyProfileManager()),
        )
        with patch('builtins.print'):
            exit_code = dispatcher.dispatch()
        self.assertEqual(exit_code, 1)

    def test_send_without_arguments_exits_nonzero(self) -> None:
        """
        Verifies that usage errors exit with code 1.

        Args:
            None

        Returns:
            None
        """
        args = self._build_args()
        args.command = 'send'
        args.subcommand = None
        dispatcher = CliDispatcher(
            args,
            [],
            cast(ProfileManager, _DummyProfileManager()),
        )
        with patch('builtins.print'):
            exit_code = dispatcher.dispatch()
        self.assertEqual(exit_code, 1)

    def test_ui_flag_is_not_consumed_by_general_help(self) -> None:
        """
        Verifies that an unknown --ui frontend id exits with code 2.

        Args:
            None

        Returns:
            None
        """
        from metor.main import main as frontend_main

        with (
            patch('sys.argv', ['metor', 'help', '--ui', 'unbekannt']),
            patch('sys.stdout'),
            patch('sys.stderr'),
            patch('sys.exit', side_effect=_raise_system_exit),
        ):
            with self.assertRaises(SystemExit) as ctx:
                frontend_main()

        self.assertEqual(ctx.exception.code, 0)

    def test_daemon_main_unlock_guard_exits_with_code_1(self) -> None:
        """
        Verifies that metor-daemon unlock delegates to the terminal UI.

        Args:
            None

        Returns:
            None
        """
        from metor import daemon_main

        with (
            patch('sys.argv', ['metor-daemon', 'unlock']),
            patch('sys.stderr'),
            patch('sys.exit', side_effect=_raise_system_exit),
        ):
            with self.assertRaises(SystemExit) as ctx:
                daemon_main.main()

        self.assertEqual(ctx.exception.code, 1)

    def test_daemon_main_missing_profile_exits_with_code_1(self) -> None:
        """
        Verifies that metor-daemon rejects a non-existent profile cleanly.

        Regression guard: the encrypted-startup guard fired before the
        profile-existence check, producing a misleading error message.

        Args:
            None

        Returns:
            None
        """
        from metor import daemon_main

        with (
            patch(
                'metor.daemon_main.ProfileManager.load_default_profile',
                return_value='default',
            ),
            patch('sys.argv', ['metor-daemon', '-p', 'existiert-nicht', 'daemon']),
            patch('builtins.print') as print_mock,
            patch('sys.exit', side_effect=_raise_system_exit),
        ):
            with self.assertRaises(SystemExit) as ctx:
                daemon_main.main()

        self.assertEqual(ctx.exception.code, 1)
        printed = ' '.join(str(call) for call in print_mock.call_args_list)
        self.assertIn('does not exist', printed)

    def test_daemon_main_parser_parity_with_daemon_launch_command(self) -> None:
        """
        Verifies that daemon_main CLI parser supports all flags produced by daemon launch.

        Args:
            None

        Returns:
            None
        """
        from metor import daemon_main

        parser = daemon_main._build_parser()
        for start_locked in (True, False):
            for startup_session_auth_stdin in (True, False):
                argv: list[str] = ['-p', 'test_profile']
                if start_locked:
                    argv.append('--locked')
                if startup_session_auth_stdin:
                    argv.append('--startup-session-auth-stdin')
                argv.append('daemon')

                args = parser.parse_args(argv)
                self.assertEqual(args.profile, 'test_profile')
                self.assertEqual(args.locked, start_locked)
                self.assertEqual(
                    args.startup_session_auth_stdin, startup_session_auth_stdin
                )
                self.assertEqual(args.command, 'daemon')

    def test_messages_show_error_rendering_exits_nonzero(self) -> None:
        """
        Verifies that messages show consumes the proxy error flag via _emit.

        Regression guard: the messages mixin rendered proxy results with print,
        so rendered errors (e.g. 'Target not found') exited 0.

        Args:
            None

        Returns:
            None
        """
        args = self._build_args()
        args.command = 'messages'
        args.subcommand = 'show'
        dispatcher = CliDispatcher(
            args,
            ['nichtda'],
            cast(ProfileManager, _DummyProfileManager()),
        )
        with (
            patch.object(
                dispatcher._proxy,
                'get_messages',
                return_value="Target 'nichtda' not found.",
            ),
            patch.object(dispatcher._proxy, 'consume_error_flag', return_value=True),
            patch('builtins.print'),
        ):
            exit_code = dispatcher.dispatch()
        self.assertEqual(exit_code, 1)

    def test_history_show_error_rendering_exits_nonzero(self) -> None:
        """
        Verifies that history show consumes the proxy error flag via _emit.

        Args:
            None

        Returns:
            None
        """
        args = self._build_args()
        args.command = 'history'
        args.subcommand = 'show'
        dispatcher = CliDispatcher(
            args,
            ['nichtda'],
            cast(ProfileManager, _DummyProfileManager()),
        )
        with (
            patch.object(
                dispatcher._proxy,
                'get_history',
                return_value="Target 'nichtda' not found.",
            ),
            patch.object(dispatcher._proxy, 'consume_error_flag', return_value=True),
            patch('builtins.print'),
        ):
            exit_code = dispatcher.dispatch()
        self.assertEqual(exit_code, 1)


if __name__ == '__main__':
    unittest.main()
