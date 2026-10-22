"""Run a scenario file: replications, frames, and the two figures.

The intervals come from the replications. The frame file is the scenario's
own master seed, which is the seed recorded in the metadata.
"""

import json
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.experiments.report import (
    ConfidenceInterval,
    ExperimentReport,
    MetricEstimate,
    PairedDifference,
    run_experiment,
)
from fleet_sim.experiments.sweep import (
    LevelResult,
    PeakCrossing,
    PenetrationSweep,
    run_penetration_sweep,
)
from fleet_sim.fleet.frames import write_frames
from fleet_sim.fleet.network import ROOT_NODE_ID
from fleet_sim.models.frames import Frame
from fleet_sim.models.prices import london_day_bounds_utc
from fleet_sim.models.scenario import RunMetadata, Scenario
from fleet_sim.progress import RunProgress
from fleet_sim.scenario import collect_days, git_commit, load_scenario
from fleet_sim.viz.results import plot_diversity_day, plot_penetration_curve
from fleet_sim.viz.save import save_figure

_PACKAGE = "fleet-sim"


class ScenarioRun(BaseModel):
    """What ``run-scenario`` printed and where it wrote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_homes: int
    region: str
    start: date
    end: date
    replications: int
    mode: str
    penetration: float
    metrics: list[MetricEstimate]
    without_batteries: list[MetricEstimate]
    diversity: list[PairedDifference]
    battery: list[PairedDifference]
    levels: list[LevelResult]
    crossing: PeakCrossing | None
    frames_path: Path
    metadata_path: Path
    metrics_path: Path
    diversity_figure: Path
    penetration_figure: Path


def run_saved_scenario(
    scenario_path: Path,
    *,
    households_path: Path,
    output_dir: Path,
    price_source: PriceSource,
    max_households: int = 100,
    progress: RunProgress | None = None,
) -> ScenarioRun:
    """Run ``scenario_path`` and write frames, metadata, metrics, and figures.

    A single penetration is one paired experiment. A list is that experiment
    at the highest penetration, plus the penetration sweep. ``max_households``
    keeps the first households in the demand file.
    """
    scenario = load_scenario(scenario_path)
    _reject_clock_changes(scenario)
    if not households_path.is_file():
        raise FileNotFoundError(f"household demand not found: {households_path}")
    pool = HouseholdDemandPool.read(
        households_path, max_households=max_households, progress=progress
    )
    comparison = max(scenario.penetration_levels())
    experiment_scenario = scenario.model_copy(update={"penetration": comparison})
    experiment = run_experiment(
        experiment_scenario,
        pool=pool,
        price_source=price_source,
        progress=progress,
    )
    sweep = None
    if isinstance(scenario.penetration, list):
        sweep = run_penetration_sweep(
            scenario, pool=pool, price_source=price_source, progress=progress
        )
    metadata = RunMetadata(
        scenario=scenario,
        seed=scenario.seed,
        package_version=version(_PACKAGE),
        git_commit=git_commit(),
    )
    n_days = (scenario.end - scenario.start).days + 1
    if progress is not None:
        progress.task("Frames", n_days)
    _days, _fallbacks, frames = collect_days(
        scenario,
        pool=pool,
        price_source=price_source,
        seed=scenario.seed,
        penetration=comparison,
        mode=scenario.mode,
        progress=progress,
        label="frames",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_path = output_dir / "frames.json"
    metadata_path = output_dir / "metadata.json"
    metrics_path = output_dir / "metrics.json"
    write_frames(frames_path, frames, metadata=metadata)
    _write_json(metadata_path, metadata.model_dump(mode="json"))
    _write_json(
        metrics_path,
        {
            "experiment": experiment.model_dump(mode="json"),
            "sweep": None if sweep is None else sweep.model_dump(mode="json"),
        },
    )
    diversity_figure = output_dir / "diversity"
    penetration_figure = output_dir / "penetration"
    if progress is not None:
        progress.task("Diversity figure", 2)
    _save_diversity(
        scenario,
        pool,
        price_source,
        experiment,
        comparison,
        diversity_figure,
        progress,
    )
    _save_penetration(experiment, comparison, sweep, penetration_figure)
    levels = (
        list(sweep.levels) if sweep is not None else _two_levels(experiment, comparison)
    )
    return ScenarioRun(
        n_homes=scenario.n_homes,
        region=scenario.region,
        start=scenario.start,
        end=scenario.end,
        replications=scenario.replications,
        mode=scenario.mode,
        penetration=comparison,
        metrics=experiment.metrics,
        without_batteries=experiment.without_batteries,
        diversity=experiment.diversity,
        battery=experiment.battery,
        levels=levels,
        crossing=None if sweep is None else sweep.crossing,
        frames_path=frames_path,
        metadata_path=metadata_path,
        metrics_path=metrics_path,
        diversity_figure=diversity_figure,
        penetration_figure=penetration_figure,
    )


def _reject_clock_changes(scenario: Scenario) -> None:
    day = scenario.start
    while day <= scenario.end:
        london_day_bounds_utc(day)
        day += timedelta(days=1)


def _save_diversity(
    scenario: Scenario,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    experiment: ExperimentReport,
    penetration: float,
    stem: Path,
    progress: RunProgress | None,
) -> None:
    dates = _dates(scenario.start, scenario.end)
    day = dates[len(dates) // 2]
    one_day = scenario.model_copy(update={"start": day, "end": day})
    diverse = _import_kw(
        collect_days(
            one_day,
            pool=pool,
            price_source=price_source,
            seed=scenario.seed,
            penetration=penetration,
            mode="diverse",
            progress=progress,
            label="diverse",
        )[2]
    )
    identical = _import_kw(
        collect_days(
            one_day,
            pool=pool,
            price_source=price_source,
            seed=scenario.seed,
            penetration=penetration,
            mode="identical",
            progress=progress,
            label="identical",
        )[2]
    )
    difference = _named(experiment.diversity, "peak_demand_kw").interval
    save_figure(
        plot_diversity_day(
            diverse,
            identical,
            day=day,
            peak_difference_kw=(difference.mean, difference.low, difference.high),
        ),
        stem,
    )


def _save_penetration(
    experiment: ExperimentReport,
    penetration: float,
    sweep: PenetrationSweep | None,
    stem: Path,
) -> None:
    if sweep is not None:
        penetrations = [level.penetration for level in sweep.levels]
        with_battery = [_level_peak(level) for level in sweep.levels]
        without = [
            _interval_triple(level.peak_without_battery) for level in sweep.levels
        ]
    else:
        without_peak = _interval_triple(
            _named(experiment.without_batteries, "peak_demand_kw").interval
        )
        with_peak = _interval_triple(
            _named(experiment.metrics, "peak_demand_kw").interval
        )
        if penetration == 0.0:
            penetrations = [0.0]
            with_battery = [without_peak]
            without = [without_peak]
        else:
            penetrations = [0.0, penetration]
            with_battery = [without_peak, with_peak]
            without = [without_peak, without_peak]
    save_figure(plot_penetration_curve(penetrations, with_battery, without), stem)


def _two_levels(experiment: ExperimentReport, penetration: float) -> list[LevelResult]:
    """One or two levels, so a single penetration still has a curve to print."""
    without = _named(experiment.without_batteries, "peak_demand_kw")
    if penetration == 0.0:
        return [
            LevelResult(
                penetration=0.0,
                metrics=experiment.without_batteries,
                peak_without_battery=without.interval,
                peak_minus_no_battery=_flat_interval(without.interval),
            )
        ]
    return [
        LevelResult(
            penetration=0.0,
            metrics=experiment.without_batteries,
            peak_without_battery=without.interval,
            peak_minus_no_battery=_flat_interval(without.interval),
        ),
        LevelResult(
            penetration=penetration,
            metrics=experiment.metrics,
            peak_without_battery=without.interval,
            peak_minus_no_battery=_named(experiment.battery, "peak_demand_kw").interval,
        ),
    ]


def _flat_interval(interval: ConfidenceInterval) -> ConfidenceInterval:
    return interval.model_copy(update={"mean": 0.0, "low": 0.0, "high": 0.0})


def _level_peak(level: LevelResult) -> tuple[float, float, float]:
    return _interval_triple(_named(level.metrics, "peak_demand_kw").interval)


def _interval_triple(interval: ConfidenceInterval) -> tuple[float, float, float]:
    return (interval.mean, interval.low, interval.high)


def _named[T: MetricEstimate | PairedDifference](rows: list[T], metric: str) -> T:
    for row in rows:
        if row.metric == metric:
            return row
    raise ValueError(f"saved results have no {metric}")


def _import_kw(frames: list[Frame]) -> list[float]:
    return [_root_flow(frame) for frame in frames]


def _root_flow(frame: Frame) -> float:
    for node in frame.nodes:
        if node.node_id == ROOT_NODE_ID:
            return node.flow_kw
    raise ValueError(f"frame at {frame.slot_start.isoformat()} has no root node")


def _dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
