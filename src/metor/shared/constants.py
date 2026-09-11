"""Pure SDK contract bounds and shared identity/proof constants."""


class Constants:
    """Deterministic limits shared by protocol producers and consumers."""

    LOCALHOST: str = '127.0.0.1'
    MAX_STREAM_BYTES: int = 1048576  # 1 MB Limit for Tor TCP streams (OOM Protection)
    MAX_IPC_BYTES: int = 5242880  # 5 MB Limit for local IPC streams (OOM Protection)
    VOICE_CHUNK_MAX_BYTES: int = 65536
    DEFAULT_RETAINED_PAGE_SIZE: int = 50
    MAX_RETAINED_PAGE_SIZE: int = 200
    VOICE_CODEC_MAX_CHARS: int = 64
    VOICE_PRESSURE_PERCENT: int = 90
    MESSAGE_ID_MAX_CHARS: int = 128
    TCP_BUFFER_SIZE: int = 4096  # Standard TCP chunk size for socket.recv
    MAX_PENDING_IPC_REQUESTS: int = 128
    MAX_RESPONSES_PER_REQUEST: int = 32
    MAX_CLIENT_EVENT_QUEUE: int = 256
    MAX_CLIENT_CALLBACK_GENERATIONS: int = 2
    SESSION_AUTH_KEY_BYTES: int = (
        32  # Argon2-derived key length for IPC session-auth proofs
    )
    SESSION_AUTH_CHALLENGE_BYTES: int = (
        32  # Random challenge length for one IPC session-auth proof round
    )
    TOR_V3_ONION_ADDRESS_LENGTH: int = 56  # Base32 chars in one v3 onion address
    TOR_V3_PUBLIC_KEY_BYTES: int = 32  # Ed25519 public key bytes embedded in v3 onions
    TOR_V3_CHECKSUM_BYTES: int = 2  # Checksum bytes embedded in v3 onions
    TOR_V3_VERSION_BYTE: int = 3  # Tor v3 onion address version marker
    DEFAULT_IPC_TIMEOUT: float = 15.0  # Default client IPC socket timeout in seconds
    THREAD_POLL_TIMEOUT: float = 1.0  # Timeout for non-blocking accept/recv loops
    IPC_AUTH_FAILURE_LIMIT: int = (
        3  # Maximum invalid local auth attempts per IPC session before disconnect
    )
