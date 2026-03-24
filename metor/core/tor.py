"""
Module for managing the local Tor process, hidden services, and local proxies.
"""

import os
import socket
import time
import socks
import stem.process
import sys
from typing import Tuple, Optional, Any

from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey, Settings
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion

# Local Package Imports
from metor.core.key import KeyManager


class TorManager:
    """Manages the lifecycle of the Tor process and its related hidden service configuration."""

    def __init__(self, pm: ProfileManager, km: KeyManager) -> None:
        """
        Initializes the TorManager.

        Args:
            pm (ProfileManager): The profile manager instance.
            km (KeyManager): The key manager instance for cryptographic operations.
        """
        self._pm: ProfileManager = pm
        self._km: KeyManager = km

        self._tm_proc: Optional[Any] = None
        self.onion: Optional[str] = None
        self.socks_port: Optional[int] = None
        self.incoming_port: Optional[int] = None
        self.control_port: Optional[int] = None

    def _get_free_port(self) -> int:
        """
        Finds and returns an available local network port.

        Returns:
            int: An available port number.
        """
        s: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((Constants.LOCALHOST, 0))
        port: int = s.getsockname()[1]
        s.close()
        return port

    def start(self) -> bool:
        """
        Starts the Tor process and sets up ports and the onion address.

        Returns:
            bool: True if the Tor process started successfully, False otherwise.
        """
        hs_dir: str = self._pm.get_hidden_service_dir()
        data_dir: str = self._pm.get_tor_data_dir()

        self._km.generate_keys()

        self.socks_port = self._get_free_port()
        self.control_port = self._get_free_port()
        self.incoming_port = self._get_free_port()

        config: dict[str, str] = {
            'SocksPort': str(self.socks_port),
            'ControlPort': str(self.control_port),
            'CookieAuthentication': '1',
            'DataDirectory': data_dir,
            'HiddenServiceDir': hs_dir,
            'HiddenServicePort': f'80 {Constants.LOCALHOST}:{self.incoming_port}',
        }

        tor_cmd: str = (
            str(Constants.DATA / Constants.TOR_WIN)
            if os.name == 'nt'
            else Constants.TOR_UNIX
        )
        tor_timeout: Optional[int] = None if os.name == 'nt' else 45

        def print_tor_output(line: str) -> None:
            """Handles and formats Tor console output if logging is enabled."""
            if Settings.get(SettingKey.ENABLE_TOR_LOGGING):
                sys.stdout.write(f'\r\033[K{Theme.CYAN}[TOR-LOG]{Theme.RESET} {line}\n')
                sys.stdout.flush()

        max_retries: int = Settings.get(SettingKey.MAX_TOR_RETRIES)
        for attempt in range(max_retries):
            try:
                self._tm_proc = stem.process.launch_tor_with_config(
                    config=config,
                    timeout=tor_timeout,
                    take_ownership=True,
                    tor_cmd=tor_cmd,
                    init_msg_handler=print_tor_output,
                )
                break
            except OSError as e:
                if Settings.get(SettingKey.ENABLE_TOR_LOGGING):
                    print(f'Error starting Tor: {e}')
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return False

        # Wait for hostname file
        hostname_file: str = os.path.join(hs_dir, Constants.HOSTNAME_FILE)
        for _ in range(10):
            if os.path.exists(hostname_file):
                break
            time.sleep(1)

        if os.path.exists(hostname_file):
            with open(hostname_file, 'r') as f:
                self.onion = f.read().strip()
        else:
            self.onion = 'unknown'

        return self._tm_proc is not None

    def stop(self) -> None:
        """Safely shuts down the Tor process, using force if necessary."""
        if self._tm_proc:
            try:
                self._tm_proc.terminate()
                self._tm_proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._tm_proc.kill()
                except Exception:
                    pass
            finally:
                self._tm_proc = None

    def connect(self, onion: str) -> socks.socksocket:
        """
        Establishes a SOCKS5 connection to a remote Tor peer.

        Args:
            onion (str): The destination onion address.

        Returns:
            socks.socksocket: The established proxy socket.
        """
        s: socks.socksocket = socks.socksocket()
        s.set_proxy(
            proxy_type=socks.SOCKS5, addr=Constants.LOCALHOST, port=self.socks_port
        )
        s.settimeout(10)
        s.connect((onion, 80))
        s.settimeout(None)
        return s

    def get_address(self) -> Tuple[bool, str]:
        """
        Retrieves the current hidden service address for the active profile.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        hs_dir: str = self._pm.get_hidden_service_dir()
        hostname_file: str = os.path.join(hs_dir, Constants.HOSTNAME_FILE)
        if os.path.exists(hostname_file):
            with open(hostname_file, 'r') as f:
                onion: str = f.read().strip()
                return (
                    True,
                    f"Current onion address for profile '{self._pm.profile_name}': {Theme.YELLOW}{clean_onion(onion)}{Theme.RESET}.onion",
                )
        return (
            False,
            f"No onion address generated for profile '{self._pm.profile_name}' yet. Simply start the daemon or use 'metor address generate'.",
        )

    def generate_address(self) -> Tuple[bool, str]:
        """
        Forces the generation of a new Tor hidden service address by restarting the process.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        if self._pm.is_daemon_running():
            return (
                False,
                f"Changing the address for profile '{self._pm.profile_name}' is not possible while a daemon is running.",
            )

        success: bool = self.start()
        if not success:
            return (
                False,
                f"Failed to start Tor for profile '{self._pm.profile_name}'. Please check your Tor configuration and logs.",
            )
        self.stop()

        return (
            True,
            f"New onion address generated for profile '{self._pm.profile_name}': {Theme.YELLOW}{clean_onion(self.onion or '')}{Theme.RESET}.onion",
        )
