"""Regression tests for the settings/config cascade and list contracts."""

# ruff: noqa: E402

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Optional, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    ConfigListDataEvent,
    EventType,
    GetHistoryCommand,
    GetSettingCommand,
    GetSettingsListCommand,
    IpcEvent,
    SettingSnapshotEntry,
    SettingsListDataEvent,
    SyncConfigCommand,
    create_event,
)
from metor.core.daemon.headless.dispatch import process_command
from metor.core.daemon.handlers import ConfigCommandHandler
from metor.data.profile import ProfileManager
from metor.data.profile.config import Config
from metor.data.settings import Settings, SettingKey
from metor.ui import Theme, UIPresenter
from metor.ui.cli.ipc.request.models import IpcRequestResult
from metor.ui.cli.proxy.settings import CliProxySettingsActions
from metor.ui.cli.proxy.transport import CliProxyTransport


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


class _LocalAuthConfig:
    """
    Provides a local-auth config test double.
    """

    def __init__(self, require_local_auth: bool) -> None:
        """
        Initializes the local-auth config helper.

        Args:
            require_local_auth (bool): Whether local auth is enabled.

        Returns:
            None
        """

        self._require_local_auth: bool = require_local_auth

    def get_bool(self, key: Any) -> bool:
        """
        Returns bool configuration values for the test scenario.

        Args:
            key (Any): The requested key.

        Returns:
            bool: The computed return value.
        """

        if key is SettingKey.REQUIRE_LOCAL_AUTH:
            return self._require_local_auth
        return False


class _TransportProfileManager:
    """
    Provides a transport profile-manager test double.
    """

    def __init__(self, require_local_auth: bool) -> None:
        """
        Initializes the transport profile-manager helper.

        Args:
            require_local_auth (bool): Whether local auth is enabled.

        Returns:
            None
        """

        self.config: _LocalAuthConfig = _LocalAuthConfig(require_local_auth)

    def get_daemon_port(self) -> None:
        """
        Reports that no managed daemon is running.

        Args:
            None

        Returns:
            None
        """

        return None

    def supports_password_auth(self) -> bool:
        """
        Reports that the profile supports password auth.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return True

    def get_static_port(self) -> int:
        """
        Returns one placeholder static port for error formatting.

        Args:
            None

        Returns:
            int: The computed return value.
        """

        return 4312


class _HeadlessConfigHandler:
    """
    Provides a config-handler test double for headless dispatch.
    """

    def __init__(self) -> None:
        """
        Initializes the config-handler helper.

        Args:
            None

        Returns:
            None
        """

        self.called: bool = False

    def handle(self, _cmd: object) -> IpcEvent:
        """
        Returns one synthetic settings-list event.

        Args:
            _cmd (object): The dispatched command.

        Returns:
            IpcEvent: The computed return value.
        """

        self.called = True
        return create_event(
            EventType.SETTINGS_LIST_DATA,
            {
                'scope': 'daemon',
                'entries': [],
            },
        )


class _HeadlessProfileManager:
    """
    Provides a headless profile-manager test double.
    """

    def __init__(self, require_local_auth: bool) -> None:
        """
        Initializes the headless profile-manager helper.

        Args:
            require_local_auth (bool): Whether local auth is enabled.

        Returns:
            None
        """

        self.config: _LocalAuthConfig = _LocalAuthConfig(require_local_auth)

    def supports_password_auth(self) -> bool:
        """
        Reports that the profile supports password auth.

        Args:
            None

        Returns:
            bool: The computed return value.
        """

        return True


class _HeadlessDispatchDaemon:
    """
    Provides a minimal headless-daemon test double.
    """

    def __init__(
        self,
        *,
        require_local_auth: bool,
        password: Optional[str],
    ) -> None:
        """
        Initializes the headless-daemon helper.

        Args:
            require_local_auth (bool): Whether local auth is enabled.
            password (Optional[str]): The supplied master password.

        Returns:
            None
        """

        self._pm = cast(ProfileManager, _HeadlessProfileManager(require_local_auth))
        self._password: Optional[str] = password
        self._config_handler: _HeadlessConfigHandler = _HeadlessConfigHandler()
        self.sent_events: list[IpcEvent] = []

    def _send(self, _conn: object, event: IpcEvent) -> None:
        """
        Captures one emitted IPC event.

        Args:
            _conn (object): The connection placeholder.
            event (IpcEvent): The emitted event.

        Returns:
            None
        """

        self.sent_events.append(event)


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
    if code is EventType.INVALID_PASSWORD:
        return 'Invalid master password.'
    if code is EventType.LOCAL_AUTH_RATE_LIMITED:
        return (
            'Too many invalid local authentication attempts. '
            f'Retry in {payload.get("retry_after")}s.'
        )
    return str(code.value)


def _build_prompt_password_callback(
    prompted: list[bool],
) -> Callable[..., str]:
    """
    Builds one password callback that records prompt usage.

    Args:
        prompted (list[bool]): The prompt-usage marker list.

    Returns:
        callable: The prompt callback used by transport tests.
    """

    def _prompt_password(*_args: Any, **_kwargs: Any) -> str:
        """
        Records one password prompt and returns a fixed test secret.

        Args:
            *_args (Any): Ignored positional arguments.
            **_kwargs (Any): Ignored keyword arguments.

        Returns:
            str: The fixed test password.
        """

        prompted.append(True)
        return 'secret'

    return _prompt_password


def _build_headless_result_callback(
    captured_passwords: list[Optional[str]],
    result: str,
) -> Callable[..., str]:
    """
    Builds one headless-daemon side effect that captures the supplied password.

    Args:
        captured_passwords (list[Optional[str]]): The captured passwords.
        result (str): The fixed headless result.

    Returns:
        callable: The side effect used by transport tests.
    """

    def _run_headless(_pm: Any, password: Optional[str], _handler: Any) -> str:
        """
        Captures the password passed to the headless runner.

        Args:
            _pm (Any): Ignored profile manager.
            password (Optional[str]): The supplied password.
            _handler (Any): Ignored request handler.

        Returns:
            str: The fixed headless result.
        """

        captured_passwords.append(password)
        return result

    return _run_headless


class SettingsContractTests(unittest.TestCase):
    """
    Covers settings contract regression scenarios.
    """

    def _build_actions(
        self,
        temp_dir: str,
        *,
        request_ipc_result: str = 'daemon-section',
        request_ipc_event: Optional[IpcEvent] = None,
        request_ipc_raw_result: Optional[IpcRequestResult] = None,
    ) -> tuple[CliProxySettingsActions, _DummyProfileManager, Path]:
        """
        Builds actions for the surrounding tests.

        Args:
            temp_dir (str): The temp dir.
            request_ipc_result (str): The request IPC result.
            request_ipc_event (Optional[IpcEvent]): Optional typed IPC event for list calls.
            request_ipc_raw_result (Optional[IpcRequestResult]): Optional fully typed IPC request result.

        Returns:
            tuple[CliProxySettingsActions, _DummyProfileManager, Path]: The computed return value.
        """

        root = Path(temp_dir)
        profile_root = root / 'alpha'
        pm = _DummyProfileManager(profile_root)
        if request_ipc_raw_result is None:
            insert_leading_blank_line: bool = request_ipc_result.startswith('\n')
            normalized_request_ipc_result: str = (
                request_ipc_result[1:]
                if insert_leading_blank_line
                else request_ipc_result
            )
            raw_result = IpcRequestResult(
                event=request_ipc_event,
                message=(
                    None
                    if request_ipc_event is not None
                    else normalized_request_ipc_result
                ),
                insert_leading_blank_line=insert_leading_blank_line,
            )
        else:
            raw_result = request_ipc_raw_result

        actions = CliProxySettingsActions(
            cast(ProfileManager, pm),
            is_remote=False,
            prefix_remote=lambda text: text,
            request_ipc=lambda *_args, **_kwargs: request_ipc_result,
            request_ipc_result=lambda *_args, **_kwargs: raw_result,
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
                request_ipc_event=SettingsListDataEvent(
                    scope='daemon',
                    entries=[
                        SettingSnapshotEntry(
                            key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                            value='15.0',
                            source='global',
                            category='Core Daemon',
                        )
                    ],
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_settings_list()

        self.assertIn('Global UI Settings', result)
        self.assertIn('ui.prompt_sign', result)
        self.assertIn('Global Daemon Settings', result)

    def test_live_disconnect_linger_default_stays_above_retunnel_reconnect_delay(
        self,
    ) -> None:
        """
        Verifies that live disconnect linger stays conservative for retunnel recovery.

        Args:
            None

        Returns:
            None
        """

        linger_default: float = float(
            Settings.SETTING_SPECS[SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT].default
        )
        retunnel_delay_default: float = float(
            Settings.SETTING_SPECS[SettingKey.RETUNNEL_RECONNECT_DELAY].default
        )

        self.assertEqual(linger_default, 2.0)
        self.assertGreater(linger_default, retunnel_delay_default)

    def test_offline_settings_list_prompts_when_local_auth_enabled(self) -> None:
        """
        Verifies that offline settings list prompts when local auth is enabled.

        Args:
            None

        Returns:
            None
        """

        prompted: list[bool] = []
        captured_passwords: list[Optional[str]] = []
        transport = CliProxyTransport(
            cast(ProfileManager, _TransportProfileManager(True)),
            is_remote=False,
            prompt_password=_build_prompt_password_callback(prompted),
            prefix_remote=lambda text: text,
            format_event=lambda event, prefix_remote=True: event.event_type.value,
            send_socket_command=lambda *_args, **_kwargs: None,
        )

        with patch(
            'metor.ui.cli.proxy.transport.run_with_headless_daemon',
            side_effect=_build_headless_result_callback(
                captured_passwords,
                'settings-output\nline-2',
            ),
        ):
            result = transport.request_ipc(GetSettingsListCommand())

        self.assertEqual(result, '\nsettings-output\nline-2')
        self.assertEqual(prompted, [True])
        self.assertEqual(captured_passwords, ['secret'])

    def test_offline_history_output_gets_blank_line_after_password_prompt(
        self,
    ) -> None:
        """
        Verifies that offline multiline history output gets the auth blank line.

        Args:
            None

        Returns:
            None
        """

        prompted: list[bool] = []
        transport = CliProxyTransport(
            cast(ProfileManager, _TransportProfileManager(True)),
            is_remote=False,
            prompt_password=_build_prompt_password_callback(prompted),
            prefix_remote=lambda text: text,
            format_event=lambda event, prefix_remote=True: event.event_type.value,
            send_socket_command=lambda *_args, **_kwargs: None,
        )

        with patch(
            'metor.ui.cli.proxy.transport.run_with_headless_daemon',
            return_value='history-output\nline-2',
        ):
            result = transport.request_ipc(GetHistoryCommand())

        self.assertEqual(result, '\nhistory-output\nline-2')
        self.assertEqual(prompted, [True])

    def test_offline_single_line_setting_output_gets_blank_line_after_password_prompt(
        self,
    ) -> None:
        """
        Verifies that offline single-line output also gets the auth blank line.

        Args:
            None

        Returns:
            None
        """

        prompted: list[bool] = []
        transport = CliProxyTransport(
            cast(ProfileManager, _TransportProfileManager(True)),
            is_remote=False,
            prompt_password=_build_prompt_password_callback(prompted),
            prefix_remote=lambda text: text,
            format_event=lambda event, prefix_remote=True: event.event_type.value,
            send_socket_command=lambda *_args, **_kwargs: None,
        )

        with patch(
            'metor.ui.cli.proxy.transport.run_with_headless_daemon',
            return_value='setting-value',
        ):
            result = transport.request_ipc(
                GetSettingCommand(setting_key=SettingKey.DAEMON_IPC_TIMEOUT.value)
            )

        self.assertEqual(result, '\nsetting-value')
        self.assertEqual(prompted, [True])

    def test_offline_settings_list_skips_prompt_when_local_auth_disabled(self) -> None:
        """
        Verifies that offline settings list skips prompt when local auth is disabled.

        Args:
            None

        Returns:
            None
        """

        prompted: list[bool] = []
        captured_passwords: list[Optional[str]] = []
        transport = CliProxyTransport(
            cast(ProfileManager, _TransportProfileManager(False)),
            is_remote=False,
            prompt_password=_build_prompt_password_callback(prompted),
            prefix_remote=lambda text: text,
            format_event=lambda event, prefix_remote=True: event.event_type.value,
            send_socket_command=lambda *_args, **_kwargs: None,
        )

        with patch(
            'metor.ui.cli.proxy.transport.run_with_headless_daemon',
            side_effect=_build_headless_result_callback(
                captured_passwords,
                'ok',
            ),
        ):
            result = transport.request_ipc(GetSettingsListCommand())

        self.assertEqual(result, 'ok')
        self.assertEqual(prompted, [])
        self.assertEqual(captured_passwords, [None])

    def test_settings_snapshot_hides_source_markers(self) -> None:
        """
        Verifies that settings snapshot hides source markers.

        Args:
            None

        Returns:
            None
        """

        rendered = UIPresenter.format_response(
            SettingsListDataEvent(
                scope='ui',
                entries=[
                    SettingSnapshotEntry(
                        key=SettingKey.PROMPT_SIGN.value,
                        value='!',
                        source='global',
                        category='User Interface',
                    ),
                    SettingSnapshotEntry(
                        key=SettingKey.CHAT_LIMIT.value,
                        value='50',
                        source='default',
                        category='User Interface',
                    ),
                ],
            )
        )

        self.assertNotIn(f'[{Theme.DARK_GREY}global{Theme.RESET}]', rendered)
        self.assertNotIn(f'[{Theme.DARK_GREY}default{Theme.RESET}]', rendered)

    def test_settings_snapshot_has_blank_line_after_header(self) -> None:
        """
        Verifies that settings snapshot has one blank line after the header.

        Args:
            None

        Returns:
            None
        """

        rendered = UIPresenter.format_response(
            SettingsListDataEvent(
                scope='ui',
                entries=[
                    SettingSnapshotEntry(
                        key=SettingKey.PROMPT_SIGN.value,
                        value='!',
                        source='global',
                        category='User Interface',
                    )
                ],
            )
        )

        self.assertIn('Global UI Settings:\n\n[User Interface]', rendered)

    def test_config_snapshot_keeps_global_marker(self) -> None:
        """
        Verifies that config snapshot still shows the global source marker.

        Args:
            None

        Returns:
            None
        """

        rendered = UIPresenter.format_response(
            ConfigListDataEvent(
                scope='daemon',
                profile='alpha',
                entries=[
                    SettingSnapshotEntry(
                        key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                        value='15.0',
                        source='global',
                        category='Core Daemon',
                    )
                ],
            )
        )

        self.assertIn(f'[{Theme.DARK_GREY}global{Theme.RESET}]', rendered)

    def test_config_snapshot_has_blank_line_after_header(self) -> None:
        """
        Verifies that config snapshot has one blank line after the header.

        Args:
            None

        Returns:
            None
        """

        rendered = UIPresenter.format_response(
            ConfigListDataEvent(
                scope='daemon',
                profile='alpha',
                entries=[
                    SettingSnapshotEntry(
                        key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                        value='15.0',
                        source='global',
                        category='Core Daemon',
                    )
                ],
            )
        )

        self.assertIn(
            "Effective Daemon Config for profile 'alpha':\n\n[Core Daemon]",
            rendered,
        )

    def test_settings_list_moves_auth_spacing_before_first_header(self) -> None:
        """
        Verifies that settings list places auth spacing before the first header.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, _pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result='\n',
                request_ipc_event=SettingsListDataEvent(
                    scope='daemon',
                    entries=[
                        SettingSnapshotEntry(
                            key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                            value='15.0',
                            source='global',
                            category='Core Daemon',
                        )
                    ],
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                result = actions.handle_settings_list()

        self.assertTrue(result.startswith('\nGlobal UI Settings:\n\n[User Interface]'))
        self.assertIn('\n\nGlobal Daemon Settings:\n\n[Core Daemon]', result)
        self.assertNotIn('\n\n\nGlobal Daemon Settings', result)
        self.assertTrue(result.endswith('\n'))

    def test_settings_list_explains_omitted_daemon_section_after_auth_failure(
        self,
    ) -> None:
        """
        Verifies that partial settings output explains omitted daemon settings on auth failure.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, _pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result='\n',
                request_ipc_event=create_event(
                    EventType.LOCAL_AUTH_RATE_LIMITED,
                    {'retry_after': 30},
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                result = actions.handle_settings_list()

        self.assertTrue(result.startswith('\nGlobal UI Settings:\n\n[User Interface]'))
        self.assertIn(
            'Daemon settings were not shown because local daemon authentication failed. '
            'Too many invalid local authentication attempts. Retry in 30s.',
            result,
        )
        self.assertNotIn('Global Daemon Settings', result)

    def test_settings_list_hides_empty_password_detail_when_auth_not_completed(
        self,
    ) -> None:
        """
        Verifies that empty password auth stops without appending a validation detail.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, _pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_raw_result=IpcRequestResult(
                    message='Aborted.',
                    insert_leading_blank_line=True,
                    auth_incomplete=True,
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                result = actions.handle_settings_list()

        self.assertIn(
            'Daemon settings were not shown because local daemon authentication did not complete.',
            result,
        )
        self.assertNotIn('Master password cannot be empty.', result)
        self.assertNotIn('Aborted.', result)

    def test_config_list_preserves_trailing_newline(self) -> None:
        """
        Verifies that config list preserves one trailing newline at the end.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_event=ConfigListDataEvent(
                    scope='daemon',
                    profile='alpha',
                    entries=[
                        SettingSnapshotEntry(
                            key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                            value='15.0',
                            source='global',
                            category='Core Daemon',
                        )
                    ],
                ),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                pm.config.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_config_list()

        self.assertTrue(result.endswith('\n'))

    def test_config_list_explains_omitted_daemon_section_after_invalid_password(
        self,
    ) -> None:
        """
        Verifies that partial config output explains omitted daemon config on auth failure.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result='\n',
                request_ipc_event=create_event(EventType.INVALID_PASSWORD),
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                pm.config.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_config_list()

        self.assertTrue(
            result.startswith("\nEffective UI Config for profile 'alpha':\n\n")
        )
        self.assertIn(
            'Daemon config values were not shown because local daemon authentication failed. '
            'Invalid master password.',
            result,
        )
        self.assertNotIn("Effective Daemon Config for profile 'alpha'", result)

    def test_headless_settings_list_requires_password_when_local_auth_enabled(
        self,
    ) -> None:
        """
        Verifies that headless settings list requires password when local auth is enabled.

        Args:
            None

        Returns:
            None
        """

        daemon = _HeadlessDispatchDaemon(require_local_auth=True, password=None)

        process_command(
            cast(Any, daemon),
            GetSettingsListCommand(),
            cast(Any, object()),
        )

        self.assertEqual(len(daemon.sent_events), 1)
        self.assertIs(daemon.sent_events[0].event_type, EventType.INVALID_PASSWORD)
        self.assertFalse(daemon._config_handler.called)

    def test_headless_settings_list_stays_passwordless_when_local_auth_disabled(
        self,
    ) -> None:
        """
        Verifies that headless settings list stays passwordless when local auth is disabled.

        Args:
            None

        Returns:
            None
        """

        daemon = _HeadlessDispatchDaemon(require_local_auth=False, password=None)

        process_command(
            cast(Any, daemon),
            GetSettingsListCommand(),
            cast(Any, object()),
        )

        self.assertEqual(len(daemon.sent_events), 1)
        self.assertIs(
            daemon.sent_events[0].event_type,
            EventType.SETTINGS_LIST_DATA,
        )
        self.assertTrue(daemon._config_handler.called)

    def test_config_sync_does_not_clear_local_overrides_when_daemon_sync_fails(
        self,
    ) -> None:
        """
        Verifies that config sync leaves local overrides intact when daemon sync fails.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            actions, pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result='Invalid master password.',
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                Settings.set(SettingKey.DAEMON_IPC_TIMEOUT, 15.0)
                pm.config.set(SettingKey.PROMPT_SIGN, '!')
                pm.config.set(SettingKey.DAEMON_IPC_TIMEOUT, 21.0)

                result = actions.handle_config_sync()

                self.assertEqual(result, 'Invalid master password.')
                self.assertEqual(pm.config.get_str(SettingKey.PROMPT_SIGN), '!')
                self.assertEqual(
                    pm.config.get_str(SettingKey.DAEMON_IPC_TIMEOUT), '21.0'
                )

    def test_config_sync_clears_local_ui_overrides_after_daemon_success(self) -> None:
        """
        Verifies that config sync clears local UI overrides only after daemon success.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            success_msg = _translate_event(EventType.CONFIG_SYNCED)
            actions, pm, settings_path = self._build_actions(
                temp_dir,
                request_ipc_result=success_msg,
            )
            with patch.object(
                Settings, 'get_global_settings_path', return_value=settings_path
            ):
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                pm.config.set(SettingKey.PROMPT_SIGN, '!')

                result = actions.handle_config_sync()

                self.assertEqual(result, success_msg)
                self.assertEqual(pm.config.get_str(SettingKey.PROMPT_SIGN), '$')

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
                request_ipc_event=ConfigListDataEvent(
                    scope='daemon',
                    profile='alpha',
                    entries=[
                        SettingSnapshotEntry(
                            key=SettingKey.DAEMON_IPC_TIMEOUT.value,
                            value='15.0',
                            source='global',
                            category='Core Daemon',
                        )
                    ],
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

    def test_daemon_config_handler_sync_clears_only_daemon_overrides(self) -> None:
        """
        Verifies that daemon config sync clears only daemon overrides.

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
                Settings.set(SettingKey.PROMPT_SIGN, '$')
                Settings.set(SettingKey.DAEMON_IPC_TIMEOUT, 15.0)
                pm.config.set(SettingKey.PROMPT_SIGN, '!')
                pm.config.set(SettingKey.DAEMON_IPC_TIMEOUT, 21.0)

                event = ConfigCommandHandler(cast(ProfileManager, pm)).handle(
                    SyncConfigCommand()
                )

                self.assertIs(event.event_type, EventType.CONFIG_SYNCED)
                self.assertEqual(pm.config.get_str(SettingKey.PROMPT_SIGN), '!')
                self.assertEqual(
                    pm.config.get_str(SettingKey.DAEMON_IPC_TIMEOUT), '15.0'
                )


if __name__ == '__main__':
    unittest.main()
