"""
Module defining application-wide constants to adhere to the DRY (Don't Repeat Yourself) principle.
"""

import os
from pathlib import Path


def _load_local_dotenv() -> None:
    """
    Loads environment variables from a local `.env` file when python-dotenv exists.

    Args:
        None

    Returns:
        None
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv()


_load_local_dotenv()


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
    TOR_CONTROL_RETRY_SEC: float = 1.0  # Delay between Tor control-port retry attempts
    TOR_PROXY_READY_RETRY_SEC: float = (
        1.0  # Delay between local Tor SOCKS readiness probes
    )
    TOR_HOSTNAME_POLL_RETRIES: int = 10
    TOR_CONTROL_RETRY_ATTEMPTS: int = 5  # Retry budget for NEWNYM control calls
    TOR_PROXY_READY_ATTEMPTS: int = (
        5  # Retry budget for local Tor SOCKS readiness checks
    )
    TOR_PROXY_READY_TIMEOUT_SEC: float = (
        1.0  # Timeout for local SOCKS readiness probe connections
    )
    TOR_KILL_TIMEOUT_SEC: float = 2.0  # Timeout for Tor process termination

    # Application & UI Constraints
    DEFAULT_COLS: int = 80  # Fallback terminal width
    UUID_MSG_BYTES: int = 8  # Byte length for persistent message UUIDs
    UUID_CHAT_BYTES: int = 4  # Byte length for ephemeral live-chat UUIDs
    LIVE_MSG_DEDUPE_CACHE_SIZE: int = (
        256  # Per-peer cache size for recent live message IDs
    )
    SESSION_AUTH_KEY_BYTES: int = (
        32  # Argon2-derived key length for IPC session-auth proofs
    )
    SESSION_AUTH_CHALLENGE_BYTES: int = (
        32  # Random challenge length for one IPC session-auth proof round
    )
    TOR_HANDSHAKE_CHALLENGE_BYTES: int = (
        32  # Random challenge length for one Tor peer-auth proof round
    )
    TOR_V3_ONION_ADDRESS_LENGTH: int = 56  # Base32 chars in one v3 onion address
    TOR_V3_PUBLIC_KEY_BYTES: int = 32  # Ed25519 public key bytes embedded in v3 onions
    TOR_V3_CHECKSUM_BYTES: int = 2  # Checksum bytes embedded in v3 onions
    TOR_V3_VERSION_BYTE: int = 3  # Tor v3 onion address version marker
    INPUT_SELECT_TIMEOUT_SEC: float = 0.0  # Non-blocking POSIX stdin poll

    # Thread Constraints & Timing
    THREAD_POLL_TIMEOUT: float = 1.0  # Timeout for non-blocking accept/recv loops
    LISTENER_READY_TIMEOUT: float = (
        5.0  # Startup wait for inbound listener bind/listen readiness
    )
    WORKER_SLEEP_SEC: float = 1.0  # Standard background worker tick rate
    WORKER_SLEEP_SLOW_SEC: float = 2.0  # Slower background worker tick rate
    LOCK_SLEEP_SEC: float = 0.05  # Sleep interval for FileLock spinlocks
    FILE_LOCK_TIMEOUT_SEC: float = 5.0  # Maximum wait for acquiring a file lock
    FILE_LOCK_STALE_AGE_SEC: float = (
        10.0  # Age threshold for considering a lock file stale
    )
    INPUT_SLEEP_SEC: float = 0.02  # UI non-blocking input thread sleep
    TCP_CLOSE_LINGER_SEC: float = 0.2  # Socket linger before shutdown
    IPC_AUTH_FAILURE_LIMIT: int = (
        3  # Maximum invalid local auth attempts per IPC session before disconnect
    )
    MUTUAL_CONNECT_RACE_WINDOW_SEC: float = 5.0  # Short grace window to recognize the winning inbound side of a simultaneous connect race
    PENDING_EXPIRY_FEEDBACK_WINDOW_SEC: float = 30.0  # How long a recently expired pending live request should produce a dedicated accept-expired UI hint

    # Network Backoff Jitter (Algorithmic Constants)
    LIVE_RECONNECT_JITTER_MAX_MS: int = 2001
    LIVE_RECONNECT_JITTER_DIVISOR: float = 100.0

    # File Names
    DB_FILE: str = 'storage.db'
    DB_RUNTIME_FILE: str = 'storage.runtime.db'
    CONTACTS_FILE: str = 'contacts.json'
    DAEMON_PORT_FILE: str = 'daemon.port'
    DAEMON_PID_FILE: str = 'daemon.pid'
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
    TOR_PATH: str = os.getenv('METOR_TOR_PATH', '').strip()
