"""Toolkit-free local date/time labels for end-user GUI metadata."""

from datetime import datetime


def display_timestamp(
    value: str, *, now: datetime | None = None, include_date: bool = False
) -> str:
    """Formats canonical timestamps without exposing microseconds or wire offsets.

    Current-day messages show the local time; earlier dates retain their calendar
    date. Empty same-runtime timestamps stay absent. Invalid values produce a
    fixed non-secret label instead of arbitrary raw content.

    Args:
        value: Public canonical timestamp, never modified or persisted by the GUI.
        now: Optional reference instant for deterministic current-day comparison.
        include_date: Whether an activity ledger always needs calendar context.

    Returns:
        Short local time, dated time, an empty string or fixed unavailable label.
    """
    if not value:
        return ''
    try:
        instant = datetime.fromisoformat(value).astimezone()
        today = (now or datetime.now().astimezone()).astimezone().date()
    except (ValueError, OverflowError, OSError):
        return 'Time unavailable'
    return instant.strftime(
        '%H:%M' if not include_date and instant.date() == today else '%Y-%m-%d %H:%M'
    )


def message_metadata(timestamp: str, status: str) -> str:
    """Combines a readable timestamp with one truthful text or Voice status."""
    shown = display_timestamp(timestamp)
    return shown + ' · ' + status if shown else status
