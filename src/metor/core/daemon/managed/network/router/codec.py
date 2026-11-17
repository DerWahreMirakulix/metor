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


def decode_message_payload(
    payload_id: str,
    b64_payload: str,
) -> Tuple[str, str, Optional[str]]:
    """Validate the common LIVE/DROP text envelope before persistence or ACK.

    Args:
        payload_id (str): The identifier from the frame header.
        b64_payload (str): The Base64-encoded JSON envelope.

    Raises:
        ValueError: If the envelope is malformed.

    Returns:
        Tuple[str, str, Optional[str]]: The message ID, text, and timestamp.
    """
    if not is_valid_message_id(payload_id):
        raise ValueError('Invalid message ID.')
    try:
        raw_text: str = base64.b64decode(b64_payload, validate=True).decode('utf-8')
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError('Invalid message payload encoding.') from exc

    try:
        envelope_raw: JsonValue = json.loads(raw_text)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid message payload JSON.') from exc

    if not isinstance(envelope_raw, dict):
        raise ValueError('Invalid message payload envelope.')

    envelope: Dict[str, JsonValue] = envelope_raw
    text_value: JsonValue = envelope.get('text')
    if not isinstance(text_value, str):
        raise ValueError('Invalid message payload text field.')

    timestamp_value: JsonValue = envelope.get('timestamp')
    if timestamp_value is not None and not isinstance(timestamp_value, str):
        raise ValueError('Invalid message timestamp.')
    if envelope.get('id') != payload_id:
        raise ValueError('Message ID does not match frame header.')
    return payload_id, text_value, timestamp_value
