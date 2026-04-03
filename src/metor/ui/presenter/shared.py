"""Shared formatting helpers used across UI presenter modules."""

from datetime import datetime, timezone
from typing import Optional, Tuple

# Local Package Imports
from metor.ui.theme import Theme


def parse_timestamp(timestamp: Optional[str]) -> Optional[datetime]:
    """
    Parses one stored timestamp into UTC when possible.

    Args:
        timestamp (Optional[str]): The raw timestamp string.

    Returns:
        Optional[datetime]: The parsed datetime or None on failure.
    """
    raw_timestamp: str = str(timestamp or '').strip()
    if not raw_timestamp:
        return None

    try:
        parsed: datetime = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc)


def format_fallback_timestamp(timestamp: str, compact: bool) -> str:
    """
    Normalizes one unparseable timestamp string for display.

    Args:
        timestamp (str): The raw timestamp string.
        compact (bool): Whether to collapse the label to time only.

    Returns:
        str: The best-effort display label.
    """
    normalized_timestamp: str = timestamp.strip().replace('T', ' ')
    if not normalized_timestamp:
        return ''

    date_part: str = ''
    time_part: str = normalized_timestamp
    if ' ' in normalized_timestamp:
        date_part, time_part = normalized_timestamp.split(' ', 1)

    for separator in ('.', '+', 'Z'):
        if separator in time_part:
            time_part = time_part.split(separator, 1)[0]

    time_parts = time_part.split(':')
    if len(time_parts) >= 3:
        time_part = ':'.join(time_parts[:3])

    if compact:
        return time_part
    if date_part:
        return f'{date_part} {time_part}'.strip()
    return time_part


def format_timestamp_label(
    timestamp: Optional[str],
    is_drop: bool = False,
    compact: bool = False,
) -> str:
    """
    Formats one timestamp for CLI or chat timeline rendering.

    Args:
        timestamp (Optional[str]): The raw timestamp string.
        is_drop (bool): Whether to append the drop suffix.
        compact (bool): Whether to collapse to a short time-only label.

    Returns:
        str: The formatted timestamp label without surrounding brackets.
    """
    raw_label: str = str(timestamp or '').strip()
    label: str = ''
    parsed_timestamp: Optional[datetime] = parse_timestamp(raw_label)

    if parsed_timestamp is not None:
        label = parsed_timestamp.strftime(
            '%H:%M:%S' if compact else '%Y-%m-%d %H:%M:%S'
        )
    elif raw_label:
        label = format_fallback_timestamp(raw_label, compact)

    if is_drop:
        label = f'{label} | Drop' if label else 'Drop'

    return label


def build_timestamp_prefix(
    timestamp: Optional[str],
    is_drop: bool = False,
    compact: bool = False,
) -> Tuple[str, str]:
    """
    Builds the rendered and visible timestamp prefix for one timeline line.

    Args:
        timestamp (Optional[str]): The raw timestamp string.
        is_drop (bool): Whether the line represents a drop transport.
        compact (bool): Whether to shorten the visible timestamp.

    Returns:
        Tuple[str, str]: The ANSI-rendered prefix and visible plain-text prefix.
    """
    label: str = format_timestamp_label(timestamp, is_drop, compact)
    if not label:
        return '', ''

    visible_prefix: str = f'[{label}] '
    rendered_prefix: str = f'{Theme.DARK_GREY}{visible_prefix}{Theme.RESET}'
    return rendered_prefix, visible_prefix


def indent_multiline_text(text: str, prefix_len: int) -> str:
    """
    Indents continuation lines so they align with the first payload column.

    Args:
        text (str): The payload text.
        prefix_len (int): The visible prefix length.

    Returns:
        str: The aligned payload text.
    """
    if '\n' not in text:
        return text

    padding: str = ' ' * prefix_len
    return f'\n{padding}'.join(text.split('\n'))


def format_prefixed_message(
    rendered_prefix: str,
    visible_prefix: str,
    text: str,
) -> str:
    """
    Formats one possibly multiline message behind an already prepared prefix.

    Args:
        rendered_prefix (str): The ANSI-rendered prefix.
        visible_prefix (str): The visible plain-text prefix.
        text (str): The payload text.

    Returns:
        str: The fully formatted line.
    """
    padded_text: str = indent_multiline_text(text, len(visible_prefix))
    return f'{rendered_prefix}{padded_text}'


def get_header_string(text: str) -> str:
    """
    Creates a simple header string with the given text.

    Args:
        text (str): The header text.

    Returns:
        str: The formatted header string.
    """
    return f'\n--- {text} ---\n'


def get_divider_string(length: int = 30, add_spaces: bool = False) -> str:
    """
    Generates a divider string consisting of dashes.

    Args:
        length (int): The number of dashes.
        add_spaces (bool): Whether to add spaces between dashes.

    Returns:
        str: The divider string.
    """
    divider: str = '-' * length
    if add_spaces:
        divider = ' '.join(divider)
    return divider
