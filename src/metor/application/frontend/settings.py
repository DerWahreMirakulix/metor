"""Narrow validated local settings service used by interactive clients."""

from metor.data import Config, SettingKey


class LocalFrontendSettings:
    """Preserves the host cascade without exposing unrestricted config or storage."""

    def __init__(self, config: Config) -> None:
        self._config = config

    @staticmethod
    def _client_key(key: str) -> SettingKey:
        if not key.startswith('client.') and key not in {
            'daemon.local_auth_failure_limit',
            'daemon.live_reconnect_delay',
        }:
            raise ValueError('Setting is outside the frontend read scope.')
        return SettingKey(key)

    @staticmethod
    def _ui_key(key: str) -> str:
        if not key.startswith('ui.terminal.'):
            raise ValueError('Setting is outside the selected frontend scope.')
        return key

    def get_int(self, key: str) -> int:
        return self._config.get_int(self._client_key(key))

    def get_float(self, key: str) -> float:
        return self._config.get_float(self._client_key(key))

    def get_namespace_str(self, key: str) -> str:
        return self._config.get_namespace_str(self._ui_key(key))

    def get_namespace_int(self, key: str) -> int:
        return self._config.get_namespace_int(self._ui_key(key))

    def get_namespace_bool(self, key: str) -> bool:
        return self._config.get_namespace_bool(self._ui_key(key))

    def get_namespace_float(self, key: str) -> float:
        return self._config.get_namespace_float(self._ui_key(key))

    def set_client_value(self, key: str, value: str | int | float | bool) -> None:
        """Writes only a validated client-scoped selected-profile override."""
        if not key.startswith('client.'):
            raise ValueError('Setting is outside the frontend write scope.')
        self._config.set(self._client_key(key), value)

    def set_ui_value(self, key: str, value: str | int | float | bool) -> None:
        """Writes only registered official UI values through base validation."""
        self._config.set_namespace(self._ui_key(key), value)
