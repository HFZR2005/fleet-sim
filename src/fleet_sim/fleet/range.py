"""Run a fleet across a range of civil days.

Each day is solved on its own. Prices come from a ``PriceSource``, whose
cache means a day already fetched is not requested again. A clock-change
day is rejected the same way as a one-day price load, before any solve.
"""

import statistics
from collections.abc import Iterator
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from fleet_sim.data.source import PriceSource
from fleet_sim.fleet.homes import Fleet
from fleet_sim.fleet.metrics import FleetMetrics, fleet_metrics
from fleet_sim.fleet.solve import FleetDay, solve_fleet
from fleet_sim.models.prices import london_day_bounds_utc
from fleet_sim.progress import RunProgress


class DayReport(BaseModel):
    """One civil day's solve and its measures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    metrics: FleetMetrics
    solution: FleetDay


class Spread(BaseModel):
    """Median and the lowest and highest value across the days."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    median: float
    minimum: float
    maximum: float


class FleetRange(BaseModel):
    """Per-day measures, plus the spread of each measure across the days."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    days: list[DayReport]
    peak_demand_kw: Spread
    peak_slot: Spread
    peak_demand_without_battery_kw: Spread
    peak_slot_without_battery: Spread
    peak_to_average_ratio: Spread
    coincidence_factor: Spread
    total_savings_pence: Spread
    savings_per_home_pence: Spread


def run_fleet_days(
    homes: Fleet,
    *,
    start: date,
    end: date,
    region: str,
    price_source: PriceSource,
    progress: RunProgress | None = None,
) -> FleetRange:
    """Solve ``homes`` on every civil day from ``start`` through ``end``."""
    if end < start:
        raise ValueError(f"end {end.isoformat()} is before start {start.isoformat()}")
    reports: list[DayReport] = []
    if progress is not None:
        progress.task("Days", (end - start).days + 1)
    for day in _days(start, end):
        if progress is not None:
            progress.detail(day.isoformat())
        london_day_bounds_utc(day)
        prices = price_source.load(day, region)
        solution = solve_fleet(homes, prices, None)
        reports.append(
            DayReport(
                day=day,
                metrics=fleet_metrics(solution, prices.price_p_per_kwh),
                solution=solution,
            )
        )
        if progress is not None:
            progress.advance()
    return FleetRange(
        days=reports,
        peak_demand_kw=_spread([report.metrics.peak_demand_kw for report in reports]),
        peak_slot=_spread([float(report.metrics.peak_slot) for report in reports]),
        peak_demand_without_battery_kw=_spread(
            [report.metrics.peak_demand_without_battery_kw for report in reports]
        ),
        peak_slot_without_battery=_spread(
            [float(report.metrics.peak_slot_without_battery) for report in reports]
        ),
        peak_to_average_ratio=_spread(
            [report.metrics.peak_to_average_ratio for report in reports]
        ),
        coincidence_factor=_spread(
            [report.metrics.coincidence_factor for report in reports]
        ),
        total_savings_pence=_spread(
            [report.metrics.total_savings_pence for report in reports]
        ),
        savings_per_home_pence=_spread(
            [report.metrics.savings_per_home_pence for report in reports]
        ),
    )


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _spread(values: list[float]) -> Spread:
    ordered = sorted(values)
    return Spread(
        median=float(statistics.median(ordered)),
        minimum=ordered[0],
        maximum=ordered[-1],
    )
