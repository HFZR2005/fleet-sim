"""Where an uncoordinated fleet charges and discharges, for weighting slopes.

The price-curve evaluation weights each slot by how hard the fleet's
batteries work in it, so slope errors count most where batteries
operate.  ``fleet_charging`` runs one scenario over a range of past days
at the Agile prices of those days, and returns the fleet's net battery
power in every slot.  The run is cached, keyed by the scenario file and
the date range.

See ``docs/formulation.md``, Price curves, Evaluation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.models.frames import Frame
from fleet_sim.models.prices import PriceSeries, require_gsp_region
from fleet_sim.models.scenario import Scenario
from fleet_sim.scenario import collect_days, load_scenario

Simulate = Callable[[Scenario, PriceSource], list[Frame]]
"""Solve ``scenario`` over its whole date range and return its frames."""


class FleetCharging(BaseModel):
    """The fleet's net battery power in each slot of a run.

    ``net_battery_kw`` is Σ over homes of (import − demand), which is
    charge − discharge: positive while the fleet charges, negative while
    it discharges.  ``skipped_days`` were left out because they are
    clock-change days or lack a full day of prices.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str
    start: date
    end: date
    slot_start_utc: list[datetime]
    net_battery_kw: list[float]
    skipped_days: list[date]

    @model_validator(mode="after")
    def _same_length(self) -> FleetCharging:
        if len(self.slot_start_utc) != len(self.net_battery_kw):
            raise ValueError(
                "slot_start_utc and net_battery_kw must have the same length "
                f"(got {len(self.slot_start_utc)} and {len(self.net_battery_kw)})"
            )
        return self

    def by_slot(self) -> dict[datetime, float]:
        """Net battery power keyed by slot start."""
        return dict(zip(self.slot_start_utc, self.net_battery_kw, strict=True))


def fleet_charging(
    scenario_path: Path,
    start: date,
    end: date,
    *,
    price_source: PriceSource,
    cache_dir: Path,
    simulate: Simulate,
) -> FleetCharging:
    """Net battery power of ``scenario_path``'s fleet from ``start`` to ``end``.

    Days whose prices don't load (clock-change days, missing slots) are
    skipped, and each run of whole days between them is solved by
    ``simulate`` on a copy of the scenario with that run's dates.  The
    result is cached in ``cache_dir / "fleet"``, keyed by a hash of the
    scenario file's bytes and the two dates; a second call reads it.
    """
    key = hashlib.sha256(
        scenario_path.read_bytes() + f"{start.isoformat()}/{end.isoformat()}".encode()
    ).hexdigest()
    path = cache_dir / "fleet" / f"{key}.json"
    if path.is_file():
        return FleetCharging.model_validate_json(path.read_text(encoding="utf-8"))

    scenario = load_scenario(scenario_path)
    prices: dict[date, PriceSeries] = {}
    skipped: list[date] = []
    day = start
    while day <= end:
        try:
            prices[day] = price_source.load(day, scenario.region)
        except ValueError:
            skipped.append(day)
        day += timedelta(days=1)

    loaded = _LoadedPrices(prices)
    stamps: list[datetime] = []
    net: list[float] = []
    for first, last in _runs(sorted(prices)):
        run = scenario.model_copy(update={"start": first, "end": last})
        for frame in simulate(run, loaded):
            stamps.append(frame.slot_start)
            net.append(sum(home.import_kw - home.demand_kw for home in frame.homes))

    result = FleetCharging(
        scenario=scenario_path.name,
        start=start,
        end=end,
        slot_start_utc=stamps,
        net_battery_kw=net,
        skipped_days=skipped,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return result


def uncoordinated(pool_path: Path, *, max_households: int = 100) -> Simulate:
    """A ``Simulate`` that solves each home on its own with ``collect_days``.

    The household pool is read on the first call only, since it is slow
    to read and every run uses the same one.  ``max_households`` matches
    the CLI's default.
    """
    pool: HouseholdDemandPool | None = None

    def simulate(scenario: Scenario, price_source: PriceSource) -> list[Frame]:
        nonlocal pool
        if pool is None:
            pool = HouseholdDemandPool.read(pool_path, max_households=max_households)
        levels = scenario.penetration_levels()
        if len(levels) != 1:
            raise ValueError("the weighting scenario must name one penetration")
        _days, _fallbacks, frames = collect_days(
            scenario,
            pool=pool,
            price_source=price_source,
            seed=scenario.seed,
            penetration=levels[0],
            mode=scenario.mode,
        )
        return frames

    return simulate


class _LoadedPrices:
    """Prices already loaded, served by day.  Implements ``PriceSource``."""

    def __init__(self, prices: dict[date, PriceSeries]) -> None:
        self._prices = prices

    def load(self, day: date, region: str) -> PriceSeries:
        series = self._prices[day]
        if require_gsp_region(region) != series.region:
            raise ValueError(f"prices are for region {series.region}, not {region}")
        return series


def _runs(days: list[date]) -> list[tuple[date, date]]:
    """Group sorted days into (first, last) runs of consecutive days."""
    runs: list[tuple[date, date]] = []
    for day in days:
        if runs and runs[-1][1] + timedelta(days=1) == day:
            runs[-1] = (runs[-1][0], day)
        else:
            runs.append((day, day))
    return runs
