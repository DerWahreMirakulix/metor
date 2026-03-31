"""
Module for managing the local Tor process, hidden services, and local proxies.
Enforces strict socket timeouts, configurable network resilience, and Tor circuit rotations.
"""

import os
import socket
import time
import socks  # type: ignore
import stem.process  # type: ignore
import stem.control  # type: ignore
import nacl.exceptions
from pathlib import Path
from typing import Tuple, Optional, Dict, Callable

from metor.core.api import DomainCode, NetworkCode, SystemCode, JsonValue
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

        self._tm_proc: Optional[stem.process.Process] = None
        self.onion: Optional[str] = None
        self.socks_port: Optional[int] = None
        self.incoming_port: Optional[int] = None
        self.control_port: Optional[int] = None

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

    def _provision_runtime_keys(self) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Injects the plaintext Ed25519 key exclusively for the Tor C-Process runtime.
        This file is shredded upon termination to maintain Data-At-Rest encryption.

        Args:
            None

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: Success flag, domain code, and params.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        try:
            decrypted_tor_key: bytes = self._km.get_decrypted_tor_key()
            tor_sec_path: Path = hs_dir / Constants.TOR_SECRET_KEY
            with tor_sec_path.open('wb') as f:
                f.write(decrypted_tor_key)
            tor_sec_path.chmod(0o600)
            return True, SystemCode.COMMAND_SUCCESS, {}
        except nacl.exceptions.CryptoError:
            return (
                False,
                NetworkCode.TOR_KEY_ERROR,
                {'error': 'Invalid master password.'},
            )
        except Exception:
            return (
                False,
                NetworkCode.TOR_KEY_ERROR,
                {'error': 'Filesystem error during key injection.'},
            )

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

    def start(self) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Starts the Tor process and sets up ports and the onion address.
        Centralizes the startup error message reporting.

        Args:
            None

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: Success flag, domain code, and params.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        data_dir: Path = Path(self._pm.get_tor_data_dir())

        self._km.generate_keys()

        success, code, params = self._provision_runtime_keys()
        if not success:
            return False, code, params

        self.socks_port = self._get_free_port()
        self.control_port = self._get_free_port()
        self.incoming_port = self._get_free_port()

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
        tor_timeout: Optional[int] = (
            None if os.name == 'nt' else Constants.UNIX_TOR_TIMEOUT
        )

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
                if (
                    self._pm.config.get_bool(SettingKey.ENABLE_TOR_LOGGING)
                    and TorManager._log_callback
                ):
                    TorManager._log_callback(f'Error starting Tor: {e}')
                if attempt < max_retries - 1:
                    time.sleep(Constants.TOR_BOOTSTRAP_RETRY_SEC)
                    continue
                else:
                    return False, NetworkCode.TOR_PROCESS_TERMINATED, {}

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

        if self._tm_proc is None:
            return (
                False,
                NetworkCode.TOR_START_FAILED,
                {'error': 'Failed to launch the Tor binary.'},
            )

        return True, SystemCode.COMMAND_SUCCESS, {}

    def stop(self) -> None:
        """
        Safely shuts down the Tor process, using force if necessary, and securely
        shreds the plaintext runtime keys to ensure complete Data-At-Rest encryption.

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

        self._shred_runtime_keys()

    def connect(self, onion: str) -> socks.socksocket:
        """
        Establishes a SOCKS5 connection to a remote Tor peer.

        Args:
            onion (str): The destination onion address.

        Returns:
            socks.socksocket: The established proxy socket.
        """
        onion_formatted = ensure_onion_format(onion)
        s: socks.socksocket = socks.socksocket()
        s.set_proxy(
            proxy_type=socks.SOCKS5, addr=Constants.LOCALHOST, port=self.socks_port
        )
        timeout: float = self._pm.config.get_float(SettingKey.TOR_TIMEOUT)
        s.settimeout(timeout)
        s.connect((onion_formatted, 80))
        return s

    def rotate_circuits(self) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Sends the NEWNYM signal to the Tor Control Port to rotate circuits.
        Enforces new network hops for subsequent connection attempts.

        Args:
            None

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: Success flag, domain code, and params.
        """
        if not self._tm_proc or not self.control_port:
            return (
                False,
                NetworkCode.RETUNNEL_FAILED,
                {'error': 'Tor process not actively running.'},
            )
        try:
            with stem.control.Controller.from_port(
                port=self.control_port
            ) as controller:
                controller.authenticate()
                controller.signal(stem.Signal.NEWNYM)
            return True, SystemCode.COMMAND_SUCCESS, {}
        except Exception as e:
            return False, NetworkCode.RETUNNEL_FAILED, {'error': str(e)}

    def get_address(self) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Retrieves the current hidden service address for the active profile.

        Args:
            None

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: A success flag, domain code, and params.
        """
        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        hostname_file: Path = hs_dir / Constants.HOSTNAME_FILE
        if hostname_file.exists():
            with hostname_file.open('r') as f:
                onion: str = f.read().strip()
                return (
                    True,
                    NetworkCode.ADDRESS_CURRENT,
                    {'profile': self._pm.profile_name, 'onion': clean_onion(onion)},
                )
        return (
            False,
            NetworkCode.ADDRESS_NOT_GENERATED,
            {'profile': self._pm.profile_name},
        )

    def generate_address(self) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Forces the generation of a new Tor hidden service address by restarting the process.

        Args:
            None

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: A success flag, domain code, and params.
        """
        if self._pm.is_daemon_running():
            return (
                False,
                NetworkCode.ADDRESS_CANT_GENERATE_RUNNING,
                {'profile': self._pm.profile_name},
            )

        success, code, params = self.start()
        if not success:
            return False, code, params
        self.stop()

        return (
            True,
            NetworkCode.ADDRESS_GENERATED,
            {'profile': self._pm.profile_name, 'onion': clean_onion(self.onion or '')},
        )
