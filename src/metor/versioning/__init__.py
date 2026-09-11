"""Authoritative Metor application and compatibility version registry."""

import re
from dataclasses import dataclass


APP_VERSION: str = '0.2.0'

# Client-to-daemon typed NDJSON wire generation.
IPC_PROTOCOL_VERSION: int = 2
IPC_PROTOCOL_MIN_SUPPORTED: int = 2

# Daemon-to-daemon Tor handshake and message-wire generation.
PEER_PROTOCOL_VERSION: int = 3
PEER_PROTOCOL_MIN_SUPPORTED: int = 3

# Durable SQLite/SQLCipher schema generation stored in PRAGMA user_version.
DB_SCHEMA_VERSION: int = 3
DB_SCHEMA_MIN_SUPPORTED: int = 3

# Persisted password-protected profile-master-key document generation.
KEYSLOT_FORMAT_VERSION: int = 1
KEYSLOT_FORMAT_MIN_SUPPORTED: int = 1

# Persisted authenticated encrypted-blob framing generation.
BLOB_FORMAT_VERSION: int = 1
BLOB_FORMAT_MIN_SUPPORTED: int = 1

# PMK subkey domains evolve together; per-blob object keys evolve independently.
# Changing either generation changes derived keys and requires a data migration.
PROFILE_KEY_DERIVATION_VERSION: int = 1
BLOB_OBJECT_DERIVATION_VERSION: int = 1

_APP_SEMVER_PATTERN: re.Pattern[str] = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'
)


@dataclass(frozen=True)
class CompatibilityAxis:
    """Describes one independently bumpable compatibility generation.

    Args:
        name (str): Stable machine-readable axis name.
        label (str): Human-readable status label.
        current (int): Current generation written or announced by Metor.
        minimum_supported (int | None): Oldest generation accepted, when the
            implementation supports a compatibility range.

    Returns:
        None
    """

    name: str
    label: str
    current: int
    minimum_supported: int | None


COMPATIBILITY_AXES: tuple[CompatibilityAxis, ...] = (
    CompatibilityAxis(
        'ipc', 'IPC protocol', IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED
    ),
    CompatibilityAxis(
        'peer',
        'Peer protocol',
        PEER_PROTOCOL_VERSION,
        PEER_PROTOCOL_MIN_SUPPORTED,
    ),
    CompatibilityAxis(
        'db-schema', 'DB schema', DB_SCHEMA_VERSION, DB_SCHEMA_MIN_SUPPORTED
    ),
    CompatibilityAxis(
        'keyslot',
        'Keyslot format',
        KEYSLOT_FORMAT_VERSION,
        KEYSLOT_FORMAT_MIN_SUPPORTED,
    ),
    CompatibilityAxis(
        'blob', 'Blob format', BLOB_FORMAT_VERSION, BLOB_FORMAT_MIN_SUPPORTED
    ),
    CompatibilityAxis(
        'profile-key-derivation',
        'Profile-key derivation',
        PROFILE_KEY_DERIVATION_VERSION,
        None,
    ),
    CompatibilityAxis(
        'blob-object-derivation',
        'Blob-object derivation',
        BLOB_OBJECT_DERIVATION_VERSION,
        None,
    ),
)


def validate_version_registry() -> tuple[str, ...]:
    """Validates every central compatibility-version invariant.

    Args:
        None

    Returns:
        tuple[str, ...]: Validation errors; empty when the registry is valid.
    """
    errors: list[str] = []
    if _APP_SEMVER_PATTERN.fullmatch(APP_VERSION) is None:
        errors.append('application: APP_VERSION must be a valid Semantic Version')
    for axis in COMPATIBILITY_AXES:
        if axis.current < 1:
            errors.append(f'{axis.name}: current version must be at least 1')
        if axis.minimum_supported is not None:
            if axis.minimum_supported < 1:
                errors.append(
                    f'{axis.name}: minimum supported version must be at least 1'
                )
            if axis.minimum_supported > axis.current:
                errors.append(
                    f'{axis.name}: minimum supported version exceeds current version'
                )
    return tuple(errors)


def negotiate_protocol_generation(
    local_current: int,
    local_minimum: int,
    remote_current: int,
    remote_minimum: int,
) -> int | None:
    """Selects the highest generation in two advertised support ranges.

    Args:
        local_current (int): Highest generation supported locally.
        local_minimum (int): Lowest generation supported locally.
        remote_current (int): Highest generation supported remotely.
        remote_minimum (int): Lowest generation supported remotely.

    Returns:
        int | None: Highest mutually supported generation, or ``None`` when
            either range is invalid or the ranges do not overlap.
    """
    if (
        local_minimum < 1
        or remote_minimum < 1
        or local_minimum > local_current
        or remote_minimum > remote_current
    ):
        return None
    negotiated: int = min(local_current, remote_current)
    if negotiated < max(local_minimum, remote_minimum):
        return None
    return negotiated


def format_version_matrix() -> str:
    """Builds the human-readable application and compatibility matrix.

    Args:
        None

    Returns:
        str: One line per authoritative version axis.
    """
    application_label: str = 'Metor application'
    lines: list[str] = [f'{application_label:<28}{APP_VERSION}']
    for axis in COMPATIBILITY_AXES:
        suffix: str = str(axis.current)
        if axis.minimum_supported is not None:
            suffix += f' (minimum supported: {axis.minimum_supported})'
        lines.append(f'{axis.label:<28}{suffix}')
    return '\n'.join(lines)
