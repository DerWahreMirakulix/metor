"""Toolkit-free canonical timestamp formatting and local calendar boundaries."""

from datetime import datetime, timedelta, timezone
import unittest

from metor.ui.gui.time import display_timestamp, message_metadata


class GuiTimestampTests(unittest.TestCase):
    """Keeps domain timestamps intact while avoiding wire-format visual noise."""

    def test_current_day_and_offset_use_local_clock_without_wire_detail(self) -> None:
        """Offset-aware ISO values display the local minute of the same instant."""
        instant = datetime(
            2024, 5, 6, 8, 9, 10, 123456, tzinfo=timezone(timedelta(hours=2))
        )
        self.assertEqual(
            display_timestamp(instant.isoformat(), now=instant),
            instant.astimezone().strftime('%H:%M'),
        )
        self.assertEqual(
            display_timestamp(instant.isoformat(), now=instant, include_date=True),
            instant.astimezone().strftime('%Y-%m-%d %H:%M'),
        )
        self.assertEqual(
            display_timestamp(instant.isoformat(), now=instant + timedelta(days=2)),
            instant.astimezone().strftime('%Y-%m-%d %H:%M'),
        )

    def test_absent_and_unexpected_timestamps_have_bounded_safe_labels(self) -> None:
        """Unknown timestamp strings never become raw content or leading separators."""
        self.assertEqual(message_metadata('', 'Pending'), 'Pending')
        for value in (
            'not a timestamp',
            'private-fixture-value' * 500,
            '9999-99-99T99:99:99+00:00',
        ):
            self.assertEqual(display_timestamp(value), 'Time unavailable')

    def test_local_day_comparison_survives_offset_and_calendar_boundary(self) -> None:
        """Current-day labels compare the converted local date across a wire-year boundary."""
        instant = datetime(
            2024, 12, 31, 23, 15, 59, 654321, tzinfo=timezone(timedelta(hours=-3))
        )
        local = instant.astimezone()
        same_day = local.replace(hour=12, minute=0, second=0, microsecond=0)
        self.assertEqual(
            display_timestamp(instant.isoformat(), now=same_day),
            local.strftime('%H:%M'),
        )
        self.assertEqual(
            display_timestamp(instant.isoformat(), now=same_day + timedelta(days=1)),
            local.strftime('%Y-%m-%d %H:%M'),
        )


if __name__ == '__main__':
    unittest.main()
