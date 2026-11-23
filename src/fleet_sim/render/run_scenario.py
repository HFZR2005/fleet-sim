"""Rich view of a ``run-scenario`` result."""

from collections.abc import Sequence
from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from fleet_sim.models.results import (
    ConfidenceInterval,
    MarketSweep,
    MetricEstimate,
    PairedDifference,
    ScenarioRun,
)

_LABELS = {
    "peak_demand_kw": "Peak demand (kW)",
    "peak_demand_without_battery_kw": "Peak without batteries (kW)",
    "peak_to_average_ratio": "Peak-to-average ratio",
    "coincidence_factor": "Coincidence factor",
    "total_savings_pence": "Total saving (pence)",
    "savings_per_home_pence": "Saving per home (pence)",
    "transformers_overloaded_share": "Transformers overloaded",
    "mean_peak_utilisation": "Mean peak utilisation",
    "worst_peak_utilisation": "Worst peak utilisation",
    "total_overload_energy_kwh": "Total overload energy (kWh)",
    "hidden_overload_share": "Hidden overload share",
}

_OVERLOADED = "transformers_overloaded_share"
_MARKET_LABELS = {
    "peak_added_load_gw": "Peak added load (GW)",
    "peak_added_load_hour": "Peak hour",
    "saving_per_battery_home_p_per_day": "Saving per battery home (p/day)",
    "non_battery_price_change_p_per_day": "Price change, no battery (p/day)",
    "mean_charge_price_p_per_kwh": "Charging price (p/kWh)",
    "mean_discharge_price_p_per_kwh": "Discharging price (p/kWh)",
}


def run_scenario_view(result: ScenarioRun) -> Group:
    """Each metric's interval, then the files the run wrote."""
    prefix = "STUB " if result.stubs else ""
    heading = Text(
        f"{prefix}{result.n_homes} homes, region {result.region}, "
        f"{result.start.isoformat()} to {result.end.isoformat()}, "
        f"{result.replications} replications, {result.mode}"
    )
    blocks: list[Table | Text] = [heading]
    if result.metrics:
        title = "STUB overload" if result.stubs else "Scenario"
        blocks.append(_metric_table(title, result.metrics))
    if result.without_batteries:
        blocks.append(_metric_table("Without batteries", result.without_batteries))
    if result.diversity:
        blocks.append(_difference_table("Diverse minus identical", result.diversity))
    if result.battery:
        blocks.append(_difference_table("With batteries minus without", result.battery))
    if len(result.levels) > 1:
        blocks.append(_penetration_table(result))
    if len(result.network_levels) > 1:
        blocks.append(_network_penetration_table(result))
    if result.market is not None:
        blocks.extend(_market_blocks(result.market, stubbed=bool(result.stubs)))
    if result.stubs:
        listed = Text("Active stubs", style="bold")
        listed.append("\n" + "\n".join(result.stubs))
        blocks.append(listed)
    blocks.extend(
        [
            _path_line("Frames", result.frames_path),
            _path_line("Metadata", result.metadata_path),
            _path_line("Metrics", result.metrics_path),
        ]
    )
    if result.diversity_figure is not None:
        blocks.append(_path_line("Diversity figure", result.diversity_figure))
    if result.penetration_figure is not None:
        blocks.append(_path_line("Penetration figure", result.penetration_figure))
    if result.overload_figure is not None:
        blocks.append(_path_line("Overload figure", result.overload_figure))
    if result.diagnostics_path is not None:
        blocks.append(_path_line("Diagnostics", result.diagnostics_path))
    for figure in result.market_figures:
        blocks.append(_path_line("Market figure", figure))
    return Group(*blocks)


def show_run_scenario(result: ScenarioRun) -> None:
    """Print ``run_scenario_view`` to the terminal.

    ``crop`` is off so a figure path longer than the terminal stays intact.
    """
    Console().print(run_scenario_view(result), crop=False, overflow="ignore")


def _market_blocks(sweep: MarketSweep, *, stubbed: bool) -> list[Table | Text]:
    """Market measures, overloads, and diagnostics, one row per point.

    Each measure is shown with its interval, and then as the paired change
    from M = 0. Every metric is in ``metrics.json``; the overload tables show
    the share of transformers overloaded.
    """
    prefix = "STUB " if stubbed else ""
    market = Table(title=f"{prefix}Market measures")
    change = Table(title=f"{prefix}Market measures, change from M = 0")
    for table in (market, change):
        _point_columns(table)
        for label in _MARKET_LABELS.values():
            table.add_column(label, justify="right")
    overload = Table(title=f"{prefix}Transformers overloaded")
    _point_columns(overload)
    for heading in ("Joint", "Change", "Re-planned", "Change"):
        overload.add_column(heading, justify="right")
    diagnostics = Table(title=f"{prefix}Diagnostics (worst over replications, days)")
    _point_columns(diagnostics)
    for heading in (
        "Linearisation error (p/kWh)",
        "(MODE) breaks",
        "Largest re-plan saving (p)",
        "Total re-plan saving (p)",
        "Tolerance",
        "Re-planned load difference (GW)",
        "Out-of-range slots",
    ):
        diagnostics.add_column(heading, justify="right")

    for level in sweep.levels:
        point = (
            level.price_model,
            f"{level.rho:g}",
            f"{level.national_batteries / 1e6:g}",
            f"{100 * level.penetration:.0f}%",
        )
        values = {m.metric: m.interval for m in level.market}
        changes = {m.metric: m.interval for m in level.market_change}
        market.add_row(*point, *(_ci(values.get(name)) for name in _MARKET_LABELS))
        change.add_row(*point, *(_ci(changes.get(name)) for name in _MARKET_LABELS))
        overload.add_row(
            *point,
            _ci(_find(level.joint_overload, _OVERLOADED)),
            _ci(_find(level.joint_overload_change, _OVERLOADED)),
            _ci(_find(level.replanned_overload, _OVERLOADED)),
            _ci(_find(level.replanned_overload_change, _OVERLOADED)),
        )
        d = level.diagnostics
        diagnostics.add_row(
            *point,
            f"{d.linearisation_error_p_per_kwh:.3f}",
            str(d.mode_break_slots),
            f"{d.max_replan_saving_p:.2f}",
            f"{d.total_replan_saving_p:.2f}",
            "exceeded" if d.exceeds_tolerance else "within",
            f"{d.replanned_load_difference_gw:.3f}",
            str(d.out_of_range_slots),
        )
    d = sweep.diagnostics
    run = Text(
        f"{prefix}{sweep.solve_count} fleet-day solves in {sweep.wall_time_s:.1f} s. "
        f"Worst over the run: linearisation error "
        f"{d.linearisation_error_p_per_kwh:.3f} p/kWh, "
        f"(MODE) breaks {d.mode_break_slots}, "
        f"largest re-plan saving {d.max_replan_saving_p:.2f} p "
        f"({'above' if d.exceeds_tolerance else 'within'} tolerance), "
        f"re-planned load differs by up to {d.replanned_load_difference_gw:.3f} GW, "
        f"out-of-range slots {d.out_of_range_slots}"
    )
    return [market, change, overload, diagnostics, run]


def _point_columns(table: Table) -> None:
    for heading in ("Price model", "ρ", "M (millions)", "Penetration"):
        table.add_column(heading)


def _find(
    rows: Sequence[MetricEstimate | PairedDifference], name: str
) -> ConfidenceInterval | None:
    return next((row.interval for row in rows if row.metric == name), None)


def _metric_table(title: str, rows: list[MetricEstimate]) -> Table:
    table = Table(title=title)
    table.add_column("Measure")
    table.add_column("Mean", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("High", justify="right")
    for row in rows:
        table.add_row(_label(row.metric), *_bounds(row.interval))
    return table


def _difference_table(title: str, rows: list[PairedDifference]) -> Table:
    table = Table(title=title)
    table.add_column("Measure")
    table.add_column("Mean", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("High", justify="right")
    for row in rows:
        table.add_row(_label(row.metric), *_bounds(row.interval))
    return table


def _penetration_table(result: ScenarioRun) -> Table:
    table = Table(title="Penetration")
    table.add_column("Penetration")
    table.add_column("Peak demand (kW)", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("High", justify="right")
    for level in result.levels:
        interval = next(
            row.interval for row in level.metrics if row.metric == "peak_demand_kw"
        )
        table.add_row(f"{100 * level.penetration:.0f}%", *_bounds(interval))
    return table


def _network_penetration_table(result: ScenarioRun) -> Table:
    table = Table(title="Network overload by penetration")
    table.add_column("Penetration")
    table.add_column("Overloaded share", justify="right")
    table.add_column("Mean utilisation", justify="right")
    table.add_column("Overload energy (kWh)", justify="right")
    table.add_column("Hidden share", justify="right")
    for level in result.network_levels:
        by_name = {m.metric: m.interval for m in level.metrics}
        table.add_row(
            f"{100 * level.penetration:.0f}%",
            _ci(by_name.get("transformers_overloaded_share")),
            _ci(by_name.get("mean_peak_utilisation")),
            _ci(by_name.get("total_overload_energy_kwh")),
            _ci(by_name.get("hidden_overload_share")),
        )
    return table


def _ci(interval: ConfidenceInterval | None) -> str:
    if interval is None:
        return ""
    return f"{interval.mean:.2f} ({interval.low:.2f}–{interval.high:.2f})"


def _bounds(interval: ConfidenceInterval) -> tuple[str, str, str]:
    return (f"{interval.mean:.2f}", f"{interval.low:.2f}", f"{interval.high:.2f}")


def _label(metric: str) -> str:
    return _LABELS.get(metric, metric)


def _path_line(label: str, path: Path) -> Text:
    line = Text(no_wrap=True, overflow="ignore")
    line.append(f"{label}  ", style="dim")
    if path.suffix == "":
        line.append(str(path.with_suffix(".svg")))
        line.append(" and ", style="dim")
        line.append(str(path.with_suffix(".png")))
    else:
        line.append(str(path))
    return line
