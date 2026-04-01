"""
Module for managing the local Tor process, hidden services, and local proxies.
Enforces strict socket timeouts, configurable network resilience, and Tor circuit rotations.
"""

import os
import socket
import subprocess
import threading
import time
import socks  # type: ignore
import stem.process  # type: ignore
import stem.control  # type: ignore
import nacl.exceptions
from pathlib import Path
from typing import Tuple, Optional, Dict, Callable

from metor.core.api import EventType, JsonValue
from metor.data import SettingKey
from metor.data.profile import ProfileManager
from metor.utils import Constants, clean_onion, secure_shred_file, ensure_onion_format

# Local Package Imports
from metor.core.key import KeyManager


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

    def _provision_runtime_keys(
        self,
    ) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Injects the plaintext Ed25519 key exclusively for the Tor C-Process runtime.
        This file is shredded upon termination to maintain Data-At-Rest encryption.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        try:
            decrypted_tor_key: bytes = self._km.get_decrypted_tor_key()
            tor_sec_path: Path = hs_dir / Constants.TOR_SECRET_KEY
            with tor_sec_path.open('wb') as f:
                f.write(decrypted_tor_key)
            tor_sec_path.chmod(0o600)
            return True, None, {}
        except nacl.exceptions.CryptoError:
            return (
                False,
                EventType.TOR_KEY_ERROR,
                {'error': 'Invalid master password.'},
            )
        except Exception:
            return (
                False,
                EventType.TOR_KEY_ERROR,
                {'error': 'Filesystem error during key injection.'},
            )

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

    def _load_onion_address(self, hs_dir: Path) -> None:
        """
        Refreshes the current onion address from the hidden service directory.

        Args:
            hs_dir (Path): The hidden service directory.

        Returns:
            None
        """
        hostname_file: Path = hs_dir / Constants.HOSTNAME_FILE
        for _ in range(Constants.TOR_HOSTNAME_POLL_RETRIES):
            if hostname_file.exists():
                break
            time.sleep(Constants.TOR_BOOTSTRAP_POLL_SEC)

        if hostname_file.exists():
            with hostname_file.open('r') as f:
                self.onion = clean_onion(f.read().strip())
        else:
            self.onion = 'unknown'

    def _terminate_process(self) -> None:
        """
        Terminates the tracked Tor process if it is still running.

        Args:
            None

        Returns:
            None
        """
        if self._tm_proc:
            try:
                self._tm_proc.terminate()
                self._tm_proc.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
            except Exception:
                try:
                    self._tm_proc.kill()
                except Exception:
                    pass
            finally:
                self._tm_proc = None

    def _is_process_running(self) -> bool:
        """
        Checks whether the tracked Tor process is still alive.

        Args:
            None

        Returns:
            bool: True if the Tor process is alive.
        """
        return self._tm_proc is not None and self._tm_proc.poll() is None

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
            time.sleep(Constants.TOR_PROXY_READY_RETRY_SEC)
        return False

    def _get_launch_timeout(self) -> Optional[int]:
        """
        Returns a thread-safe Tor launch timeout for the current execution context.

        Args:
            None

        Returns:
            Optional[int]: The Unix timeout in the main thread, otherwise None.
        """
        if os.name == 'nt':
            return None
        if threading.current_thread() is not threading.main_thread():
            return None
        return Constants.UNIX_TOR_TIMEOUT

    def _launch_process(self) -> Tuple[bool, Optional[EventType], Dict[str, JsonValue]]:
        """
        Launches the Tor process using the current runtime ports and hidden service state.

        Args:
            None

        Returns:
            Tuple[bool, Optional[EventType], Dict[str, JsonValue]]: Success flag, optional event type, and payload.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        data_dir: Path = Path(self._pm.get_tor_data_dir())

        self._reserve_ports()

        config: Dict[str, str] = {
            'SocksPort': str(self.socks_port),
            'ControlPort': str(self.control_port),
            'CookieAuthentication': '1',
            'DataDirectory': str(data_dir),
            'HiddenServiceDir': str(hs_dir),
            'HiddenServicePort': f'80 {Constants.LOCALHOST}:{self.incoming_port}',
        }

        tor_cmd: str = (
            str(Constants.DATA / Constants.TOR_WIN)
            if os.name == 'nt'
            else Constants.TOR_UNIX
        )
        tor_timeout: Optional[int] = self._get_launch_timeout()

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
        last_error: str = 'Unknown Tor launch error.'
        self._tm_proc = None

        for attempt in range(max_retries):
            try:
                self._tm_proc = stem.process.launch_tor_with_config(
                    config=config,
                    timeout=tor_timeout,
                    take_ownership=True,
                    tor_cmd=tor_cmd,
                    init_msg_handler=print_tor_output,
                )

                pid_file: Path = data_dir / 'tor.pid'
                with pid_file.open('w') as f:
                    f.write(str(self._tm_proc.pid))

                break
            except OSError as e:
                last_error = str(e).strip() or 'Unknown Tor launch error.'
                if (
                    self._pm.config.get_bool(SettingKey.ENABLE_TOR_LOGGING)
                    and TorManager._log_callback
                ):
                    TorManager._log_callback(f'Error starting Tor: {e}')
                if attempt < max_retries - 1:
                    time.sleep(Constants.TOR_BOOTSTRAP_RETRY_SEC)
                    continue
                return (
                    False,
                    EventType.TOR_PROCESS_TERMINATED,
                    {'error': f'Failed to launch Tor: {last_error}'},
                )

        self._load_onion_address(hs_dir)

        if self._tm_proc is None:
            return (
                False,
                EventType.TOR_START_FAILED,
                {'error': 'Failed to launch the Tor binary.'},
            )

        if not self._wait_for_proxy_listener():
            self._terminate_process()
            return (
                False,
                EventType.TOR_PROCESS_TERMINATED,
                {'error': 'Tor SOCKS proxy did not become ready.'},
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

        success, event_type, params = self._provision_runtime_keys()
        if not success:
            return False, event_type, params

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

        error: str = str(params.get('error') or fallback_error)
        return False, EventType.RETUNNEL_FAILED, {'error': error}

    def _shred_runtime_keys(self) -> None:
        """
        Securely shreds the plaintext runtime keys from the filesystem.
        Leaves the public key and encrypted master key intact.

        Args:
            None

        Returns:
            None
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        secure_shred_file(hs_dir / Constants.TOR_SECRET_KEY)

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

            success, code, params = self._provision_runtime_keys()
            if not success:
                return False, code, params

            self.socks_port = self._get_free_port()
            self.control_port = self._get_free_port()
            self.incoming_port = self._get_free_port()
            return self._launch_process()

    def stop(self) -> None:
        """
        Safely shuts down the Tor process, using force if necessary, and securely
        shreds the plaintext runtime keys to ensure complete Data-At-Rest encryption.

        Args:
            None

        Returns:
            None
        """
        with self._process_lock:
            self._terminate_process()
            self._shred_runtime_keys()

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

            last_error: str = 'Unknown Tor control error.'
            for attempt in range(Constants.TOR_CONTROL_RETRY_ATTEMPTS):
                try:
                    with stem.control.Controller.from_port(
                        port=self.control_port
                    ) as controller:
                        controller.authenticate()
                        controller.signal(stem.Signal.NEWNYM)

                    if not self._wait_for_proxy_listener():
                        return self._recover_runtime(
                            'Tor SOCKS proxy unavailable after circuit rotation.'
                        )

                    return True, None, {}
                except Exception as e:
                    last_error = str(e).strip() or 'Unknown Tor control error.'
                    if attempt < Constants.TOR_CONTROL_RETRY_ATTEMPTS - 1:
                        time.sleep(Constants.TOR_CONTROL_RETRY_SEC)

            return self._recover_runtime(last_error)

    def get_address(self) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """
        Retrieves the current hidden service address for the active profile.

        Args:
            None

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: A success flag, strict event type, and payload.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
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

        success, event_type, params = self.start()
        if not success:
            return False, event_type or EventType.TOR_START_FAILED, params
        self.stop()

        return (
            True,
            EventType.ADDRESS_GENERATED,
            {'profile': self._pm.profile_name, 'onion': clean_onion(self.onion or '')},
        )
