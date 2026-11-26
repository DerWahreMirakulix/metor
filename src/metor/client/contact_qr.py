"""Versioned contact QR payload parsing for all frontends."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, cast

from metor.core.api import JsonValue
from metor.shared.constants import Constants
from metor.shared.network import decode_tor_v3_onion_public_key, ensure_onion_format


class ContactQrError(str, Enum):
    """Stable contact QR validation failures."""

    MALFORMED = 'malformed'
    INVALID_FIELDS = 'invalid_fields'
    UNSUPPORTED_VERSION = 'unsupported_version'
    INVALID_ALIAS = 'invalid_alias'
    INVALID_ONION = 'invalid_onion'


@dataclass(frozen=True)
class ContactQrPayload:
    """Validated versioned contact identity payload."""

    version: int
    onion: str
    alias: Optional[str] = None


@dataclass(frozen=True)
class ContactQrValidationResult:
    """Validation result without UI-rendered error text."""

    payload: Optional[ContactQrPayload] = None
    error: Optional[ContactQrError] = None

    @property
    def valid(self) -> bool:
        """Reports whether validation produced a payload.

        Args:
            None

        Returns:
            bool: True when a validated payload is present.
        """
        return self.payload is not None


def _is_flat_object(text: str) -> bool:
    """Check the contact schema's sole container before entering the JSON decoder."""
    value = text.strip(' \t\r\n')
    if not value.startswith('{') or not value.endswith('}'):
        return False
    quoted = False
    escaped = False
    for character in value[1:-1]:
        if quoted:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in '{[':
            return False
    return True


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous duplicate fields instead of accepting the final value."""
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('Duplicate contact field')
    return fields


def fits_contact_input(value: str, byte_limit: int) -> bool:
    """Check the byte budget and encoding before updating native form state."""
    if len(value) > byte_limit:
        return False
    try:
        return len(value.encode('utf-8')) <= byte_limit
    except UnicodeEncodeError:
        return False


def validate_contact_qr(raw: bytes | str) -> ContactQrValidationResult:
    """Validates a version-one JSON contact QR payload.

    Args:
        raw (bytes | str): Raw scanner output.

    Returns:
        ContactQrValidationResult: Typed payload or stable failure code.
    """
    if len(raw) > Constants.CONTACT_QR_MAX_BYTES:
        return ContactQrValidationResult(error=ContactQrError.MALFORMED)
    try:
        encoded = raw.encode('utf-8') if isinstance(raw, str) else raw
        if len(encoded) > Constants.CONTACT_QR_MAX_BYTES:
            return ContactQrValidationResult(error=ContactQrError.MALFORMED)
        text = encoded.decode('utf-8')
        if not _is_flat_object(text):
            return ContactQrValidationResult(error=ContactQrError.MALFORMED)
        decoded: object = json.loads(text, object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError, RecursionError):
        return ContactQrValidationResult(error=ContactQrError.MALFORMED)
    if not isinstance(decoded, dict):
        return ContactQrValidationResult(error=ContactQrError.MALFORMED)
    data: dict[str, JsonValue] = cast(dict[str, JsonValue], decoded)
    if set(data) - {'version', 'onion', 'alias'}:
        return ContactQrValidationResult(error=ContactQrError.INVALID_FIELDS)
    if type(data.get('version')) is not int or data.get('version') != 1:
        return ContactQrValidationResult(error=ContactQrError.UNSUPPORTED_VERSION)
    alias_value = data.get('alias')
    if alias_value is not None and (
        not isinstance(alias_value, str)
        or not alias_value.strip()
        or any(0xD800 <= ord(character) <= 0xDFFF for character in alias_value)
    ):
        return ContactQrValidationResult(error=ContactQrError.INVALID_ALIAS)
    onion_value = data.get('onion')
    if not isinstance(onion_value, str):
        return ContactQrValidationResult(error=ContactQrError.INVALID_ONION)
    try:
        decode_tor_v3_onion_public_key(onion_value)
        onion = ensure_onion_format(onion_value)
    except ValueError:
        return ContactQrValidationResult(error=ContactQrError.INVALID_ONION)
    return ContactQrValidationResult(
        payload=ContactQrPayload(
            version=1,
            onion=onion,
            alias=alias_value.strip() if isinstance(alias_value, str) else None,
        )
    )
