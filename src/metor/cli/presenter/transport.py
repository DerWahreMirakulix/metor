"""Formatters for transport state DTOs."""

from typing import Dict, List, Optional

from metor.core.api import JsonValue, TransportStateEvent

# Local Package Imports
from metor.cli.theme import Theme


def _format_drop_tunnel(drop_tunnel: Optional[Dict[str, JsonValue]]) -> str:
    """
    Formats one cached drop-tunnel summary line.

    Args:
        drop_tunnel (Optional[dict]): The raw drop-tunnel metadata dict, if any.

    Returns:
        str: The formatted drop-tunnel line.
    """
    if not drop_tunnel:
        return f'drop_tunnel: {Theme.DARK_GREY}none{Theme.RESET}'

    parts: List[str] = []
    if drop_tunnel.get('cached'):
        parts.append('cached')
    if drop_tunnel.get('opened_at'):
        parts.append(f'opened_at: {drop_tunnel["opened_at"]}')
    if drop_tunnel.get('last_used_at'):
        parts.append(f'last_used_at: {drop_tunnel["last_used_at"]}')

    detail: str = ', '.join(parts) if parts else 'cached'
    return f'drop_tunnel: {detail}'


def format_transport_state(event: TransportStateEvent) -> str:
    """
    Formats one transport state DTO for terminal output.

    Args:
        event (TransportStateEvent): The transport state DTO.

    Returns:
        str: The formatted transport state lines.
    """
    header_text: str = f'Transport state for {Theme.CYAN}{event.peer}{Theme.RESET}'
    if not event.peer:
        return f'{Theme.YELLOW}No active sessions.{Theme.RESET}'
    lines: List[str] = [
        header_text,
        '',
        f'session_state: {Theme.YELLOW}{event.session_state}{Theme.RESET}',
        _format_drop_tunnel(event.drop_tunnel),
        f'focus_count: {event.focus_count}',
        f'pending_live_count: {event.pending_live_count}',
        f'auto_accept: {"yes" if event.auto_accept else "no"}',
    ]
    return '\n'.join(lines)
