"""Versioned contact QR payload parsing for all frontends."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, cast

from metor.core.api import JsonValue
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


def validate_contact_qr(raw: bytes | str) -> ContactQrValidationResult:
    """Validates a version-one JSON contact QR payload.

    Args:
        raw (bytes | str): Raw scanner output.

    Returns:
        ContactQrValidationResult: Typed payload or stable failure code.
    """
    try:
        raw_text: str = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        decoded: object = json.loads(raw_text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ContactQrValidationResult(error=ContactQrError.MALFORMED)
    if not isinstance(decoded, dict):
        return ContactQrValidationResult(error=ContactQrError.MALFORMED)
    data: dict[str, JsonValue] = cast(dict[str, JsonValue], decoded)
    if set(data) - {'version', 'onion', 'alias'}:
        return ContactQrValidationResult(error=ContactQrError.INVALID_FIELDS)
    if data.get('version') != 1:
        return ContactQrValidationResult(error=ContactQrError.UNSUPPORTED_VERSION)
    alias_value = data.get('alias')
    if alias_value is not None and (
        not isinstance(alias_value, str) or not alias_value.strip()
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
