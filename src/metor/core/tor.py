"""
Module for managing the local Tor process, hidden services, and local proxies.
Enforces strict socket timeouts, configurable network resilience, and Tor circuit rotations.
"""

import locale
import os
import socket
import subprocess
import threading
import time
import socks
import nacl.exceptions
from pathlib import Path
from typing import Tuple, Optional, Dict, Callable

from metor.core.api import EventType, JsonValue, RuntimeErrorCode
from metor.data import SettingKey
from metor.data.profile import ProfileManager
from metor.utils import (
    Constants,
    ProcessManager,
    open_private_binary_file,
)
from metor.shared import clean_onion, ensure_onion_format

# Local Package Imports
from metor.core.key import KeyManager
from metor.core.tor_control import OnionServiceControl
from metor.core.tor_process import launch_tor


def _torrc_path(path: Path) -> str:
    """Quote one filesystem path as an ASCII torrc value for the native launcher.

    Tor treats an unquoted hash as a comment. Octal escapes preserve control
    characters and filesystem bytes in the ASCII configuration sent to Tor.
    The Windows Tor Expert Bundle opens paths using the system ANSI code page.
    """
    if _is_windows():
        encoding = locale.getencoding()
        encoded = str(path).encode(encoding)
        if encoded.decode(encoding) != str(path):
            raise UnicodeError('Tor cannot represent the profile directory.')
    else:
        encoded = os.fsencode(path)
    escaped = ''.join(
        chr(byte)
        if 0x20 <= byte <= 0x7E and chr(byte) not in '"\\'
        else f'\\{byte:03o}'
        for byte in encoded
    )
    return f'"{escaped}"'


def _is_windows() -> bool:
    """Returns whether the running host uses the Windows process model.

    Args:
        None

    Returns:
        bool: True on Windows.
    """
    return os.name == 'nt'


class TorManager:
    """Manages the lifecycle of the Tor process and its related hidden service configuration."""

    _log_callback: Optional[Callable[[str], None]] = None

    @classmethod
    def set_log_callback(cls, callback: Callable[[str], None]) -> None:
        """
        Sets a global callback for Tor logging to keep the Core layer UI-agnostic.

        Args:
            callback (Callable[[str], None]): The logging function.

        Returns:
            None
        """
        cls._log_callback = callback

    def __init__(self, pm: ProfileManager, km: KeyManager) -> None:
        """
        Initializes the TorManager.

        Args:
            pm (ProfileManager): The profile manager instance.
            km (KeyManager): The key manager instance for cryptographic operations.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._km: KeyManager = km

        self._tm_proc: Optional[subprocess.Popen[bytes]] = None
        self._control: OnionServiceControl | None = None
        self._cancelled = threading.Event()
        self.onion: Optional[str] = None
        self.socks_port: Optional[int] = None
        self.incoming_port: Optional[int] = None
        self.control_port: Optional[int] = None
        self._process_lock: threading.RLock = threading.RLock()

    def _get_free_port(self) -> int:
        """
        Finds and returns an available local network port.

        Args:
            None

        Returns:
            int: An available port number.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((Constants.LOCALHOST, 0))
            return int(s.getsockname()[1])

    def cancel_start(self) -> None:
        """Wake a currently bootstrapping Tor process from another thread."""
        self._cancelled.set()

    def _own_process(self, process: subprocess.Popen[bytes]) -> None:
        """Retain the child even if bootstrap or emergency cleanup fails."""
        self._tm_proc = process

    def _register_service(self) -> None:
        assert self.control_port is not None and self.incoming_port is not None
        self._control = OnionServiceControl(self.control_port)
        self._control.authenticate(
            self._pm.paths.get_tor_data_dir() / 'control_auth_cookie'
        )
        public = self._km.get_metor_key()[-32:]
        self.onion = self._control.register(
            self._km.get_decrypted_tor_key(), public, self.incoming_port
        )
        with open_private_binary_file(
            self._pm.paths.get_hidden_service_dir() / Constants.HOSTNAME_FILE
        ) as handle:
            handle.write((self.onion + '.onion\n').encode('ascii'))

    def _reserve_ports(self) -> None:
        """
        Allocates the Tor runtime ports once and preserves them across restarts.

        Args:
            None

        Returns:
            None
        """
        if self.socks_port is None:
            self.socks_port = self._get_free_port()
        if self.control_port is None:
            self.control_port = self._get_free_port()
        if self.incoming_port is None:
            self.incoming_port = self._get_free_port()

    def _refresh_proxy_ports(self) -> None:
        """
        Allocates fresh local Tor proxy ports while preserving the inbound listener.

        Args:
            None

        Returns:
            None
        """
        self.socks_port = self._get_free_port()
        self.control_port = self._get_free_port()

    def _terminate_process(self) -> None:
        """
        Terminates the tracked Tor process and confirms its bounded exit.

        Args:
            None

        Raises:
            RuntimeError: If neither terminate nor kill produces a confirmed exit.

        Returns:
            None
        """
        try:
            if self._control is not None:
                self._control.close()
                self._control = None
        finally:
            self._terminate_child()

    def _terminate_child(self) -> None:
        process = self._tm_proc
        if process is None:
            return
        if process.poll() is not None:
            self._tm_proc = None
            return

        try:
            process.terminate()
            process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        except Exception:
            if process.poll() is not None:
                self._tm_proc = None
                return
            try:
                process.kill()
                process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
            except Exception as exc:
                if process.poll() is not None:
                    self._tm_proc = None
                    return
                raise RuntimeError(
                    'Tor process termination could not be confirmed.'
                ) from exc

        self._tm_proc = None

    def _is_process_running(self) -> bool:
        """
        Checks whether the tracked Tor process is still alive.

        Args:
            None

        Returns:
            bool: True if the Tor process is alive.
        """
        return (
            self._tm_proc is not None
            and self._tm_proc.poll() is None
            and self._control is not None
            and self._control.is_alive()
        )

    def _is_proxy_listener_ready(self) -> bool:
        """
        Probes the local Tor SOCKS port to verify that it accepts connections.

        Args:
            None

        Returns:
            bool: True if the SOCKS listener is reachable.
        """
        if self.socks_port is None:
            return False

        try:
            with socket.create_connection(
                (Constants.LOCALHOST, self.socks_port),
                timeout=Constants.TOR_PROXY_READY_TIMEOUT_SEC,
            ):
                return True
        except OSError:
            return False

    def _wait_for_proxy_listener(self) -> bool:
        """
        Waits briefly for the local Tor SOCKS listener to become reachable.

        Args:
            None

        Returns:
            bool: True if the SOCKS listener became reachable.
        """
        for _ in range(Constants.TOR_PROXY_READY_ATTEMPTS):
            if self._is_process_running() and self._is_proxy_listener_ready():
                return True
            if self._cancelled.wait(Constants.TOR_PROXY_READY_RETRY_SEC):
                return False
        return False

    @staticmethod
    def _resolve_tor_command() -> str:
        """
        Resolves the Tor executable command for the current host environment.

        Args:
            None

        Returns:
            str: The Tor executable path or command name.
        """
        tor_cmd_override: str = Constants.TOR_PATH
        if tor_cmd_override:
            configured_path = Path(tor_cmd_override)
            if not configured_path.is_absolute():
                raise FileNotFoundError('METOR_TOR_PATH must be an absolute path.')
            candidate = configured_path.resolve()
        elif _is_windows():
            candidate = (Constants.DATA / Constants.TOR_WIN).resolve()
        else:
            candidate = Constants.TOR_UNIX_DEFAULT_PATH.resolve()

        if not candidate.is_file():
            raise FileNotFoundError('The configured Tor executable does not exist.')
        if not _is_windows() and not os.access(candidate, os.X_OK):
            raise PermissionError('The configured Tor executable is not executable.')
        return str(candidate)

    def _launch_process(self) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Launches the Tor process using the current runtime ports and hidden service state.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        data_dir: Path = self._pm.paths.get_tor_data_dir()

        self._reserve_ports()

        try:
            tor_data_path = _torrc_path(data_dir)
        except UnicodeError:
            return (
                False,
                EventType.TOR_START_FAILED,
                {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
            )
        config: Dict[str, str] = {
            'SocksPort': str(self.socks_port),
            'ControlPort': str(self.control_port),
            'CookieAuthentication': '1',
            'DataDirectory': tor_data_path,
        }

        tor_cmd: str = self._resolve_tor_command()

        def print_tor_output(line: str) -> None:
            """
            Handles and formats Tor console output if logging is enabled.

            Args:
                line (str): The logged string line from the Tor process.

            Returns:
                None
            """
            if (
                self._pm.config.get_bool(SettingKey.ENABLE_TOR_LOGGING)
                and TorManager._log_callback
            ):
                TorManager._log_callback(line)

        max_retries: int = self._pm.config.get_int(SettingKey.MAX_TOR_RETRIES)
        if self._tm_proc is not None:
            raise RuntimeError('An existing Tor process still requires release.')

        for attempt in range(max_retries):
            try:
                self._tm_proc = launch_tor(
                    config=config,
                    tor_cmd=tor_cmd,
                    init_msg_handler=print_tor_output,
                    cancelled=self._cancelled.is_set,
                    process_owner=self._own_process,
                )
                pid_file: Path = data_dir / 'tor.pid'
                identity_payload = ProcessManager.process_identity_payload(
                    self._tm_proc.pid,
                    self._pm.profile_name,
                    role=Constants.PROCESS_ROLE_TOR,
                    executable=Path(tor_cmd),
                ).encode('utf-8')
                with open_private_binary_file(pid_file) as f:
                    f.write(identity_payload)
                self._register_service()
                break
            except nacl.exceptions.CryptoError:
                self._terminate_process()
                return False, EventType.TOR_KEY_DECRYPT_FAILED, {}
            except (OSError, ValueError):
                if self._tm_proc is not None:
                    try:
                        self._terminate_process()
                    except RuntimeError:
                        return (
                            False,
                            EventType.TOR_START_FAILED,
                            {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
                        )
                if (
                    self._pm.config.get_bool(SettingKey.ENABLE_TOR_LOGGING)
                    and TorManager._log_callback
                ):
                    TorManager._log_callback('Tor launch failed.')
                if attempt < max_retries - 1 and not self._cancelled.wait(
                    Constants.TOR_BOOTSTRAP_RETRY_SEC
                ):
                    continue
                return (
                    False,
                    EventType.TOR_START_FAILED,
                    {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
                )

        if self._tm_proc is None:
            return (
                False,
                EventType.TOR_START_FAILED,
                {'error_code': RuntimeErrorCode.TOR_BINARY_LAUNCH_FAILED},
            )

        if not self._wait_for_proxy_listener():
            self._terminate_process()
            return (
                False,
                EventType.TOR_PROCESS_TERMINATED,
                {'error_code': RuntimeErrorCode.TOR_PROXY_NOT_READY},
            )

        return True, None, {}

    def _restart_process(
        self,
    ) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Restarts the Tor process while preserving the inbound listener port.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        self._terminate_process()
        self._refresh_proxy_ports()

        return self._launch_process()

    def _recover_runtime(
        self, fallback_error: str
    ) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Restarts Tor and converts any failure into a retunnel-safe diagnostic.

        Args:
            fallback_error (str): The fallback error if restart yields no details.

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        success, _, params = self._restart_process()
        if success:
            return True, None, {}

        if params:
            return False, EventType.RETUNNEL_FAILED, params

        return (
            False,
            EventType.RETUNNEL_FAILED,
            {
                'error_code': RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED,
                'error_detail': fallback_error,
            },
        )

    def start(self) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Starts the Tor process and sets up ports and the onion address.
        Centralizes the startup error message reporting.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        with self._process_lock:
            self._km.generate_keys()

            self.socks_port = self._get_free_port()
            self.control_port = self._get_free_port()
            self.incoming_port = self._get_free_port()
            return self._launch_process()

    def stop(self) -> None:
        """
        Close the owning control connection and confirm the Tor process has exited.

        Args:
            None

        Raises:
            Exception: If releasing the control session or Tor child fails.

        Returns:
            None
        """
        self.cancel_start()
        with self._process_lock:
            self._terminate_process()
            self._cancelled.clear()

    def ensure_proxy_ready(
        self,
    ) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Restores Tor runtime state when the tracked process or SOCKS proxy is unavailable.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        with self._process_lock:
            if self._wait_for_proxy_listener():
                return True, None, {}
            return self._restart_process()

    def connect(self, onion: str) -> socks.socksocket:
        """
        Establishes a SOCKS5 connection to a remote Tor peer.

        Args:
            onion (str): The destination onion address.

        Returns:
            socks.socksocket: The established proxy socket.
        """
        success, _, params = self.ensure_proxy_ready()
        if not success:
            raise ConnectionError(
                str(params.get('error') or 'Tor SOCKS proxy unavailable.')
            )

        onion_formatted = ensure_onion_format(onion)
        s: socks.socksocket = socks.socksocket()
        s.set_proxy(
            proxy_type=socks.SOCKS5, addr=Constants.LOCALHOST, port=self.socks_port
        )
        timeout: float = self._pm.config.get_float(SettingKey.TOR_TIMEOUT)
        s.settimeout(timeout)
        s.connect((onion_formatted, 80))
        return s

    def rotate_circuits(
        self,
    ) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Sends the NEWNYM signal to the Tor Control Port to rotate circuits.
        Enforces new network hops for subsequent connection attempts.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        with self._process_lock:
            if not self._is_process_running() or not self.control_port:
                return self._recover_runtime('Tor process not actively running.')

            for attempt in range(Constants.TOR_CONTROL_RETRY_ATTEMPTS):
                try:
                    if self._control is None:
                        raise OSError('Tor control session is unavailable.')
                    self._control.rotate()

                    if not self._wait_for_proxy_listener():
                        return self._recover_runtime(
                            'Tor SOCKS proxy unavailable after circuit rotation.'
                        )

                    return True, None, {}
                except Exception:
                    if attempt < Constants.TOR_CONTROL_RETRY_ATTEMPTS - 1:
                        time.sleep(Constants.TOR_CONTROL_RETRY_SEC)

            return self._recover_runtime('Tor control operation failed.')

    def get_address(self) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """
        Retrieves the current hidden service address for the active profile.

        Args:
            None

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: A success flag, strict event type, and payload.
        """
        hs_dir: Path = self._pm.paths.get_hidden_service_dir()
        hostname_file: Path = hs_dir / Constants.HOSTNAME_FILE
        if hostname_file.exists():
            with hostname_file.open('r') as f:
                onion: str = f.read().strip()
                return (
                    True,
                    EventType.ADDRESS_CURRENT,
                    {'profile': self._pm.profile_name, 'onion': clean_onion(onion)},
                )
        return (
            False,
            EventType.ADDRESS_NOT_GENERATED,
            {'profile': self._pm.profile_name},
        )

    def generate_address(self) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """
        Forces the generation of a new Tor hidden service address by restarting the process.

        Args:
            None

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: A success flag, strict event type, and payload.
        """
        if self._pm.is_daemon_running():
            return (
                False,
                EventType.ADDRESS_CANT_GENERATE_RUNNING,
                {'profile': self._pm.profile_name},
            )

        try:
            success, event_type, params = self.start()
            if not success:
                return False, event_type or EventType.TOR_START_FAILED, params
        finally:
            self.stop()

        return (
            True,
            EventType.ADDRESS_GENERATED,
            {'profile': self._pm.profile_name, 'onion': clean_onion(self.onion or '')},
        )
