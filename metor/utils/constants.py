"""
Module defining application-wide constants to adhere to the DRY (Don't Repeat Yourself) principle.
"""

import os


class Constants:
    """Centralized constants for file names, network settings, and directory structures."""

    LOCALHOST: str = '127.0.0.1'

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
    DATA: str = os.path.join(os.path.expanduser('~'), DATA_DIR)
