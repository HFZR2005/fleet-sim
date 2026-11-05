"""Half-hourly residual load (demand minus renewables) for Great Britain.

The real implementation (issue #66) reads from a public grid data source.
This stub returns synthetic values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet_sim.stubs import stub


@stub("synthetic residual load — replace in issue #66")
def load_residual_load(
    *,
    start_year: int,
    end_year: int,
) -> list[tuple[datetime, float]]:
    """Return ``(timestamp_utc, residual_load_gw)`` pairs.

    Stub: 48 half-hours per day for two days per year, residual load
    linearly spaced between 20 and 40 GW.
    """
    rows: list[tuple[datetime, float]] = []
    for year in range(start_year, end_year + 1):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for day_offset in range(2):
            day_start = base + timedelta(days=day_offset)
            for slot in range(48):
                stamp = day_start + timedelta(minutes=30 * slot)
                load_gw = 20.0 + 20.0 * slot / 47
                rows.append((stamp, load_gw))
    return rows
