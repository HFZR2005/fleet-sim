"""Load a scenario file and run it once from its master seed.

Repeating that run is ``fleet_sim.experiments``. Walking a list of
penetrations is a later issue. This module is the one pass over the date range.
"""

import json
import subprocess
import tomllib
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.fleet.frames import frames_for_day, write_frames
from fleet_sim.fleet.generate import generate_fleet, mean_fleet, with_demand
from fleet_sim.fleet.metrics import FleetMetrics, fleet_metrics
from fleet_sim.fleet.solve import solve_fleet
from fleet_sim.models.demand import DemandFallback
from fleet_sim.models.frames import Frame
from fleet_sim.models.prices import london_day_bounds_utc
from fleet_sim.models.scenario import RunMetadata, Scenario

_PACKAGE = "fleet-sim"


class DayMetrics(BaseModel):
    """One civil day's fleet measures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    metrics: FleetMetrics


class ScenarioResult(BaseModel):
    """The master-seed pass, and the trial days that had to fall back."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: RunMetadata
    days: list[DayMetrics]
    fallbacks: list[DemandFallback]


def load_scenario(path: Path) -> Scenario:
    """Read a scenario TOML file."""
    if not path.is_file():
        raise FileNotFoundError(f"scenario not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"scenario {path} is not valid TOML") from exc
    try:
        return Scenario.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"scenario {path} is invalid\n{exc}") from exc


def run_scenario(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    output_dir: Path,
) -> ScenarioResult:
    """Solve ``scenario`` once and write metadata, frames, and metrics.

    The fleet is drawn from ``scenario.seed``. Each day reloads demand for
    the households assigned on that draw. Identical mode then copies the
    mean of that day's homes. A scenario that names several penetrations
    is not run here.
    """
    days, fallbacks, frames = collect_days(
        scenario,
        pool=pool,
        price_source=price_source,
        seed=scenario.seed,
        penetration=_one_penetration(scenario),
        mode=scenario.mode,
    )
    metadata = RunMetadata(
        scenario=scenario,
        seed=scenario.seed,
        package_version=version(_PACKAGE),
        git_commit=git_commit(),
    )
    result = ScenarioResult(metadata=metadata, days=days, fallbacks=fallbacks)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_model(output_dir / "metadata.json", metadata)
    _write_model(output_dir / "metrics.json", result)
    write_frames(output_dir / "frames.json", frames, metadata=metadata)
    return result


def collect_days(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    seed: int,
    penetration: float,
    mode: str,
) -> tuple[list[DayMetrics], list[DemandFallback], list[Frame]]:
    """Solve one fleet over the date range.

    ``seed`` is the master seed for this pass. It is the scenario seed for
    a single run, and a derived seed for one replication. ``mode`` is
    ``diverse`` or ``identical``.
    """
    if mode not in ("diverse", "identical"):
        raise ValueError(f"mode must be 'diverse' or 'identical' (got {mode!r})")
    assigned = generate_fleet(
        pool,
        scenario.start,
        scenario.n_homes,
        seed,
        penetration,
        region=scenario.region,
        mode="diverse",
        distribution=scenario.battery,
    )
    days: list[DayMetrics] = []
    fallbacks: list[DemandFallback] = []
    frames: list[Frame] = []
    for day in _days(scenario.start, scenario.end):
        london_day_bounds_utc(day)
        prices = price_source.load(day, scenario.region)
        loaded = with_demand(assigned.fleet, pool, day)
        fallbacks.extend(loaded.fallbacks)
        fleet = loaded.fleet
        if mode == "identical":
            fleet = mean_fleet(fleet)
        solution = solve_fleet(fleet, prices, None)
        days.append(
            DayMetrics(day=day, metrics=fleet_metrics(solution, prices.price_p_per_kwh))
        )
        frames.extend(frames_for_day(prices, solution))
    return days, fallbacks, frames


def _one_penetration(scenario: Scenario) -> float:
    levels = scenario.penetration_levels()
    if len(levels) != 1:
        raise ValueError(
            "this run takes one penetration; "
            f"a sweep over {len(levels)} values is a later step"
        )
    return levels[0]


def read_metadata(path: Path) -> RunMetadata:
    """Read a ``metadata.json`` written by :func:`run_scenario`."""
    return RunMetadata.model_validate(json.loads(path.read_text(encoding="utf-8")))


def git_commit() -> str:
    """The current commit, or ``unknown`` when git cannot say."""
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return output.strip()


def _days(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _write_model(path: Path, model: BaseModel) -> None:
    path.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
