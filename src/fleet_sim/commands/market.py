"""A scenario with a ``[market]`` section: the fleet in the loop.

For each ρ, local penetration and replication: draw the fleet on the
scenario's topology, then for each price model and national fleet size M
solve each day's equilibrium and evaluate the network under both
allocations. M = 0 is always solved, and every measure is paired with it on
the same fleet and days. Only the headline point, the first ρ and the
highest local penetration, is repeated under the robustness models. Each
day's price inputs are built once per price model and shared by every
replication. See ``docs/architecture.md``, Fleet in the loop.
"""

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal, NamedTuple

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.experiments.report import replication_seed, t_interval
from fleet_sim.fleet.frames import frames_for_day, write_frames
from fleet_sim.fleet.generate import generate_fleet, with_demand
from fleet_sim.fleet.market import market_metrics, solve_market_day
from fleet_sim.fleet.network import Network
from fleet_sim.fleet.overload import day_overload, summarise_replication
from fleet_sim.fleet.price_inputs import day_price_inputs
from fleet_sim.fleet.topology import assign_transformers, build_topology
from fleet_sim.models.fleet import Fleet, FleetDay
from fleet_sim.models.frames import Frame
from fleet_sim.models.market import (
    DiagnosticsRecord,
    EquilibriumDiagnostics,
    MarketDay,
)
from fleet_sim.models.network import (
    DayOverload,
    HomeProfile,
    NetworkSpec,
    ReplicationOverload,
)
from fleet_sim.models.results import (
    MarketLevelResult,
    MarketSweep,
    MetricEstimate,
    PairedDifference,
    ScenarioRun,
)
from fleet_sim.models.scenario import RunMetadata, Scenario
from fleet_sim.prices.config import load_config
from fleet_sim.prices.parameters import load_price_model
from fleet_sim.progress import RunProgress
from fleet_sim.random_streams import RandomStreams
from fleet_sim.scenario import git_commit
from fleet_sim.stubs import active_stubs, begin_stub_run, require_no_stubs
from fleet_sim.viz.market import (
    plot_added_load,
    plot_overload_by_penetration,
    plot_saving_by_model,
    read_market_sweep,
)
from fleet_sim.viz.save import save_figure

_PACKAGE = "fleet-sim"
_CALIBRATION = Path("calibration/price_curves.toml")

Allocation = Literal["joint", "replanned"]
_GROUPS = ("market", "joint", "replanned")
_OVERLOAD_METRICS = (
    "transformers_overloaded_share",
    "mean_peak_utilisation",
    "worst_peak_utilisation",
    "total_overload_energy_kwh",
    "hidden_overload_share",
)
_MARKET_METRICS = (
    "peak_added_load_gw",
    "peak_added_load_hour",
    "saving_per_battery_home_p_per_day",
    "non_battery_price_change_p_per_day",
    "mean_charge_price_p_per_kwh",
    "mean_discharge_price_p_per_kwh",
)


class _Point(NamedTuple):
    """One sweep point: a price model, ρ, national fleet M and penetration."""

    price_model: str
    rho: float
    national_batteries: float
    penetration: float


@dataclass
class _Samples:
    """One point's measures, one value per replication.

    ``values[group][metric]`` with group ``market``, ``joint`` or
    ``replanned``; ``net_power_kw`` holds each replication's profile.
    """

    values: dict[str, dict[str, list[float]]]
    net_power_kw: list[list[float]]
    diagnostics: list[EquilibriumDiagnostics]


def run_market_scenario(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    output_dir: Path,
    cache_dir: Path | None = None,
    progress: RunProgress | None = None,
    release: bool = False,
) -> ScenarioRun:
    """Run ``scenario`` with its ``[market]`` and ``[network]`` sections.

    ``cache_dir`` holds the price-curve inputs (Agile rates, residual load,
    fuel cost); by default it is the one ``calibration/price_curves.toml``
    names, which also gives the fuel-cost settings.
    """
    if scenario.market is None:
        raise ValueError("a market scenario needs a [market] section")
    if scenario.network is None:
        raise ValueError("a [market] scenario also needs a [network] section")
    if scenario.replications < 2:
        raise ValueError(
            f"a t-interval needs at least 2 replications (got {scenario.replications})"
        )
    started = time.perf_counter()
    begin_stub_run()
    settings = scenario.market
    levels = settings.national_battery_levels()
    if 0.0 not in levels:
        levels = [0.0, *levels]
    penetrations = scenario.penetration_levels()
    rhos = scenario.network.rho_levels()
    models = settings.price_models()
    headline = (rhos[0], max(penetrations))
    dates = _dates(scenario.start, scenario.end)
    calibration = load_config(_CALIBRATION)
    price_cache = Path(calibration.data.cache_dir) if cache_dir is None else cache_dir
    inputs = {
        name: [
            day_price_inputs(
                day,
                scenario.region,
                price_cache,
                model=load_price_model(settings.price_parameters_file, name),
                fuel_cost=calibration.fuel_cost,
            )
            for day in dates
        ]
        for name in models
    }

    def models_at(rho: float, penetration: float) -> list[str]:
        return models if (rho, penetration) == headline else models[:1]

    points = [
        _Point(name, rho, m, p)
        for rho in rhos
        for p in penetrations
        for name in models_at(rho, p)
        for m in levels
    ]
    solve_count = scenario.replications * len(points) * len(dates)
    if progress is not None:
        progress.task("Market", solve_count)
    home_ids = [f"home-{i + 1}" for i in range(scenario.n_homes)]
    spec = build_topology(home_ids, scenario.network, RandomStreams(scenario.seed))

    samples = {
        point: _Samples(
            values={
                "market": {name: [] for name in _MARKET_METRICS},
                "joint": {name: [] for name in _OVERLOAD_METRICS},
                "replanned": {name: [] for name in _OVERLOAD_METRICS},
            },
            net_power_kw=[],
            diagnostics=[],
        )
        for point in points
    }
    records: list[DiagnosticsRecord] = []
    frames: list[Frame] = []
    frame_point = _Point(models[0], headline[0], levels[-1], headline[1])

    for rho in rhos:
        for penetration in penetrations:
            for index in range(scenario.replications):
                fleets = _draw_fleets(
                    scenario,
                    pool,
                    spec,
                    rho,
                    penetration,
                    replication_seed(scenario.seed, index),
                    dates,
                )
                for name in models_at(rho, penetration):
                    for national_batteries in levels:
                        point = _Point(name, rho, national_batteries, penetration)
                        label = (
                            f"replication {index + 1}/{scenario.replications}, "
                            f"{name}, ρ {rho}, M {national_batteries:,.0f}, "
                            f"penetration {penetration:.0%}"
                        )
                        days: list[MarketDay] = []
                        for fleet, day_inputs in zip(fleets, inputs[name], strict=True):
                            if progress is not None:
                                progress.detail(f"{label}, {day_inputs.day}")
                            days.append(
                                solve_market_day(
                                    fleet, day_inputs, national_batteries, settings
                                )
                            )
                            if progress is not None:
                                progress.advance()
                        _record(samples[point], spec, days)
                        records.extend(
                            DiagnosticsRecord(
                                price_model=name,
                                rho=rho,
                                national_batteries=national_batteries,
                                penetration=penetration,
                                replication=index,
                                day=day.day,
                                diagnostics=day.diagnostics,
                            )
                            for day in days
                        )
                        if index == 0 and point == frame_point:
                            for day in days:
                                frames.extend(
                                    frames_for_day(
                                        day.prices, _fleet_day(spec, day, "joint")
                                    )
                                )

    market_levels = [
        _level(point, samples[point], samples[point._replace(national_batteries=0.0)])
        for point in points
    ]
    sweep = MarketSweep(
        price_model=models[0],
        robustness_models=models[1:],
        headline_rho=headline[0],
        headline_penetration=headline[1],
        solve_count=solve_count,
        wall_time_s=time.perf_counter() - started,
        diagnostics=_worst([level.diagnostics for level in market_levels]),
        levels=market_levels,
    )
    if release:
        require_no_stubs()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = RunMetadata(
        scenario=scenario,
        seed=scenario.seed,
        package_version=version(_PACKAGE),
        git_commit=git_commit(),
    )
    frames_path = output_dir / "frames.json"
    metadata_path = output_dir / "metadata.json"
    metrics_path = output_dir / "metrics.json"
    diagnostics_path = output_dir / "diagnostics.json"
    write_frames(frames_path, frames, metadata=metadata)
    _write_json(metadata_path, metadata.model_dump(mode="json"))
    _write_json(
        diagnostics_path, [record.model_dump(mode="json") for record in records]
    )
    _write_json(
        metrics_path,
        {"stubs": active_stubs(), "market": sweep.model_dump(mode="json")},
    )
    saved = read_market_sweep(metrics_path)
    figures = [
        output_dir / "added_load",
        output_dir / "saving_by_model",
        output_dir / "overload_by_penetration",
    ]
    save_figure(plot_added_load(saved), figures[0])
    save_figure(plot_saving_by_model(saved), figures[1])
    save_figure(plot_overload_by_penetration(saved), figures[2])
    return ScenarioRun(
        n_homes=scenario.n_homes,
        region=scenario.region,
        start=scenario.start,
        end=scenario.end,
        replications=scenario.replications,
        mode=scenario.mode,
        penetration=headline[1],
        metrics=[],
        without_batteries=[],
        diversity=[],
        battery=[],
        levels=[],
        crossing=None,
        frames_path=frames_path,
        metadata_path=metadata_path,
        metrics_path=metrics_path,
        market=sweep,
        market_figures=figures,
        diagnostics_path=diagnostics_path,
        stubs=active_stubs(),
    )


def _draw_fleets(
    scenario: Scenario,
    pool: HouseholdDemandPool,
    spec: NetworkSpec,
    rho: float,
    penetration: float,
    seed: int,
    dates: list[date],
) -> list[Fleet]:
    """One replication's fleet on each day, shared by every model and M."""
    generated = generate_fleet(
        pool,
        scenario.start,
        scenario.n_homes,
        seed,
        penetration,
        region=scenario.region,
        mode="diverse",
        distribution=scenario.battery,
        transformer_map=spec.home_transformer,
        rho=rho,
    )
    base = assign_transformers(generated.fleet, spec)
    return [with_demand(base, pool, day).fleet for day in dates]


def _record(samples: _Samples, spec: NetworkSpec, days: list[MarketDay]) -> None:
    """Add one replication's market and overload measures to ``samples``."""
    metrics = market_metrics(days)
    overloads = {
        "joint": _overload(spec, days, "joint"),
        "replanned": _overload(spec, days, "replanned"),
    }
    for name in _MARKET_METRICS:
        samples.values["market"][name].append(float(getattr(metrics, name)))
    for allocation, overload in overloads.items():
        for name in _OVERLOAD_METRICS:
            samples.values[allocation][name].append(float(getattr(overload, name)))
    samples.net_power_kw.append(metrics.net_power_per_battery_home_kw)
    samples.diagnostics.extend(day.diagnostics for day in days)


def _level(point: _Point, samples: _Samples, baseline: _Samples) -> MarketLevelResult:
    """Intervals for one point, and its paired differences from M = 0."""
    changes = {
        group: _paired(samples.values[group], baseline.values[group])
        for group in _GROUPS
    }
    replications = len(samples.net_power_kw)
    return MarketLevelResult(
        price_model=point.price_model,
        rho=point.rho,
        national_batteries=point.national_batteries,
        penetration=point.penetration,
        market=_estimates(samples.values["market"]),
        joint_overload=_estimates(samples.values["joint"]),
        replanned_overload=_estimates(samples.values["replanned"]),
        market_change=changes["market"],
        joint_overload_change=changes["joint"],
        replanned_overload_change=changes["replanned"],
        net_power_per_battery_home_kw=[
            sum(profile[slot] for profile in samples.net_power_kw) / replications
            for slot in range(len(samples.net_power_kw[0]))
        ],
        diagnostics=_worst(samples.diagnostics),
    )


def _fleet_day(spec: NetworkSpec, day: MarketDay, allocation: Allocation) -> FleetDay:
    """The day's homes running ``allocation``, and the network's flow."""
    homes = day.joint if allocation == "joint" else day.replanned
    profiles = [
        HomeProfile(
            home_id=home.home_id,
            grid_import_kw=list(home.schedule.grid_import_kw),
        )
        for home in homes
    ]
    return FleetDay(homes=homes, nodes=Network(spec=spec).evaluate(profiles))


def _overload(
    spec: NetworkSpec, days: list[MarketDay], allocation: Allocation
) -> ReplicationOverload:
    """Milestone-4 overload metrics with each home running ``allocation``."""
    reports: list[DayOverload] = [
        day_overload(day.day, _fleet_day(spec, day, allocation).nodes) for day in days
    ]
    return summarise_replication(reports)


def _estimates(samples: dict[str, list[float]]) -> list[MetricEstimate]:
    return [
        MetricEstimate(metric=name, interval=t_interval(values))
        for name, values in samples.items()
    ]


def _paired(
    samples: dict[str, list[float]], baseline: dict[str, list[float]]
) -> list[PairedDifference]:
    """In the loop minus M = 0, replication by replication."""
    return [
        PairedDifference(
            metric=name,
            left="in_the_loop",
            right="historical_prices",
            interval=t_interval(
                [a - b for a, b in zip(values, baseline[name], strict=True)]
            ),
        )
        for name, values in samples.items()
    ]


def _worst(items: list[EquilibriumDiagnostics]) -> EquilibriumDiagnostics:
    """The largest error, saving and load difference, and the summed counts.

    A point exceeds the tolerance when any of its days does.
    """
    return EquilibriumDiagnostics(
        linearisation_error_p_per_kwh=max(
            d.linearisation_error_p_per_kwh for d in items
        ),
        mode_break_slots=sum(d.mode_break_slots for d in items),
        max_replan_saving_p=max(d.max_replan_saving_p for d in items),
        total_replan_saving_p=sum(d.total_replan_saving_p for d in items),
        exceeds_tolerance=any(d.exceeds_tolerance for d in items),
        replanned_load_difference_gw=max(d.replanned_load_difference_gw for d in items),
        out_of_range_slots=sum(d.out_of_range_slots for d in items),
    )


def _dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
