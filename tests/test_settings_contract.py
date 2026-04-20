"""Regression tests for the settings/config cascade and list contracts."""

# ruff: noqa: E402

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import EventType, GetSettingCommand
from metor.core.daemon.handlers import ConfigCommandHandler
from metor.data.profile import ProfileManager
from metor.data.profile.config import Config
from metor.data.settings import Settings, SettingKey
from metor.ui.cli.proxy.settings import CliProxySettingsActions


class _DummyPaths:
    """
    Provides a dummy paths test double.
    """

    def __init__(self, profile_root: Path) -> None:
        """
        Initializes the dummy paths helper.

        Args:
            profile_root (Path): The profile root.

        Returns:
            None
        """

        self._profile_root: Path = profile_root

    def exists(self) -> bool:
        """
        Executes exists for the test scenario.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return self._profile_root.exists()

    def create_directories(self) -> None:
        """
        Creates directories for the test scenario.

        Args:
            None

        Returns:
            None
        """

        self._profile_root.mkdir(parents=True, exist_ok=True)

    def get_config_file(self) -> Path:
        """
        Returns config file for the test scenario.

        Args:
            None

        Returns:
            Path: The computed return value.
        """

        return self._profile_root / 'config.json'


class _DummyProfileManager:
    """
    Provides a dummy profile manager test double.
    """

    def __init__(self, profile_root: Path, profile_name: str = 'alpha') -> None:
        """
        Initializes the dummy profile manager helper.

        Args:
            profile_root (Path): The profile root.
            profile_name (str): The profile name.

        Returns:
            None
        """

        self.profile_name: str = profile_name
        self.config: Config = Config(cast(Any, _DummyPaths(profile_root)))

    def is_daemon_running(self) -> bool:
        """
        Reports whether the helper is daemon running.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return False


def _translate_event(
    code: EventType,
    params: dict[str, object] | None = None,
) -> str:
    """
    Translates event for the test scenario.

    Args:
        code (EventType): The code.
        params (dict[str, object] | None): The params.

    Returns:
        str: The computed return value.
    """

    payload: dict[str, object] = {} if params is None else params
    if code is EventType.SETTING_DATA:
        return f"Global Setting '{payload.get('key')}': {payload.get('value')}"
    if code is EventType.CONFIG_DATA:
        return f"Profile Config '{payload.get('key')}': {payload.get('value')}"
    if code is EventType.INVALID_SETTING_KEY:
        return 'Invalid setting key provided.'
    if code is EventType.INVALID_CONFIG_KEY:
        return 'Invalid profile config key provided.'
    if code is EventType.SETTING_TYPE_ERROR:
        return str(payload.get('reason', 'invalid value'))
    return str(code.value)


class SettingsContractTests(unittest.TestCase):
    """
    Covers settings contract regression scenarios.
    """

    def _build_actions(
        self,
        temp_dir: str,
        *,
        request_ipc_result: str = 'daemon-section',
    ) -> tuple[CliProxySettingsActions, _DummyProfileManager, Path]:
        """
        Builds actions for the surrounding tests.

        Args:
            temp_dir (str): The temp dir.
            request_ipc_result (str): The request IPC result.

        Returns:
            tuple[CliProxySettingsActions, _DummyProfileManager, Path]: The computed return value.
        """

        root = Path(temp_dir)
        profile_root = root / 'alpha'
        pm = _DummyProfileManager(profile_root)
        actions = CliProxySettingsActions(
            cast(ProfileManager, pm),
            is_remote=False,
            request_ipc=lambda *_args, **_kwargs: request_ipc_result,
            translate_event=_translate_event,
        )
        return actions, pm, root / 'settings.json'

    def test_ui_settings_get_reads_global_value_not_effective_profile_value(
        self,
    ) -> None:
        """
        Verifies that UI settings get reads global value not effective profile value.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(temp_dir)
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.IPC_TIMEOUT, 7.5)
                pm.config.set(SettingKey.IPC_TIMEOUT, 9.5)

                result = actions.handle_settings_get(SettingKey.IPC_TIMEOUT.value)

        self.assertIn('Global Setting', result)
        self.assertIn('7.5', result)
        self.assertNotIn('9.5', result)

    def test_ui_settings_set_updates_global_store_without_profile_override(
        self,
    ) -> None:
        """
        Verifies that UI settings set updates global store without profile override.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(temp_dir)
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                result = actions.handle_settings_set(SettingKey.PROMPT_SIGN.value, '!')

                self.assertIn('updated successfully', result)
                self.assertEqual(Settings.get_str(SettingKey.PROMPT_SIGN), '!')
                self.assertFalse(pm.config._paths.get_config_file().exists())

    def test_ui_default_profile_can_be_set_globally_via_settings_command(self) -> None:
        """
        Verifies that UI default profile can be set globally via settings command.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, _pm, settings_path = self._build_actions(temp_dir)
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                result = actions.handle_settings_set(
                    SettingKey.DEFAULT_PROFILE.value,
                    'work',
                )

                self.assertIn('updated successfully', result)
                self.assertEqual(Settings.get_str(SettingKey.DEFAULT_PROFILE), 'work')

    def test_global_settings_validate_integrity_rejects_semantic_errors(self) -> None:
        """
        Verifies that global settings validate integrity rejects semantic errors.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / 'settings.json'
            settings_path.write_text(
                json.dumps({'ui': {'ipc_timeout': 'bogus'}, 'daemon': {}}),
                encoding='utf-8',
            )

            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                with self.assertRaisesRegex(ValueError, 'ui.ipc_timeout'):
                    Settings.validate_integrity()

    def test_profile_config_validate_integrity_rejects_unknown_keys(self) -> None:
        """
        Verifies that profile config validate integrity rejects unknown keys.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            _actions, pm, settings_path = self._build_actions(temp_dir)
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                pm.config._paths.create_directories()
                pm.config._paths.get_config_file().write_text(
                    json.dumps({'ui': {'unknown': 1}}),
                    encoding='utf-8',
                )

                with self.assertRaisesRegex(ValueError, 'ui.unknown'):
                    pm.config.validate_integrity()

    def test_settings_list_combines_local_ui_and_daemon_sections(self) -> None:
        """
        Verifies that settings list combines local UI and daemon sections.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, _pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result='Global Daemon Settings:\n  daemon.ipc_timeout = 15.0',
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_settings_list()

        self.assertIn('Global UI Settings', result)
        self.assertIn('ui.prompt_sign', result)
        self.assertIn('Global Daemon Settings', result)

    def test_config_list_combines_ui_structural_and_daemon_sections(self) -> None:
        """
        Verifies that config list combines UI structural and daemon sections.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result=(
                    "Effective Daemon Config for profile 'alpha':\n"
                    '  daemon.ipc_timeout = 15.0'
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                pm.config.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_config_list()

        self.assertIn("Effective UI Config for profile 'alpha'", result)
        self.assertIn('ui.prompt_sign', result)
        self.assertIn("Structural Profile Config for profile 'alpha'", result)
        self.assertIn('security_mode', result)
        self.assertIn("Effective Daemon Config for profile 'alpha'", result)

    def test_daemon_config_handler_keeps_single_setting_get_intact(self) -> None:
        """
        Verifies that daemon config handler keeps single setting get intact.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            _actions, pm, settings_path = self._build_actions(temp_dir)
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.DAEMON_IPC_TIMEOUT, 22.0)

                event = ConfigCommandHandler(cast(ProfileManager, pm)).handle(
                    GetSettingCommand(setting_key=SettingKey.DAEMON_IPC_TIMEOUT.value)
                )

        self.assertIs(event.event_type, EventType.SETTING_DATA)
        self.assertEqual(getattr(event, 'value', None), '22.0')


if __name__ == '__main__':
    unittest.main()
