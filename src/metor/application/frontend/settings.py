"""Narrow validated local settings service used by interactive clients."""

from metor.data import Config, SettingKey


class LocalFrontendSettings:
    """Preserves the host cascade without exposing unrestricted config or storage."""

    def __init__(self, config: Config) -> None:
        """Initializes the service around the profile configuration owner.

        Args:
            config (Config): The config input.

        Returns:
            None
        """
        self._config = config

    @staticmethod
    def _client_key(key: str) -> SettingKey:
        """Validates and resolves a frontend-readable client setting key.

        Args:
            key (str): The key input.

        Returns:
            SettingKey: The resulting value.
        """
        if not key.startswith('client.') and key not in {
            'daemon.local_auth_failure_limit',
            'daemon.live_reconnect_delay',
        }:
            raise ValueError('Setting is outside the frontend read scope.')
        return SettingKey(key)

    @staticmethod
    def _ui_key(key: str) -> str:
        """Validates a Terminal-owned presentation setting key.

        Args:
            key (str): The key input.

        Returns:
            str: The resulting text value.
        """
        if not key.startswith('ui.terminal.'):
            raise ValueError('Setting is outside the selected frontend scope.')
        return key

    def get_int(self, key: str) -> int:
        """Reads a validated client integer setting.

        Args:
            key (str): The key input.

        Returns:
            int: The resulting integer value.
        """
        return self._config.get_int(self._client_key(key))

    def get_float(self, key: str) -> float:
        """Reads a validated client floating-point setting.

        Args:
            key (str): The key input.

        Returns:
            float: The resulting numeric value.
        """
        return self._config.get_float(self._client_key(key))

    def get_namespace_str(self, key: str) -> str:
        """Reads a validated Terminal string setting.

        Args:
            key (str): The key input.

        Returns:
            str: The resulting text value.
        """
        return self._config.get_namespace_str(self._ui_key(key))

    def get_namespace_int(self, key: str) -> int:
        """Reads a validated Terminal integer setting.

        Args:
            key (str): The key input.

        Returns:
            int: The resulting integer value.
        """
        return self._config.get_namespace_int(self._ui_key(key))

    def get_namespace_bool(self, key: str) -> bool:
        """Reads a validated Terminal Boolean setting.

        Args:
            key (str): The key input.

        Returns:
            bool: Validated effective value.
        """
        return self._config.get_namespace_bool(self._ui_key(key))

    def get_namespace_float(self, key: str) -> float:
        """Reads a validated Terminal floating-point setting.

        Args:
            key (str): The key input.

        Returns:
            float: The resulting numeric value.
        """
        return self._config.get_namespace_float(self._ui_key(key))

    def set_client_value(self, key: str, value: str | int | float | bool) -> None:
        """Writes only a validated client-scoped selected-profile override.

        Args:
            key (str): The key input.
            value (str | int | float | bool): The value input.

        Returns:
            None
        """
        if not key.startswith('client.'):
            raise ValueError('Setting is outside the frontend write scope.')
        self._config.set(self._client_key(key), value)

    def set_ui_value(self, key: str, value: str | int | float | bool) -> None:
        """Writes only registered official UI values through base validation.

        Args:
            key (str): The key input.
            value (str | int | float | bool): The value input.

        Returns:
            None
        """
        self._config.set_namespace(self._ui_key(key), value)
