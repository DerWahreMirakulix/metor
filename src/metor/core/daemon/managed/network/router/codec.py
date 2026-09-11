"""Strict wire-envelope encoding and decoding for routed text messages."""

import base64
import binascii
import json
from typing import Dict, Optional, Tuple

from metor.core.api import JsonValue, is_valid_message_id
from metor.core.daemon.managed.models import TorCommand


def build_message_frame(
    command: TorCommand, msg_id: str, text: str, timestamp: str
) -> str:
    """Builds one newline-delimited, Base64-encoded message frame.

    Args:
        command (TorCommand): The transport command for the frame.
        msg_id (str): The stable logical message identifier.
        text (str): The text payload.
        timestamp (str): The daemon-authored timestamp.

    Returns:
        str: The complete protocol frame.
    """
    if not is_valid_message_id(msg_id):
        raise ValueError('Invalid message ID.')
    envelope: Dict[str, JsonValue] = {
        'id': msg_id,
        'timestamp': timestamp,
        'text': text,
    }
    encoded_payload: str = base64.b64encode(
        json.dumps(envelope).encode('utf-8')
    ).decode('utf-8')
    return f'{command.value} {msg_id} {encoded_payload}\n'


def decode_live_payload(
    payload_id: str,
    b64_payload: str,
) -> Tuple[str, str, Optional[str]]:
    """Decodes and strictly validates one live message envelope.

    Args:
        payload_id (str): The transport-level fallback identifier.
        b64_payload (str): The Base64-encoded JSON envelope.

    Raises:
        ValueError: If the envelope is malformed.

    Returns:
        Tuple[str, str, Optional[str]]: The message ID, text, and timestamp.
    """
    if not is_valid_message_id(payload_id):
        raise ValueError('Invalid live message ID.')
    try:
        raw_text: str = base64.b64decode(b64_payload, validate=True).decode('utf-8')
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError('Invalid live payload encoding.') from exc

    try:
        envelope_raw: JsonValue = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError('Invalid live payload JSON.') from exc

    if not isinstance(envelope_raw, dict):
        raise ValueError('Invalid live payload envelope.')

    envelope: Dict[str, JsonValue] = envelope_raw
    text_value: JsonValue = envelope.get('text')
    if not isinstance(text_value, str):
        raise ValueError('Invalid live payload text field.')

    timestamp_value: JsonValue = envelope.get('timestamp')
    timestamp: Optional[str] = (
        str(timestamp_value) if timestamp_value is not None else None
    )
    envelope_id = envelope.get('id', payload_id)
    if (
        not isinstance(envelope_id, str)
        or envelope_id != payload_id
        or not is_valid_message_id(envelope_id)
    ):
        raise ValueError('Invalid live message ID.')
    return envelope_id, text_value, timestamp


def decode_drop_payload(
    payload_id: str,
    b64_payload: str,
) -> Optional[Tuple[str, str, Optional[str]]]:
    """Decodes one drop envelope while preserving legacy plain-text support.

    Args:
        payload_id (str): The transport-level fallback identifier.
        b64_payload (str): The Base64-encoded payload.

    Returns:
        Optional[Tuple[str, str, Optional[str]]]: The decoded message fields, or
            None when the encoding itself is invalid.
    """
    if not is_valid_message_id(payload_id):
        return None
    try:
        raw_text: str = base64.b64decode(b64_payload, validate=True).decode('utf-8')
    except (binascii.Error, UnicodeDecodeError):
        return None

    try:
        envelope: Dict[str, JsonValue] = json.loads(raw_text)
    except json.JSONDecodeError:
        return payload_id, raw_text, None

    timestamp_value: JsonValue = envelope.get('timestamp')
    timestamp: Optional[str] = (
        str(timestamp_value) if timestamp_value is not None else None
    )
    envelope_id = envelope.get('id', payload_id)
    if not isinstance(envelope_id, str) or not is_valid_message_id(envelope_id):
        return None
    return (
        envelope_id,
        str(envelope.get('text', raw_text)),
        timestamp,
    )
