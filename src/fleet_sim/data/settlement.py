"""GB settlement period to UTC timestamp conversion.

A GB settlement day runs from midnight to midnight UK local time.
Normal days have 48 half-hour settlement periods.  Spring-forward days
(last Sunday in March) have 46 and fall-back days (last Sunday in
October) have 50.

Period 1 always starts at 00:00 UK local time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")


def settlement_periods_utc(day: date) -> list[datetime]:
    """Return UTC timestamps for every settlement period of *day*.

    The list has 46, 48, or 50 entries depending on whether *day* is a
    clock-change day.  Index ``i`` corresponds to settlement period
    ``i + 1``.
    """
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=_LONDON)
    next_midnight = local_midnight + timedelta(days=1)
    utc_start = local_midnight.astimezone(UTC).replace(tzinfo=UTC)
    utc_end = next_midnight.astimezone(UTC).replace(tzinfo=UTC)
    n = int((utc_end - utc_start).total_seconds()) // 1800
    return [utc_start + timedelta(minutes=30 * i) for i in range(n)]


def expected_periods(day: date) -> int:
    """Return the number of settlement periods for *day* (46, 48, or 50)."""
    return len(settlement_periods_utc(day))


def period_to_utc(day: date, period: int) -> datetime:
    """Convert a settlement date and 1-based period to a UTC timestamp."""
    stamps = settlement_periods_utc(day)
    if period < 1 or period > len(stamps):
        raise ValueError(
            f"period {period} out of range for {day} (expected 1–{len(stamps)})"
        )
    return stamps[period - 1]
