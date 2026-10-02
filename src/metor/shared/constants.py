"""Pure SDK contract bounds and shared identity/proof constants."""


class Constants:
    """Deterministic limits shared by protocol producers and consumers."""

    LOCALHOST: str = '127.0.0.1'
    MAX_STREAM_BYTES: int = 1048576  # 1 MB Limit for Tor TCP streams (OOM Protection)
    MAX_IPC_BYTES: int = 5242880  # 5 MB Limit for local IPC streams (OOM Protection)
    VOICE_CHUNK_MAX_BYTES: int = 65536
    DEFAULT_RETAINED_PAGE_SIZE: int = 50
    MAX_RETAINED_PAGE_SIZE: int = 200
    TEXT_HANDOFF_MAX_BYTES: int = 2 * 1024 * 1024
    ARCHIVE_PAGE_MAX_BYTES: int = 2 * 1024 * 1024
    HISTORY_PAGE_MAX_ITEMS: int = 200
    HISTORY_ANCHOR_MAX: int = (1 << 63) - 1
    FRONTEND_PROFILE_PAGE_ITEMS: int = 64
    FRONTEND_PROFILE_NAME_CHARACTERS: int = 255
    HISTORY_METADATA_MAX_CHARS: int = 512
    HISTORY_PAGE_MAX_BYTES: int = 2 * 1024 * 1024
    VOICE_CODEC_MAX_CHARS: int = 64
    VOICE_PRESSURE_PERCENT: int = 90
    MESSAGE_ID_MAX_CHARS: int = 128
    VOICE_OWNER_TOKEN_BYTES: int = 16
    LIVE_ATTEMPT_TOKEN_BYTES: int = 16
    DESTRUCTION_OPERATION_BYTES: int = 16
    VOICE_OWNER_MAX_DRAFTS: int = 8
    VOICE_OWNER_MAX_ITEMS: int = 9
    VOICE_OWNER_MAX_PROFILE_ITEMS: int = 256
    PROFILE_INSTANCE_BYTES: int = 16
    GUI_METADATA_MAX_BYTES: int = 64 * 1024
    GUI_MAX_PINS: int = 128
    GUI_DEFAULT_IDLE_SECONDS: int = 120
    GUI_MAX_IDLE_SECONDS: int = 24 * 60 * 60
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
    MAX_UNLOCK_INITIALIZATION_WAIT_SEC: float = 180.0  # Bounded cold Tor startup
    THREAD_POLL_TIMEOUT: float = 1.0  # Timeout for non-blocking accept/recv loops
    IPC_AUTH_FAILURE_LIMIT: int = (
        3  # Maximum invalid local auth attempts per IPC session before disconnect
    )
    FRONTEND_LIFETIME_TOKEN_BYTES: int = 32
    FRONTEND_LIFETIME_ID_BYTES: int = 16
    CALL_MAX_CONCURRENT: int = 1
    CALL_HISTORY_ITEMS: int = 16
    CALL_RING_TIMEOUT_SEC: float = 45.0
    CALL_FRAME_BYTES: int = 640
    CALL_FRAME_INTERVAL_SEC: float = 0.02
    CALL_AUDIO_MAX_FRAMES: int = 10
    CALL_AUDIO_READ_FRAMES: int = 4
    CALL_AUDIO_EXPIRY_SEC: float = 0.2
    CALL_KEEPALIVE_SEC: float = 1.0
    CALL_PEER_TIMEOUT_SEC: float = 10.0
    CALL_FRAME_SEQUENCE_MAX: int = (1 << 63) - 1
    CALL_CODEC: str = 'pcm_s16le_16000_mono'
    CALL_AUTH_FLAG: str = 'CALL'
    CALL_ID_BYTES: int = 16
    CALL_MAX_FRAME_BYTES: int = 1280
    CALL_OWNER_IDENTITIES_MAX: int = 256
    CALL_TRANSPORT_IDENTITIES_MAX: int = 256
    CALL_TIMESTAMP_SCALE: int = 1000
    CALL_FRAME_PREFIX: str = 'CALL_'
