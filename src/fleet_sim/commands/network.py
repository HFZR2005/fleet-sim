"""A scenario that names transformers: fleet, tree, solve, overload, figure.

The figure is a stub. The summary across replications is the same t-interval
as any other metric.
"""

import json
from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.experiments.report import replication_seed, t_interval
from fleet_sim.fleet.frames import frames_for_day, write_frames
from fleet_sim.fleet.generate import generate_fleet, mean_fleet, with_demand
from fleet_sim.fleet.network import Network
from fleet_sim.fleet.overload import day_overload, summarise_replication
from fleet_sim.fleet.solve import solve_fleet
from fleet_sim.fleet.topology import assign_transformers, build_topology
from fleet_sim.models.frames import Frame
from fleet_sim.models.network import HomeProfile, NetworkSpec, ReplicationOverload
from fleet_sim.models.results import (
    MetricEstimate,
    NetworkLevelResult,
    OverloadCrossing,
    PairedDifference,
    ScenarioRun,
)
from fleet_sim.models.scenario import RunMetadata, Scenario
from fleet_sim.progress import RunProgress
from fleet_sim.random_streams import RandomStreams
from fleet_sim.scenario import git_commit
from fleet_sim.stubs import active_stubs, begin_stub_run, require_no_stubs
from fleet_sim.viz.network import (
    OverloadSeries,
    plot_overload_curve,
    plot_transformer_day,
    plot_utilisation_distribution,
    read_transformer_day,
    read_utilisation_distribution,
)
from fleet_sim.viz.save import save_figure

_PACKAGE = "fleet-sim"
_METRICS = (
    "transformers_overloaded_share",
    "mean_peak_utilisation",
    "worst_peak_utilisation",
    "total_overload_energy_kwh",
    "hidden_overload_share",
)
_CROSSING_METRIC = "transformers_overloaded_share"


def run_network_scenario(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    output_dir: Path,
    progress: RunProgress | None = None,
    release: bool = False,
) -> ScenarioRun:
    """Run ``scenario`` once the ``[network]`` section is present.

    When the scenario names more than one penetration level, each level is
    swept and overload metrics are collected at every level with a paired
    without-batteries comparison. See ``docs/formulation.md``, Overload
    crossing.
    """
    if scenario.network is None:
        raise ValueError("a network scenario needs a [network] section")
    if scenario.replications < 2:
        raise ValueError(
            f"a t-interval needs at least 2 replications (got {scenario.replications})"
        )
    begin_stub_run()
    settings = scenario.network
    penetrations = scenario.penetration_levels()
    dates = _dates(scenario.start, scenario.end)
    n_passes = len(penetrations) * 2  # with + without batteries
    if progress is not None:
        progress.task("Network", scenario.replications * n_passes * len(dates))
    home_ids = [f"home-{i + 1}" for i in range(scenario.n_homes)]
    topology_streams = RandomStreams(scenario.seed)
    spec = build_topology(home_ids, settings, topology_streams)

    # samples[penetration]["with"|"without"][metric][replication]
    samples: dict[float, dict[str, dict[str, list[float]]]] = {
        p: {
            "with": {name: [] for name in _METRICS},
            "without": {name: [] for name in _METRICS},
        }
        for p in penetrations
    }
    frame_source: list[Frame] = []

    for index in range(scenario.replications):
        seed = replication_seed(scenario.seed, index)
        no_battery: ReplicationOverload | None = None
        for penetration in penetrations:
            label = (
                f"replication {index + 1}/{scenario.replications}, "
                f"penetration {penetration:.0%}"
            )
            summary = _run_one_replication(
                scenario,
                pool,
                price_source,
                spec,
                penetration,
                seed,
                dates,
                progress,
                f"{label} (with batteries)",
                collect_frames=(index == 0 and penetration == penetrations[-1]),
                frame_sink=frame_source,
            )
            for name in _METRICS:
                samples[penetration]["with"][name].append(float(getattr(summary, name)))
            if no_battery is None:
                no_battery = _run_one_replication(
                    scenario,
                    pool,
                    price_source,
                    spec,
                    0.0,
                    seed,
                    dates,
                    progress,
                    f"{label} (without batteries)",
                    collect_frames=False,
                    frame_sink=frame_source,
                )
            else:
                # The without-batteries pass is the same for every penetration
                # within a replication (same topology, same demand, penetration=0).
                # Advance progress without re-running.
                if progress is not None:
                    for _ in dates:
                        progress.advance()
            for name in _METRICS:
                samples[penetration]["without"][name].append(
                    float(getattr(no_battery, name))
                )

    network_levels = _build_levels(penetrations, samples)
    crossing = _overload_crossing(penetrations, samples)
    highest_metrics = network_levels[-1].metrics if network_levels else []
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
    write_frames(frames_path, frame_source, metadata=metadata)
    _write_json(metadata_path, metadata.model_dump(mode="json"))
    _write_json(
        metrics_path,
        {
            "stubs": active_stubs(),
            "overload": [item.model_dump(mode="json") for item in highest_metrics],
            "network_levels": [
                level.model_dump(mode="json") for level in network_levels
            ],
            "overload_crossing": (
                crossing.model_dump(mode="json") if crossing else None
            ),
        },
    )

    overload_curve_path = output_dir / "overload_curve"
    curve_series = OverloadSeries(
        label=f"ρ = {settings.rho}",
        penetrations=penetrations,
        bands=[
            _metric_band(level.metrics, "transformers_overloaded_share")
            for level in network_levels
        ],
    )
    save_figure(plot_overload_curve([curve_series]), overload_curve_path)

    transformer_day_path = output_dir / "transformer_day"
    transformer_day = read_transformer_day(frames_path)
    save_figure(plot_transformer_day(transformer_day), transformer_day_path)

    utilisation_dist_path = output_dir / "utilisation_dist"
    util_data = read_utilisation_distribution(frames_path)
    save_figure(plot_utilisation_distribution(util_data), utilisation_dist_path)

    return ScenarioRun(
        n_homes=scenario.n_homes,
        region=scenario.region,
        start=scenario.start,
        end=scenario.end,
        replications=scenario.replications,
        mode=scenario.mode,
        penetration=penetrations[-1],
        metrics=highest_metrics,
        without_batteries=network_levels[-1].without_batteries
        if network_levels
        else [],
        diversity=[],
        battery=network_levels[-1].battery_effect if network_levels else [],
        levels=[],
        crossing=None,
        frames_path=frames_path,
        metadata_path=metadata_path,
        metrics_path=metrics_path,
        stubs=active_stubs(),
        overload_figure=overload_curve_path,
        network_levels=network_levels,
        overload_crossing=crossing,
    )


def _run_one_replication(
    scenario: Scenario,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    spec: NetworkSpec,
    penetration: float,
    seed: int,
    dates: list[date],
    progress: RunProgress | None,
    label: str,
    *,
    collect_frames: bool,
    frame_sink: list[Frame],
) -> ReplicationOverload:
    """Generate, solve, evaluate, and summarise one replication."""
    assert scenario.network is not None
    settings = scenario.network
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
        rho=settings.rho,
    )
    base = assign_transformers(generated.fleet, spec)
    day_reports = []
    for day in dates:
        if progress is not None:
            progress.detail(f"{label}, {day.isoformat()}")
        prices = price_source.load(day, scenario.region)
        loaded = with_demand(base, pool, day)
        fleet = loaded.fleet
        if scenario.mode == "identical":
            fleet = assign_transformers(mean_fleet(fleet), spec)
        solved = solve_fleet(fleet, prices, None)
        profiles = [
            HomeProfile(
                home_id=home.home_id,
                grid_import_kw=list(home.schedule.grid_import_kw),
            )
            for home in solved.homes
        ]
        nodes = Network(spec=spec).evaluate(profiles)
        solved = solved.model_copy(update={"nodes": nodes})
        day_reports.append(day_overload(day, nodes))
        if collect_frames:
            frame_sink.extend(frames_for_day(prices, solved))
        if progress is not None:
            progress.advance()
    return summarise_replication(day_reports)


def _build_levels(
    penetrations: list[float],
    samples: dict[float, dict[str, dict[str, list[float]]]],
) -> list[NetworkLevelResult]:
    """Build ``NetworkLevelResult`` for each penetration."""
    levels: list[NetworkLevelResult] = []
    for p in penetrations:
        with_metrics = [
            MetricEstimate(metric=name, interval=t_interval(samples[p]["with"][name]))
            for name in _METRICS
        ]
        without_metrics = [
            MetricEstimate(
                metric=name, interval=t_interval(samples[p]["without"][name])
            )
            for name in _METRICS
        ]
        paired = [
            PairedDifference(
                metric=name,
                left="with_batteries",
                right="without_batteries",
                interval=t_interval(
                    [
                        w - wo
                        for w, wo in zip(
                            samples[p]["with"][name],
                            samples[p]["without"][name],
                            strict=True,
                        )
                    ]
                ),
            )
            for name in _METRICS
        ]
        levels.append(
            NetworkLevelResult(
                penetration=p,
                metrics=with_metrics,
                without_batteries=without_metrics,
                battery_effect=paired,
            )
        )
    return levels


def _overload_crossing(
    penetrations: list[float],
    samples: dict[float, dict[str, dict[str, list[float]]]],
) -> OverloadCrossing | None:
    """Find the first penetration where overloads appear."""
    if len(penetrations) < 2:
        return None
    n_replications = len(samples[penetrations[0]]["with"][_CROSSING_METRIC])
    per_replication: list[float | None] = []
    for index in range(n_replications):
        crossing: float | None = None
        for p in penetrations:
            if samples[p]["with"][_CROSSING_METRIC][index] > 0:
                crossing = p
                break
        per_replication.append(crossing)
    crossed = [p for p in per_replication if p is not None]
    level_metrics = {
        p: t_interval(samples[p]["with"][_CROSSING_METRIC]) for p in penetrations
    }
    above = next(
        (p for p in penetrations if level_metrics[p].low > 0),
        None,
    )
    return OverloadCrossing(
        metric=_CROSSING_METRIC,
        per_replication=per_replication,
        lowest=min(crossed) if crossed else None,
        highest=max(crossed) if crossed else None,
        interval_above_zero_from=above,
    )


def _metric_band(
    metrics: list[MetricEstimate], name: str
) -> tuple[float, float, float]:
    """Extract ``(mean, low, high)`` for ``name`` from a metrics list."""
    for item in metrics:
        if item.metric == name:
            return (item.interval.mean, item.interval.low, item.interval.high)
    raise ValueError(f"no metric named {name}")


def _dates(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    return days


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
