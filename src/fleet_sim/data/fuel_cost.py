"""Marginal fuel cost of gas generation.

The real implementation (issue #67) combines gas price, carbon price,
heat rate, and carbon intensity.  This stub returns a constant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet_sim.stubs import stub


@stub("synthetic fuel cost — replace in issue #67")
def compute_fuel_cost(
    *,
    start_year: int,
    end_year: int,
    heat_rate: float,
    gas_carbon_intensity: float,
    include_carbon_price_support: bool,
) -> list[tuple[datetime, float]]:
    """Return ``(timestamp_utc, fuel_cost_gbp_per_mwh)`` pairs.

    Stub: 48 half-hours per day for two days per year, constant cost.
    """
    _ = heat_rate, gas_carbon_intensity, include_carbon_price_support
    rows: list[tuple[datetime, float]] = []
    for year in range(start_year, end_year + 1):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for day_offset in range(2):
            day_start = base + timedelta(days=day_offset)
            for slot in range(48):
                stamp = day_start + timedelta(minutes=30 * slot)
                rows.append((stamp, 30.0))
    return rows
