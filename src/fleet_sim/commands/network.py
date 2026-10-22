"""A scenario that names transformers: fleet, tree, solve, overload, figure.

Topology, the overload numbers, and the figure are stubs. The summary across
replications is the same t-interval as any other metric.
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
from fleet_sim.models.network import HomeProfile
from fleet_sim.models.results import MetricEstimate, ScenarioRun
from fleet_sim.models.scenario import RunMetadata, Scenario
from fleet_sim.progress import RunProgress
from fleet_sim.scenario import git_commit
from fleet_sim.stubs import active_stubs, begin_stub_run, require_no_stubs
from fleet_sim.viz.network import plot_network_overload
from fleet_sim.viz.save import save_figure

_PACKAGE = "fleet-sim"
_METRICS = (
    "transformers_overloaded_share",
    "mean_peak_utilisation",
    "worst_peak_utilisation",
    "total_overload_energy_kwh",
    "hidden_overload_share",
)


def run_network_scenario(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    output_dir: Path,
    progress: RunProgress | None = None,
    release: bool = False,
) -> ScenarioRun:
    """Run ``scenario`` once the ``[network]`` section is present."""
    if scenario.network is None:
        raise ValueError("a network scenario needs a [network] section")
    levels = scenario.penetration_levels()
    if len(levels) != 1:
        raise ValueError(
            "a network scenario takes one penetration; "
            f"a sweep over {len(levels)} values is a later step"
        )
    penetration = levels[0]
    if scenario.replications < 2:
        raise ValueError(
            f"a t-interval needs at least 2 replications (got {scenario.replications})"
        )
    begin_stub_run()
    settings = scenario.network
    dates = _dates(scenario.start, scenario.end)
    if progress is not None:
        progress.task("Network", scenario.replications * len(dates))
    samples: dict[str, list[float]] = {name: [] for name in _METRICS}
    frame_source: list[Frame] = []
    for index in range(scenario.replications):
        seed = replication_seed(scenario.seed, index)
        generated = generate_fleet(
            pool,
            scenario.start,
            scenario.n_homes,
            seed,
            penetration,
            region=scenario.region,
            mode="diverse",
            distribution=scenario.battery,
        )
        spec = build_topology(
            [home.home_id for home in generated.fleet.homes], settings
        )
        base = assign_transformers(generated.fleet, spec)
        day_reports = []
        for day in dates:
            if progress is not None:
                progress.detail(
                    f"replication {index + 1}/{scenario.replications}, {day.isoformat()}"
                )
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
            if index == 0:
                frame_source.extend(frames_for_day(prices, solved))
            if progress is not None:
                progress.advance()
        summary = summarise_replication(day_reports)
        for name in _METRICS:
            samples[name].append(float(getattr(summary, name)))
    metrics = [
        MetricEstimate(metric=name, interval=t_interval(samples[name]))
        for name in _METRICS
    ]
    figure = plot_network_overload(metrics)
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
    overload_figure = output_dir / "overload"
    write_frames(frames_path, frame_source, metadata=metadata)
    _write_json(metadata_path, metadata.model_dump(mode="json"))
    _write_json(
        metrics_path,
        {
            "stubs": active_stubs(),
            "overload": [item.model_dump(mode="json") for item in metrics],
        },
    )
    save_figure(figure, overload_figure)
    return ScenarioRun(
        n_homes=scenario.n_homes,
        region=scenario.region,
        start=scenario.start,
        end=scenario.end,
        replications=scenario.replications,
        mode=scenario.mode,
        penetration=penetration,
        metrics=metrics,
        without_batteries=[],
        diversity=[],
        battery=[],
        levels=[],
        crossing=None,
        frames_path=frames_path,
        metadata_path=metadata_path,
        metrics_path=metrics_path,
        stubs=active_stubs(),
        overload_figure=overload_figure,
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
