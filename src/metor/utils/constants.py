"""
Module defining application-wide constants to adhere to the DRY (Don't Repeat Yourself) principle.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a local .env file if present
load_dotenv()


class Constants:
    """Centralized constants for file names, network settings, and directory structures."""

    LOCALHOST: str = '127.0.0.1'

    # Network Constraints
    MAX_STREAM_BYTES: int = 1048576  # 1 MB Limit for Tor TCP streams (OOM Protection)
    MAX_IPC_BYTES: int = 5242880  # 5 MB Limit for local IPC streams (OOM Protection)
    IPC_RESPONSE_TIMEOUT: float = (
        5.0  # Timeout for IPC requests to prevent deadlocks over SSH Tunnels
    )

    # File Names
    DB_FILE: str = 'storage.db'
    CONTACTS_FILE: str = 'contacts.json'
    DAEMON_PORT_FILE: str = 'daemon.port'
    SETTINGS_FILE: str = 'settings.json'

    # Directory Names
    DATA_DIR: str = '.metor'
    HIDDEN_SERVICE_DIR: str = 'hidden_service'
    TOR_DATA_DIR: str = 'tor_data'

    # Key Files (Tor & Metor)
    METOR_SECRET_KEY: str = 'metor_secret.key'
    TOR_SECRET_KEY: str = 'hs_ed25519_secret_key'
    TOR_PUBLIC_KEY: str = 'hs_ed25519_public_key'
    HOSTNAME_FILE: str = 'hostname'
    TOR_WIN: str = 'tor.exe'
    TOR_UNIX: str = 'tor'

    # Application Metadata
    # Uses METOR_DATA_DIR_PARENT from environment if set, otherwise falls back to the user's home directory natively via pathlib
    DATA: Path = Path(os.getenv('METOR_DATA_DIR_PARENT', Path.home())) / DATA_DIR
