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
    TCP_BUFFER_SIZE: int = 4096  # Standard TCP chunk size for socket.recv
    SERVER_BACKLOG: int = 5  # Standard socket backlog for daemon IPC and listeners
    SERVER_BACKLOG_HEADLESS: int = 1  # Minimal socket backlog for ephemeral daemons

    # Tor Bootstrapping
    UNIX_TOR_TIMEOUT: int = 45  # Process launch timeout for Unix Tor binaries
    TOR_BOOTSTRAP_POLL_SEC: float = 1.0
    TOR_BOOTSTRAP_RETRY_SEC: float = 2.0
    TOR_HOSTNAME_POLL_RETRIES: int = 10
    TOR_KILL_TIMEOUT_SEC: float = 2.0  # Timeout for Tor process termination

    # Application & UI Constraints
    DEFAULT_COLS: int = 80  # Fallback terminal width
    UUID_MSG_BYTES: int = 8  # Byte length for persistent message UUIDs
    UUID_CHAT_BYTES: int = 4  # Byte length for ephemeral live-chat UUIDs

    # Thread Constraints & Timing
    THREAD_POLL_TIMEOUT: float = 1.0  # Timeout for non-blocking accept/recv loops
    WORKER_SLEEP_SEC: float = 1.0  # Standard background worker tick rate
    WORKER_SLEEP_SLOW_SEC: float = 2.0  # Slower background worker tick rate
    LOCK_SLEEP_SEC: float = 0.05  # Sleep interval for FileLock spinlocks
    INPUT_SLEEP_SEC: float = 0.02  # UI non-blocking input thread sleep
    TCP_CLOSE_LINGER_SEC: float = 0.2  # Socket linger before shutdown

    # Network Backoff Jitter (Algorithmic Constants)
    RECONNECT_BACKOFF_BASE_SEC: float = 10.0
    RECONNECT_BACKOFF_JITTER_MAX_MS: int = 2001
    RECONNECT_BACKOFF_JITTER_DIVISOR: float = 100.0

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
