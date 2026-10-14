from datetime import datetime, timezone

from app.main import (
    calculate_half_day,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
)


def test_late_grace_period_exactly_10_minutes():
    punch = datetime(2026, 7, 6, 4, 10, tzinfo=timezone.utc)
    assert compute_late_minutes(punch, "09:30", "2026-07-06") == 0


def test_late_minutes_after_grace_period():
    punch = datetime(2026, 7, 6, 4, 10, 1, tzinfo=timezone.utc)
    assert compute_late_minutes(punch, "09:30", "2026-07-06") == 10


def test_work_hours_round_half_up():
    start = datetime(2026, 7, 6, 4, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 6, 8, 15, tzinfo=timezone.utc)
    assert compute_work_hours(start, end) == 4.25


def test_half_day_below_four_and_half_hours():
    assert calculate_half_day(4.49) is True


def test_four_and_half_hours_is_not_half_day():
    assert calculate_half_day(4.50) is False


def test_overtime_requires_30_minutes():
    # Shift ends at 18:30 IST, which is 13:00 UTC.
    before_threshold = datetime(2026, 7, 6, 13, 29, 59, tzinfo=timezone.utc)
    at_threshold = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)

    assert compute_overtime(
        before_threshold, "18:30", "2026-07-06", "09:30"
    ) == 0

    assert compute_overtime(
        at_threshold, "18:30", "2026-07-06", "09:30"
    ) == 30
