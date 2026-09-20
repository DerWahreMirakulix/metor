"""Finite GUI resource, input and layout limits from the approved v1.0 contracts."""


class GuiLimits:
    """Central bounds for presentation resources and worker admission."""

    DEVICE_BYTES: int = 64 * 1024
    DEVICE_STRING: int = 256
    MAX_PIXELS: int = 16384
    MIN_SCALE: float = 0.25
    MAX_SCALE: float = 8.0
    QUEUE_RECORDS: int = 512
    QUEUE_BYTES: int = 4 * 1024 * 1024
    NOTIFICATION_COALESCE_SECONDS: float = 5.0
    NOTIFICATIONS: int = 128
    NOTIFICATION_BYTES: int = 128 * 1024
    MEDIA_CACHE_BYTES: int = 16 * 1024 * 1024
    MEDIA_CACHE_BLOCK_BYTES: int = 64 * 1024
    PURGE_OBSERVE_SECONDS: float = 65.0
    PURGE_CLEANUP_SECONDS: float = 5.0
    PLAYBACK_COVERAGE_INTERVALS: int = 8192
    PLAYBACK_COVERAGE_PER_ITEM: int = 128
    WAVEFORM_BINS: int = 64
    SEEK_FRACTION_STEP: float = 0.05
    DECODE_BYTES: int = 4 * 1024 * 1024
    CAPTURE_BYTES: int = 1024 * 1024
    CAPTURE_DRAIN_SECONDS: float = 5.0
    LIFECYCLE_CAPTURE_SECONDS: float = 65.0
    PLAYBACK_POLL_SECONDS: float = 0.1
    PLAYBACK_QUEUE: int = 64
    AUDIO_ENDPOINTS: int = 128
    HELD_KEYS: int = 256
    HARDWARE_INPUT_RECORDS: int = 64
    HARDWARE_STATUS_SECONDS: float = 1.0
    MESSAGE_ID_BYTES: int = 16
    TEXT_CONTEXTS: int = 32
    TEXT_BYTES: int = 256 * 1024
    REVIEW_CONTEXTS: int = 8
    LIVE_ITEMS: int = 1000
    LIVE_METADATA_BYTES: int = 2 * 1024 * 1024
    PINS: int = 128
    PREFERENCE_BYTES: int = 64 * 1024
    RESTRICTED_REFRESH_SECONDS: float = 1.0
    IDLE_SECONDS: float = 120.0
    POWER_SECONDS: float = 2.0
    PURGE_SECONDS: float = 5.0
    LONG_PRESS_SECONDS: float = 0.5
    TOOLTIP_SECONDS: float = 0.6
    ACCESSIBILITY_NODES: int = 4096
    ACCESSIBILITY_BYTES: int = 2 * 1024 * 1024
    ACCESSIBILITY_ACTIONS: int = 64
    ACCESSIBILITY_POLL_SECONDS: float = 0.1
    WINDOWS_REFERENCE_DPI: float = 96.0
    LONG_PRESS_TRAVEL: float = 8.0
    CAPS_SECONDS: float = 0.3
    UI_TICK_SECONDS: float = 1 / 60
    REQUEST_WORKERS: int = 1
    ARCHIVE_PAGE_BYTES: int = 2 * 1024 * 1024
    PAGE_ITEMS: int = 64
    RECEIPT_TARGETS: int = 3 * LIVE_ITEMS + PAGE_ITEMS
    CONTACT_SELECTION_ITEMS: int = 128
    CONTACT_SELECTION_BYTES: int = 64 * 1024
    TEXT_HANDOFF_ITEM_BYTES: int = 1024
    CONTACT_BYTES: int = 4096
    SETTING_INPUT_CHARACTERS: int = 128
    SETTINGS_BYTES: int = 64 * 1024
    HISTORY_ANCHORS: int = 128
    SUCCESS_SECONDS: float = 3.0


class Geometry:
    """Logical layout measurements; physical pixels are mapped exactly once."""

    MIN_WIDTH: int = 360
    MIN_HEIGHT: int = 640
    DEFAULT_WIDTH: int = 1180
    DEFAULT_HEIGHT: int = 760
    BREAKPOINT: int = 960
    MASTER: int = 360
    DIVIDER: int = 1
    EDGE: int = 24
    TARGET: int = 48
    HEADER_END: int = 72
    SELECTOR_TOP: int = 88
    SELECTOR_END: int = 136
    TIMELINE_TOP: int = 152
    COMPACT_LIVE_TOP: int = 216
    COMPOSER: int = 64
    KEYBOARD: int = 264
    KEYBOARD_GAP: int = 8
    COMPACT_MAX: int = 560
    WIDE_MAX: int = 800
    FORM_MAX: int = 400
    TOOLTIP_MAX: int = 280
    BUBBLE_MAX: int = 520
    BUBBLE_MIN: int = 128
    BUBBLE_RATIO: float = 0.85
