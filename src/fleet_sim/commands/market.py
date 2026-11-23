"""A scenario with a ``[market]`` section: the fleet in the loop.

For each replication, national fleet size M and local penetration: draw the
fleet on the scenario's topology, then for each day build the price inputs,
solve the equilibrium, and evaluate the network under both allocations.
Each day's price inputs are built once and shared by every replication.
See ``docs/architecture.md``, Fleet in the loop.
"""

import json
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.experiments.report import replication_seed, t_interval
from fleet_sim.fleet.frames import frames_for_day, write_frames
from fleet_sim.fleet.generate import generate_fleet, with_demand
from fleet_sim.fleet.market import market_metrics, solve_market_day
from fleet_sim.fleet.network import Network
from fleet_sim.fleet.overload import day_overload, summarise_replication
from fleet_sim.fleet.price_inputs import DayPriceInputs, day_price_inputs
from fleet_sim.fleet.topology import assign_transformers, build_topology
from fleet_sim.models.fleet import FleetDay
from fleet_sim.models.frames import Frame
from fleet_sim.models.market import EquilibriumDiagnostics, MarketDay, MarketSettings
from fleet_sim.models.network import (
    DayOverload,
    HomeProfile,
    NetworkSpec,
    ReplicationOverload,
)
from fleet_sim.models.results import MarketLevelResult, MetricEstimate, ScenarioRun
from fleet_sim.models.scenario import RunMetadata, Scenario
from fleet_sim.prices.config import load_config
from fleet_sim.prices.parameters import load_price_model
from fleet_sim.progress import RunProgress
from fleet_sim.random_streams import RandomStreams
from fleet_sim.scenario import git_commit
from fleet_sim.stubs import active_stubs, begin_stub_run, require_no_stubs
from fleet_sim.viz.market import plot_market_placeholder
from fleet_sim.viz.save import save_figure

_PACKAGE = "fleet-sim"
_CALIBRATION = Path("calibration/price_curves.toml")

Allocation = Literal["joint", "replanned"]
_OVERLOAD_METRICS = (
    "transformers_overloaded_share",
    "mean_peak_utilisation",
    "worst_peak_utilisation",
    "total_overload_energy_kwh",
    "hidden_overload_share",
)
_MARKET_METRICS = (
    "peak_added_load_gw",
    "saving_per_battery_home_p_per_day",
    "non_battery_price_change_p_per_day",
    "mean_charge_price_p_per_kwh",
    "mean_discharge_price_p_per_kwh",
)

# samples[(M, penetration)][group][metric] -> one value per replication
_Samples = dict[tuple[float, float], dict[str, dict[str, list[float]]]]


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
    begin_stub_run()
    settings = scenario.market
    levels = settings.national_battery_levels()
    penetrations = scenario.penetration_levels()
    dates = _dates(scenario.start, scenario.end)
    calibration = load_config(_CALIBRATION)
    model = load_price_model(settings.price_parameters_file, settings.price_model)
    price_cache = Path(calibration.data.cache_dir) if cache_dir is None else cache_dir
    inputs = [
        day_price_inputs(
            day,
            scenario.region,
            price_cache,
            model=model,
            fuel_cost=calibration.fuel_cost,
        )
        for day in dates
    ]
    if progress is not None:
        progress.task(
            "Market",
            scenario.replications * len(levels) * len(penetrations) * len(dates),
        )
    home_ids = [f"home-{i + 1}" for i in range(scenario.n_homes)]
    spec = build_topology(home_ids, scenario.network, RandomStreams(scenario.seed))

    points = [(m, p) for m in levels for p in penetrations]
    samples: _Samples = {
        point: {
            "joint": {name: [] for name in _OVERLOAD_METRICS},
            "replanned": {name: [] for name in _OVERLOAD_METRICS},
            "market": {name: [] for name in _MARKET_METRICS},
        }
        for point in points
    }
    diagnostics: dict[tuple[float, float], list[EquilibriumDiagnostics]] = {
        point: [] for point in points
    }
    frames: list[Frame] = []

    for index in range(scenario.replications):
        seed = replication_seed(scenario.seed, index)
        for national_batteries, penetration in points:
            label = (
                f"replication {index + 1}/{scenario.replications}, "
                f"M {national_batteries:,.0f}, penetration {penetration:.0%}"
            )
            days = _run_days(
                scenario,
                settings,
                pool,
                spec,
                national_batteries,
                penetration,
                seed,
                inputs,
                progress,
                label,
            )
            group = samples[(national_batteries, penetration)]
            joint = _overload(spec, days, "joint")
            replanned = _overload(spec, days, "replanned")
            metrics = market_metrics(days)
            for name in _OVERLOAD_METRICS:
                group["joint"][name].append(float(getattr(joint, name)))
                group["replanned"][name].append(float(getattr(replanned, name)))
            for name in _MARKET_METRICS:
                group["market"][name].append(float(getattr(metrics, name)))
            diagnostics[(national_batteries, penetration)].extend(
                day.diagnostics for day in days
            )
            if index == 0 and (national_batteries, penetration) == points[-1]:
                for day in days:
                    frames.extend(
                        frames_for_day(day.prices, _fleet_day(spec, day, "joint"))
                    )

    market_levels = [
        MarketLevelResult(
            national_batteries=m,
            penetration=p,
            joint_overload=_estimates(samples[(m, p)]["joint"]),
            replanned_overload=_estimates(samples[(m, p)]["replanned"]),
            market=_estimates(samples[(m, p)]["market"]),
            diagnostics=_worst(diagnostics[(m, p)]),
        )
        for m, p in points
    ]
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
    write_frames(frames_path, frames, metadata=metadata)
    _write_json(metadata_path, metadata.model_dump(mode="json"))
    market_figure = output_dir / "market"
    save_figure(plot_market_placeholder(market_levels), market_figure)
    _write_json(
        metrics_path,
        {
            "stubs": active_stubs(),
            "market_levels": [level.model_dump(mode="json") for level in market_levels],
        },
    )
    return ScenarioRun(
        n_homes=scenario.n_homes,
        region=scenario.region,
        start=scenario.start,
        end=scenario.end,
        replications=scenario.replications,
        mode=scenario.mode,
        penetration=penetrations[-1],
        metrics=[],
        without_batteries=[],
        diversity=[],
        battery=[],
        levels=[],
        crossing=None,
        frames_path=frames_path,
        metadata_path=metadata_path,
        metrics_path=metrics_path,
        market_levels=market_levels,
        market_figure=market_figure,
        stubs=active_stubs(),
    )


def _run_days(
    scenario: Scenario,
    settings: MarketSettings,
    pool: HouseholdDemandPool,
    spec: NetworkSpec,
    national_batteries: float,
    penetration: float,
    seed: int,
    inputs: list[DayPriceInputs],
    progress: RunProgress | None,
    label: str,
) -> list[MarketDay]:
    """Draw one fleet and solve each of its days in the loop."""
    assert scenario.network is not None
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
        rho=scenario.network.rho,
    )
    base = assign_transformers(generated.fleet, spec)
    days: list[MarketDay] = []
    for day_inputs in inputs:
        if progress is not None:
            progress.detail(f"{label}, {day_inputs.day.isoformat()}")
        fleet = with_demand(base, pool, day_inputs.day).fleet
        days.append(solve_market_day(fleet, day_inputs, national_batteries, settings))
        if progress is not None:
            progress.advance()
    return days


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


def _worst(items: list[EquilibriumDiagnostics]) -> EquilibriumDiagnostics:
    """The largest error and saving, and the summed counts, over ``items``."""
    return EquilibriumDiagnostics(
        linearisation_error_p_per_kwh=max(
            d.linearisation_error_p_per_kwh for d in items
        ),
        mode_break_slots=sum(d.mode_break_slots for d in items),
        max_replan_saving_p=max(d.max_replan_saving_p for d in items),
        total_replan_saving_p=sum(d.total_replan_saving_p for d in items),
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
