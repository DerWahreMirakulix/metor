"""
Module for handling global application settings securely.
Utilizes a centralized cross-platform file locking mechanism to prevent race conditions.
Enforces strict typing using Enums for configuration keys and strongly-typed accessors.
Prevents silent overwrites of corrupted JSON configurations.
"""

from dataclasses import dataclass
import json
from enum import Enum
from pathlib import Path
from typing import Dict, Union, Optional

from metor.utils import Constants, FileLock, TypeCaster, validate_json_file


# Types
SettingValue = Union[str, int, float, bool]


class SettingKey(str, Enum):
    """Available global configuration keys strictly isolated by Client (ui) and Server (daemon) domains."""

    # 1. User Interface (Client)
    DEFAULT_PROFILE = 'ui.default_profile'
    PROMPT_SIGN = 'ui.prompt_sign'
    CHAT_LIMIT = 'ui.chat_limit'
    HISTORY_LIMIT = 'ui.history_limit'
    MESSAGES_LIMIT = 'ui.messages_limit'
    CHAT_BUFFER_PADDING = 'ui.chat_buffer_padding'
    INBOX_NOTIFICATION_DELAY = 'ui.inbox_notification_delay'
    IPC_TIMEOUT = 'ui.ipc_timeout'

    # 2. Core Daemon (Server - Network, Persistence & Security)
    MAX_TOR_RETRIES = 'daemon.max_tor_retries'
    MAX_CONNECT_RETRIES = 'daemon.max_connect_retries'
    TOR_TIMEOUT = 'daemon.tor_timeout'
    STREAM_IDLE_TIMEOUT = 'daemon.stream_idle_timeout'
    LATE_ACCEPTANCE_TIMEOUT = 'daemon.late_acceptance_timeout'
    DAEMON_IPC_TIMEOUT = 'daemon.ipc_timeout'
    ENABLE_TOR_LOGGING = 'daemon.enable_tor_logging'
    ENABLE_SQL_LOGGING = 'daemon.enable_sql_logging'
    ENABLE_RUNTIME_DB_MIRROR = 'daemon.enable_runtime_db_mirror'
    AUTO_ACCEPT_CONTACTS = 'daemon.auto_accept_contacts'
    REQUIRE_LOCAL_AUTH = 'daemon.require_local_auth'
    ALLOW_DROPS = 'daemon.allow_drops'
    EPHEMERAL_MESSAGES = 'daemon.ephemeral_messages'
    RECORD_LIVE_HISTORY = 'daemon.record_live_history'
    RECORD_DROP_HISTORY = 'daemon.record_drop_history'
    FALLBACK_TO_DROP = 'daemon.fallback_to_drop'
    MAX_UNSEEN_LIVE_MSGS = 'daemon.max_unseen_live_msgs'

    # 3. Advanced Network Resilience & Constraints
    MAX_CONCURRENT_CONNECTIONS = 'daemon.max_concurrent_connections'
    DROP_TUNNEL_IDLE_TIMEOUT = 'daemon.drop_tunnel_idle_timeout'
    ALLOW_DROP_STANDBY_ON_LIVE = 'daemon.allow_drop_standby_on_live'
    CONNECT_RETRY_BACKOFF_DELAY = 'daemon.connect_retry_backoff_delay'
    LIVE_RECONNECT_DELAY = 'daemon.live_reconnect_delay'
    LIVE_RECONNECT_GRACE_TIMEOUT = 'daemon.live_reconnect_grace_timeout'
    LIVE_DISCONNECT_LINGER_TIMEOUT = 'daemon.live_disconnect_linger_timeout'
    RETUNNEL_RECONNECT_DELAY = 'daemon.retunnel_reconnect_delay'
    RETUNNEL_RECOVERY_RETRIES = 'daemon.retunnel_recovery_retries'

    @property
    def is_ui(self) -> bool:
        """
        Determines if the setting belongs to the User Interface domain.

        Args:
            None

        Returns:
            bool: True if it is a UI setting.
        """
        return self.value.startswith('ui.')

    @property
    def is_daemon(self) -> bool:
        """
        Determines if the setting belongs to the Daemon domain.

        Args:
            None

        Returns:
            bool: True if it is a Daemon setting.
        """
        return self.value.startswith('daemon.')


class SettingValidationError(ValueError):
    """Raised when a setting value violates semantic constraints."""


@dataclass(frozen=True)
class SettingSpec:
    """Describes one supported setting and its documentation metadata."""

    key: SettingKey
    default: SettingValue
    category: str
    description: str
    constraints: str
    security_note: Optional[str] = None
    allow_profile_override: bool = True
    allow_empty_string: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class Settings:
    """Dynamic application settings manager reading from and writing to a nested global JSON file."""

    SETTING_SPECS: Dict[SettingKey, SettingSpec] = {
        SettingKey.DEFAULT_PROFILE: SettingSpec(
            key=SettingKey.DEFAULT_PROFILE,
            default='default',
            category='User Interface',
            description='Selects the profile used when the CLI is started without `-p`.',
            constraints='Non-empty profile name using letters, numbers, `-`, or `_`.',
            allow_profile_override=False,
            allow_empty_string=False,
        ),
        SettingKey.PROMPT_SIGN: SettingSpec(
            key=SettingKey.PROMPT_SIGN,
            default='$',
            category='User Interface',
            description='Sets the prompt prefix shown in the interactive chat UI.',
            constraints='Non-empty string.',
            allow_empty_string=False,
        ),
        SettingKey.CHAT_LIMIT: SettingSpec(
            key=SettingKey.CHAT_LIMIT,
            default=50,
            category='User Interface',
            description='Limits the number of rendered chat lines kept in volatile UI memory.',
            constraints='Integer >= 1.',
            min_value=1,
        ),
        SettingKey.HISTORY_LIMIT: SettingSpec(
            key=SettingKey.HISTORY_LIMIT,
            default=50,
            category='User Interface',
            description='Default number of history events shown per request.',
            constraints='Integer >= 1.',
            min_value=1,
        ),
        SettingKey.MESSAGES_LIMIT: SettingSpec(
            key=SettingKey.MESSAGES_LIMIT,
            default=50,
            category='User Interface',
            description='Default number of stored messages shown per request.',
            constraints='Integer >= 1.',
            min_value=1,
        ),
        SettingKey.CHAT_BUFFER_PADDING: SettingSpec(
            key=SettingKey.CHAT_BUFFER_PADDING,
            default=20,
            category='User Interface',
            description='Keeps extra renderer lines around the viewport to reduce redraw churn.',
            constraints='Integer >= 0.',
            min_value=0,
        ),
        SettingKey.INBOX_NOTIFICATION_DELAY: SettingSpec(
            key=SettingKey.INBOX_NOTIFICATION_DELAY,
            default=10.0,
            category='User Interface',
            description='Delays and aggregates unread-message notifications while the peer is unfocused. `0` disables buffering.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.IPC_TIMEOUT: SettingSpec(
            key=SettingKey.IPC_TIMEOUT,
            default=15.0,
            category='User Interface',
            description='Client-side timeout for CLI and chat IPC requests.',
            constraints='Float >= 0.1 seconds.',
            min_value=0.1,
        ),
        SettingKey.MAX_TOR_RETRIES: SettingSpec(
            key=SettingKey.MAX_TOR_RETRIES,
            default=3,
            category='Core Daemon',
            description='Controls how many times Tor launch is attempted before startup fails.',
            constraints='Integer >= 1.',
            min_value=1,
        ),
        SettingKey.MAX_CONNECT_RETRIES: SettingSpec(
            key=SettingKey.MAX_CONNECT_RETRIES,
            default=3,
            category='Core Daemon',
            description='Controls how many additional live connect retries run after the initial attempt.',
            constraints='Integer >= 0.',
            min_value=0,
        ),
        SettingKey.TOR_TIMEOUT: SettingSpec(
            key=SettingKey.TOR_TIMEOUT,
            default=10.0,
            category='Core Daemon',
            description='Timeout for outbound Tor socket operations and readiness checks.',
            constraints='Float >= 0.1 seconds.',
            min_value=0.1,
        ),
        SettingKey.STREAM_IDLE_TIMEOUT: SettingSpec(
            key=SettingKey.STREAM_IDLE_TIMEOUT,
            default=60.0,
            category='Core Daemon',
            description=(
                'Socket read timeout for active live sessions and idle timeout '
                'for drop sockets. Active live chats stay connected across pure '
                'read timeouts.'
            ),
            constraints='Float >= 0.1 seconds.',
            min_value=0.1,
        ),
        SettingKey.LATE_ACCEPTANCE_TIMEOUT: SettingSpec(
            key=SettingKey.LATE_ACCEPTANCE_TIMEOUT,
            default=60.0,
            category='Core Daemon',
            description='Window during which pending live sessions may still be accepted.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.DAEMON_IPC_TIMEOUT: SettingSpec(
            key=SettingKey.DAEMON_IPC_TIMEOUT,
            default=15.0,
            category='Core Daemon',
            description='Server-side timeout for daemon IPC sockets.',
            constraints='Float >= 0.1 seconds.',
            min_value=0.1,
        ),
        SettingKey.ENABLE_TOR_LOGGING: SettingSpec(
            key=SettingKey.ENABLE_TOR_LOGGING,
            default=False,
            category='Core Daemon',
            description='Emits Tor process logs to the terminal.',
            constraints='Boolean.',
            security_note='Can reveal operational timing and local environment details in terminal logs.',
        ),
        SettingKey.ENABLE_SQL_LOGGING: SettingSpec(
            key=SettingKey.ENABLE_SQL_LOGGING,
            default=False,
            category='Core Daemon',
            description='Emits SQLCipher and SQLite diagnostics to the terminal.',
            constraints='Boolean.',
            security_note='Can expose local schema, file, and corruption details in logs.',
        ),
        SettingKey.ENABLE_RUNTIME_DB_MIRROR: SettingSpec(
            key=SettingKey.ENABLE_RUNTIME_DB_MIRROR,
            default=False,
            category='Core Daemon',
            description='Exports a plaintext runtime copy of the encrypted database for local inspection tools.',
            constraints='Boolean.',
            security_note='Creates a plaintext database on disk while enabled. Keep disabled unless you explicitly need local inspection tooling.',
        ),
        SettingKey.AUTO_ACCEPT_CONTACTS: SettingSpec(
            key=SettingKey.AUTO_ACCEPT_CONTACTS,
            default=True,
            category='Core Daemon',
            description='Automatically accepts incoming live sessions from saved contacts.',
            constraints='Boolean.',
            security_note='Improves convenience for known contacts, but reduces explicit confirmation on inbound reconnects.',
        ),
        SettingKey.REQUIRE_LOCAL_AUTH: SettingSpec(
            key=SettingKey.REQUIRE_LOCAL_AUTH,
            default=True,
            category='Core Daemon',
            description='Requires every UI session to authenticate even when the daemon is already running.',
            constraints='Boolean.',
            security_note='Enabled by default for encrypted profiles. Disable it only on trusted single-user hosts.',
        ),
        SettingKey.ALLOW_DROPS: SettingSpec(
            key=SettingKey.ALLOW_DROPS,
            default=True,
            category='Core Daemon',
            description='Enables reception and processing of offline drop messages.',
            constraints='Boolean.',
        ),
        SettingKey.EPHEMERAL_MESSAGES: SettingSpec(
            key=SettingKey.EPHEMERAL_MESSAGES,
            default=False,
            category='Core Daemon',
            description='Shreds consumed drop-message payloads after they are read instead of retaining them in message history.',
            constraints='Boolean.',
            security_note='Improves local deniability by removing consumed drop content while preserving minimal delivery metadata for deduplication.',
        ),
        SettingKey.RECORD_LIVE_HISTORY: SettingSpec(
            key=SettingKey.RECORD_LIVE_HISTORY,
            default=True,
            category='Core Daemon',
            description='Persists raw live transport rows in the history ledger and projected summary history.',
            constraints='Boolean.',
            security_note='Disabling reduces local metadata retention for live sessions.',
        ),
        SettingKey.RECORD_DROP_HISTORY: SettingSpec(
            key=SettingKey.RECORD_DROP_HISTORY,
            default=True,
            category='Core Daemon',
            description='Persists raw drop transport rows in the history ledger and projected summary history.',
            constraints='Boolean.',
            security_note='Disabling reduces local metadata retention for drop delivery attempts.',
        ),
        SettingKey.FALLBACK_TO_DROP: SettingSpec(
            key=SettingKey.FALLBACK_TO_DROP,
            default=True,
            category='Core Daemon',
            description='Falls back unacknowledged live messages into the offline drop queue when possible.',
            constraints='Boolean.',
        ),
        SettingKey.MAX_UNSEEN_LIVE_MSGS: SettingSpec(
            key=SettingKey.MAX_UNSEEN_LIVE_MSGS,
            default=20,
            category='Core Daemon',
            description='Caps unread crash-safe live backlog per peer. `0` disables headless live backlog, while `-1` removes the limit entirely.',
            constraints='Integer >= -1.',
            min_value=-1,
        ),
        SettingKey.MAX_CONCURRENT_CONNECTIONS: SettingSpec(
            key=SettingKey.MAX_CONCURRENT_CONNECTIONS,
            default=50,
            category='Advanced Network Resilience',
            description='Limits simultaneous authenticated and unauthenticated live sockets handled by the daemon.',
            constraints='Integer >= 1.',
            min_value=1,
        ),
        SettingKey.DROP_TUNNEL_IDLE_TIMEOUT: SettingSpec(
            key=SettingKey.DROP_TUNNEL_IDLE_TIMEOUT,
            default=30.0,
            category='Advanced Network Resilience',
            description='Controls cached drop tunnel lifetime. `0` disables caching completely.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.ALLOW_DROP_STANDBY_ON_LIVE: SettingSpec(
            key=SettingKey.ALLOW_DROP_STANDBY_ON_LIVE,
            default=False,
            category='Advanced Network Resilience',
            description='Keeps a cached drop tunnel warm while live remains the primary transport.',
            constraints='Boolean.',
        ),
        SettingKey.CONNECT_RETRY_BACKOFF_DELAY: SettingSpec(
            key=SettingKey.CONNECT_RETRY_BACKOFF_DELAY,
            default=3.0,
            category='Advanced Network Resilience',
            description='Delay between explicit live connect retries after the initial attempt. `0` retries immediately.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.LIVE_RECONNECT_DELAY: SettingSpec(
            key=SettingKey.LIVE_RECONNECT_DELAY,
            default=15,
            category='Advanced Network Resilience',
            description='Base delay before automatic live reconnect attempts. `0` disables automatic reconnect.',
            constraints='Integer >= 0 seconds.',
            min_value=0,
        ),
        SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT: SettingSpec(
            key=SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT,
            default=15,
            category='Advanced Network Resilience',
            description='Reconnect grace window for silently accepting a recent peer reconnect. `0` disables reconnect grace.',
            constraints='Integer >= 0 seconds.',
            min_value=0,
        ),
        SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT: SettingSpec(
            key=SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT,
            default=1.0,
            category='Advanced Network Resilience',
            description='Keeps a locally initiated live socket open briefly after sending `DISCONNECT` so the control frame can flush through Tor before shutdown. Higher values improve retunnel reliability on slower routes.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.RETUNNEL_RECONNECT_DELAY: SettingSpec(
            key=SettingKey.RETUNNEL_RECONNECT_DELAY,
            default=1.0,
            category='Advanced Network Resilience',
            description='Delay before reconnecting after a live retunnel disconnect. `0` reconnects immediately.',
            constraints='Float >= 0 seconds.',
            min_value=0.0,
        ),
        SettingKey.RETUNNEL_RECOVERY_RETRIES: SettingSpec(
            key=SettingKey.RETUNNEL_RECOVERY_RETRIES,
            default=2,
            category='Advanced Network Resilience',
            description='Additional delayed retunnel recovery retries after a transient reject or early close.',
            constraints='Integer >= 0.',
            min_value=0,
        ),
    }

    _DEFAULTS: Dict[str, SettingValue] = {
        spec.key.value: spec.default for spec in SETTING_SPECS.values()
    }

    @classmethod
    def get_specs(cls) -> tuple[SettingSpec, ...]:
        """
        Returns the ordered setting specifications for documentation and validation.

        Args:
            None

        Returns:
            tuple[SettingSpec, ...]: All supported setting specifications.
        """
        return tuple(cls.SETTING_SPECS.values())

    @classmethod
    def get_spec(cls, key: SettingKey) -> SettingSpec:
        """
        Returns the metadata for one setting key.

        Args:
            key (SettingKey): The setting key.

        Returns:
            SettingSpec: The matching setting specification.
        """
        return cls.SETTING_SPECS[key]

    @classmethod
    def validate_value(
        cls,
        key: SettingKey,
        value: SettingValue,
        *,
        for_profile_override: bool = False,
    ) -> SettingValue:
        """
        Validates and normalizes one setting value against the declared schema.

        Args:
            key (SettingKey): The setting key to validate.
            value (SettingValue): The candidate value.
            for_profile_override (bool): Whether the value is written as a profile override.

        Raises:
            TypeError: If the value type is invalid.
            SettingValidationError: If the value violates semantic constraints.

        Returns:
            SettingValue: The normalized value.
        """
        spec: SettingSpec = cls.get_spec(key)

        if for_profile_override and not spec.allow_profile_override:
            raise SettingValidationError(
                f"Setting '{key.value}' can only be changed globally."
            )

        expected_type: type = type(spec.default)
        normalized: SettingValue

        if expected_type is bool:
            if type(value) is not bool:
                raise TypeError(
                    f"Invalid type for '{key.value}'. Expected bool, got {type(value).__name__}."
                )
            normalized = value
        elif expected_type is int:
            if type(value) is not int:
                raise TypeError(
                    f"Invalid type for '{key.value}'. Expected int, got {type(value).__name__}."
                )
            normalized = value
        elif expected_type is float:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(
                    f"Invalid type for '{key.value}'. Expected float, got {type(value).__name__}."
                )
            normalized = float(value)
        elif expected_type is str:
            if type(value) is not str:
                raise TypeError(
                    f"Invalid type for '{key.value}'. Expected str, got {type(value).__name__}."
                )

            normalized = value.strip() if key is SettingKey.DEFAULT_PROFILE else value
            if not spec.allow_empty_string and not normalized:
                raise SettingValidationError(
                    f"Setting '{key.value}' must not be empty."
                )

            if key is SettingKey.DEFAULT_PROFILE:
                safe_name: str = ''.join(
                    c for c in normalized if c.isalnum() or c in ('-', '_')
                )
                if safe_name != normalized:
                    raise SettingValidationError(
                        f"Setting '{key.value}' must contain only letters, numbers, '-' or '_'."
                    )
        else:
            normalized = value

        if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
            if spec.min_value is not None and float(normalized) < spec.min_value:
                raise SettingValidationError(
                    f"Setting '{key.value}' must be >= {spec.min_value:g}."
                )
            if spec.max_value is not None and float(normalized) > spec.max_value:
                raise SettingValidationError(
                    f"Setting '{key.value}' must be <= {spec.max_value:g}."
                )

        return normalized

    @staticmethod
    def get_global_settings_path() -> Path:
        """
        Retrieves the path to the global settings JSON file.

        Args:
            None

        Returns:
            Path: Absolute path object to settings.json.
        """
        data_dir: Path = Constants.DATA
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / Constants.SETTINGS_FILE

    @classmethod
    def validate_integrity(cls) -> None:
        """
        Validates the JSON syntax of the global settings file using the generic parser utility.

        Args:
            None

        Raises:
            ValueError: If the file exists but contains a syntax error.

        Returns:
            None
        """
        path: Path = cls.get_global_settings_path()
        validate_json_file(path)

    @classmethod
    def _load_settings(cls) -> Dict[str, Dict[str, SettingValue]]:
        """
        Loads the settings from the JSON file into a nested structure.
        Creates the default structure and writes it to disk if the file is missing.
        Prevents overwriting the file if a JSONDecodeError occurs on an existing file.

        Args:
            None

        Returns:
            Dict[str, Dict[str, SettingValue]]: The loaded settings dictionary partitioned by domain.
        """
        path: Path = cls.get_global_settings_path()
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f:
                    data: Dict[str, Dict[str, SettingValue]] = json.load(f)

                    for domain in ('ui', 'daemon'):
                        if domain not in data:
                            data[domain] = {}

                    return data
            except (json.JSONDecodeError, IOError):
                pass

        data = {'ui': {}, 'daemon': {}}
        for key_enum, val in cls._DEFAULTS.items():
            category: str
            sub_key: str
            category, sub_key = key_enum.split('.', 1)
            data[category][sub_key] = val

        if not path.exists():
            with FileLock(path):
                with path.open('w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)

        return data

    @classmethod
    def get(cls, key: SettingKey) -> Optional[SettingValue]:
        """
        Retrieves a setting value by its strongly-typed key. Uses default if not found.

        Args:
            key (SettingKey): The setting key enum to retrieve.

        Returns:
            Optional[SettingValue]: The value of the setting, or None if completely missing.
        """
        data: Dict[str, Dict[str, SettingValue]] = cls._load_settings()
        category: str
        sub_key: str
        category, sub_key = key.value.split('.', 1)

        if category in data and sub_key in data[category]:
            candidate: SettingValue = data[category][sub_key]
            try:
                return cls.validate_value(key, candidate)
            except (TypeError, SettingValidationError):
                return cls._DEFAULTS.get(key.value)

        return cls._DEFAULTS.get(key.value)

    @classmethod
    def get_str(cls, key: SettingKey) -> str:
        """
        Retrieves a setting and guarantees a string return type.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            str: The configuration value as a string.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_str(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_str(default_val)

    @classmethod
    def get_int(cls, key: SettingKey) -> int:
        """
        Retrieves a setting and safely coerces it into an integer.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            int: The configuration value as an integer.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_int(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_int(default_val)

    @classmethod
    def get_float(cls, key: SettingKey) -> float:
        """
        Retrieves a setting and safely coerces it into a float.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            float: The configuration value as a float.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_float(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_float(default_val)

    @classmethod
    def get_bool(cls, key: SettingKey) -> bool:
        """
        Retrieves a setting and safely coerces it into a boolean.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            bool: The configuration value as a boolean.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_bool(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_bool(default_val)

    @classmethod
    def set(cls, key: SettingKey, value: SettingValue) -> None:
        """
        Updates a setting value and saves it safely to the nested JSON file using a lock.
        Enforces strict type validation against the default configuration schema.

        Args:
            key (SettingKey): The setting key enum to update.
            value (SettingValue): The new value for the setting.

        Raises:
            TypeError: If the provided value does not match the expected type schema.

        Returns:
            None
        """
        value = cls.validate_value(key, value)

        path: Path = cls.get_global_settings_path()

        with FileLock(path):
            data: Dict[str, Dict[str, SettingValue]] = cls._load_settings()
            category: str
            sub_key: str
            category, sub_key = key.value.split('.', 1)

            data[category][sub_key] = value

            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
