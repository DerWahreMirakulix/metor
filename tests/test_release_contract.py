"""Regression tests for release-critical CLI wiring and SQL backend selection."""

# ruff: noqa: E402

import argparse
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.release_bundle import (
    PIP_VERSION,
    build_bundle_name,
    build_install_guide,
    build_release_wheelhouse,
    build_install_shell_script,
    build_install_windows_script,
)
from metor.data.profile import (
    ProfileManager,
    ProfileOperationResult,
    ProfileOperationType,
)
from metor.data.profile.models import ProfileSecurityMode
from metor.data.sql import SqlCipherDbApi, _load_sqlcipher_dbapi
from metor.data.settings import Settings, SettingKey
from metor.ui.cli.dispatcher import CliDispatcher


class _DummyProfileManager:
    def is_remote(self) -> bool:
        return False


class _FakeSqlCipherModule:
    class Connection:
        pass

    class Cursor:
        pass

    class DatabaseError(Exception):
        pass

    class OperationalError(Exception):
        pass


class ReleaseContractTests(unittest.TestCase):
    def _build_args(
        self,
        *,
        plaintext: bool = False,
        remote: bool = False,
        port: int | None = None,
        locked: bool = False,
    ) -> argparse.Namespace:
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
        dispatcher = CliDispatcher(
            self._build_args(plaintext=True),
            ['alice'],
            cast(ProfileManager, _DummyProfileManager()),
        )
        result = ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_CREATED,
            {'profile': 'alice', 'security_mode': ProfileSecurityMode.PLAINTEXT.value},
        )

        with (
            patch(
                'metor.ui.cli.dispatcher.base.ProfileManager.add_profile_folder',
                return_value=result,
            ) as add_profile,
            patch('builtins.print'),
        ):
            dispatcher.dispatch()

        self.assertIs(
            add_profile.call_args.kwargs['security_mode'],
            ProfileSecurityMode.PLAINTEXT,
        )

    def test_profiles_add_defaults_to_encrypted_security_mode(self) -> None:
        dispatcher = CliDispatcher(
            self._build_args(),
            ['alice'],
            cast(ProfileManager, _DummyProfileManager()),
        )
        result = ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_CREATED,
            {'profile': 'alice', 'security_mode': ProfileSecurityMode.ENCRYPTED.value},
        )

        with (
            patch(
                'metor.ui.cli.dispatcher.base.ProfileManager.add_profile_folder',
                return_value=result,
            ) as add_profile,
            patch('builtins.print'),
        ):
            dispatcher.dispatch()

        self.assertIs(
            add_profile.call_args.kwargs['security_mode'],
            ProfileSecurityMode.ENCRYPTED,
        )

    def test_require_local_auth_defaults_to_enabled(self) -> None:
        spec = Settings.SETTING_SPECS[SettingKey.REQUIRE_LOCAL_AUTH]

        self.assertTrue(spec.default)

    def test_local_auth_lockout_timeout_has_secure_default(self) -> None:
        spec = Settings.SETTING_SPECS[SettingKey.LOCAL_AUTH_LOCKOUT_TIMEOUT]

        self.assertEqual(spec.default, 30.0)

    def test_max_ipc_clients_has_bounded_default(self) -> None:
        spec = Settings.SETTING_SPECS[SettingKey.MAX_IPC_CLIENTS]

        self.assertEqual(spec.default, 8)

    def test_release_bundle_name_normalizes_windows_host_labels(self) -> None:
        bundle_name = build_bundle_name('Windows', 'AMD64', 3, 11)

        self.assertEqual(bundle_name, 'metor-wheelhouse-windows-x86_64-py311')

    def test_release_install_guide_uses_offline_bundle_install(self) -> None:
        guide = build_install_guide('metor-wheelhouse-linux-x86_64-py311')

        self.assertIn('sh install.sh', guide)
        self.assertIn('install.cmd', guide)
        self.assertIn(
            '--no-index --find-links wheelhouse --upgrade pip==26.0.1',
            guide,
        )
        self.assertIn('requires no package index access', guide)

    def test_release_shell_installer_uses_local_wheelhouse(self) -> None:
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
        commands: list[list[str]] = []

        def fake_run_command(command: Sequence[str], cwd: Path) -> None:
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

    def test_sqlcipher_loader_prefers_sqlcipher3(self) -> None:
        def importer(module_name: str) -> SqlCipherDbApi:
            if module_name == 'sqlcipher3.dbapi2':
                return cast(SqlCipherDbApi, _FakeSqlCipherModule)
            raise AssertionError(f'Unexpected module lookup: {module_name}')

        module, backend = _load_sqlcipher_dbapi(importer)

        self.assertIs(module, _FakeSqlCipherModule)
        self.assertEqual(backend, 'sqlcipher3')

    def test_sqlcipher_loader_falls_back_to_pysqlcipher3(self) -> None:
        def importer(module_name: str) -> SqlCipherDbApi:
            if module_name == 'sqlcipher3.dbapi2':
                raise ImportError('sqlcipher3 unavailable')
            if module_name == 'pysqlcipher3.dbapi2':
                return cast(SqlCipherDbApi, _FakeSqlCipherModule)
            raise AssertionError(f'Unexpected module lookup: {module_name}')

        module, backend = _load_sqlcipher_dbapi(importer)

        self.assertIs(module, _FakeSqlCipherModule)
        self.assertEqual(backend, 'pysqlcipher3')

    def test_sqlcipher_loader_raises_helpful_error_when_backends_missing(self) -> None:
        def importer(module_name: str) -> SqlCipherDbApi:
            raise ImportError(f'missing {module_name}')

        with self.assertRaises(ImportError) as ctx:
            _load_sqlcipher_dbapi(importer)

        message = str(ctx.exception)
        self.assertIn('sqlcipher3-binary on Linux', message)
        self.assertIn('sqlcipher3 on Windows', message)
        self.assertIn('pysqlcipher3', message)


if __name__ == '__main__':
    unittest.main()
