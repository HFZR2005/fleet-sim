"""Wholesale electricity prices derived from Agile retail tariffs.

The real implementation (issue #65) inverts the Agile import price to
recover wholesale prices.  This stub returns synthetic observations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet_sim.stubs import stub


@stub("synthetic wholesale data — replace in issue #65")
def load_wholesale_prices(
    *,
    start_year: int,
    end_year: int,
) -> list[tuple[datetime, float]]:
    """Return ``(timestamp_utc, price_gbp_per_mwh)`` pairs.

    Stub: 48 half-hours per day for two days per year, with a linear
    price pattern.
    """
    rows: list[tuple[datetime, float]] = []
    for year in range(start_year, end_year + 1):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for day_offset in range(2):
            day_start = base + timedelta(days=day_offset)
            for slot in range(48):
                stamp = day_start + timedelta(minutes=30 * slot)
                price = 40.0 + 2.0 * slot / 48
                rows.append((stamp, price))
    return rows
