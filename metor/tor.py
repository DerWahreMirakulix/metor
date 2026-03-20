import os
import socket
import time
import socks
import stem.process
import sys

from metor.profile import ProfileManager
from metor.key import KeyManager
from metor.settings import Settings
from metor.utils import clean_onion

class TorManager:
    """Manages the Tor process, hidden services, and local proxies."""
    
    def __init__(self, pm: ProfileManager, km: KeyManager):
        self.pm = pm
        self.km = km
        self.tm_proc = None
        self.onion = None
        self.socks_port = None
        self.incoming_port = None
        self.control_port = None

    def _get_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def start(self):
        """Start Tor and set up ports/onion address."""
        hs_dir = self.pm.get_hidden_service_dir()
        data_dir = self.pm.get_tor_data_dir()
        
        self.km.generate_keys()

        self.socks_port = self._get_free_port()
        self.control_port = self._get_free_port()
        self.incoming_port = self._get_free_port()
        
        config = {
            'SocksPort': str(self.socks_port),
            'ControlPort': str(self.control_port),
            'CookieAuthentication': '1',
            'DataDirectory': data_dir,      
            'HiddenServiceDir': hs_dir,
            'HiddenServicePort': f'80 127.0.0.1:{self.incoming_port}'
        }
        
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        tor_cmd = os.path.join(pkg_dir, "tor.exe") if os.name == "nt" else "tor"
        tor_timeout = None if os.name == "nt" else 45
        
        def print_tor_output(line):
            if Settings.ENABLE_TOR_LOGGING:
                sys.stdout.write(f"\r\033[K{Settings.CYAN}[TOR-LOG]{Settings.RESET} {line}\n")
                sys.stdout.flush()

        for attempt in range(Settings.MAX_TOR_RETRIES):
            try:
                self.tm_proc = stem.process.launch_tor_with_config(
                    config=config, timeout=tor_timeout, take_ownership=True,
                    tor_cmd=tor_cmd, init_msg_handler=print_tor_output
                )
                break 
            except OSError as e:
                if Settings.ENABLE_TOR_LOGGING:
                    print(f"Error starting Tor: {e}")
                if attempt < Settings.MAX_TOR_RETRIES - 1:
                    time.sleep(2)
                    continue
                else:
                    return False

        # Wait for hostname file
        hostname_file = os.path.join(hs_dir, "hostname")
        for _ in range(10):
            if os.path.exists(hostname_file): break
            time.sleep(1)
            
        if os.path.exists(hostname_file):
            with open(hostname_file, "r") as f:
                self.onion = f.read().strip()
        else:
            self.onion = "unknown"
            
        return self.tm_proc is not None

    def stop(self):
        """Safely shuts down the Tor process, using force if necessary."""
        if self.tm_proc:
            try:
                self.tm_proc.terminate()
                self.tm_proc.wait(timeout=2.0) # politely ask Tor to stop
            except Exception:
                try:
                    self.tm_proc.kill() # force kill if it doesn't stop
                except Exception:
                    pass
            finally:
                self.tm_proc = None

    def connect(self, onion):
        """Establish SOCKS5 connection to remote peer."""
        s = socks.socksocket()
        s.set_proxy(proxy_type=socks.SOCKS5, addr='127.0.0.1', port=self.socks_port)
        s.settimeout(10)
        s.connect((onion, 80))
        s.settimeout(None)
        return s

    def get_address(self):
        hs_dir = self.pm.get_hidden_service_dir()
        hostname_file = os.path.join(hs_dir, "hostname")
        if os.path.exists(hostname_file):
            with open(hostname_file, "r") as f:
                onion = f.read().strip()
                return True, f"Current onion address for profile '{self.pm.profile_name}': {Settings.YELLOW}{clean_onion(onion)}{Settings.RESET}.onion"
        return False, f"No onion address generated for profile '{self.pm.profile_name}' yet. Simply start the daemon or use 'metor address generate'."

    def generate_address(self):
        """Force generation of a new address (starts/stops Tor)."""
        if self.pm.is_daemon_running():
            return False, f"Changing the address for profile '{self.pm.profile_name}' is not possible while a daemon is running"

        success = self.start()
        if not success:
            return False, f"Failed to start Tor for profile '{self.pm.profile_name}'. Please check your Tor configuration and logs."
        self.stop()
        
        return True, f"New onion address generated for profile '{self.pm.profile_name}': {Settings.YELLOW}{clean_onion(self.onion)}{Settings.RESET}.onion"
