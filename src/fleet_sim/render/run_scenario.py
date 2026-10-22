"""Rich view of a ``run-scenario`` result."""

from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from fleet_sim.commands.run_scenario import ScenarioRun
from fleet_sim.experiments.report import (
    ConfidenceInterval,
    MetricEstimate,
    PairedDifference,
)

_LABELS = {
    "peak_demand_kw": "Peak demand (kW)",
    "peak_demand_without_battery_kw": "Peak without batteries (kW)",
    "peak_to_average_ratio": "Peak-to-average ratio",
    "coincidence_factor": "Coincidence factor",
    "total_savings_pence": "Total saving (pence)",
    "savings_per_home_pence": "Saving per home (pence)",
}


def run_scenario_view(result: ScenarioRun) -> Group:
    """Each metric's interval, then the files the run wrote."""
    heading = Text(
        f"{result.n_homes} homes, region {result.region}, "
        f"{result.start.isoformat()} to {result.end.isoformat()}, "
        f"{result.replications} replications, {result.mode}"
    )
    blocks: list[Table | Text] = [
        heading,
        _metric_table("Scenario", result.metrics),
        _metric_table("Without batteries", result.without_batteries),
        _difference_table("Diverse minus identical", result.diversity),
        _difference_table("With batteries minus without", result.battery),
    ]
    if len(result.levels) > 1:
        blocks.append(_penetration_table(result))
    blocks.extend(
        [
            _path_line("Frames", result.frames_path),
            _path_line("Metadata", result.metadata_path),
            _path_line("Metrics", result.metrics_path),
            _path_line("Diversity figure", result.diversity_figure),
            _path_line("Penetration figure", result.penetration_figure),
        ]
    )
    return Group(*blocks)


def show_run_scenario(result: ScenarioRun) -> None:
    """Print ``run_scenario_view`` to the terminal.

    ``crop`` is off so a figure path longer than the terminal stays intact.
    """
    Console().print(run_scenario_view(result), crop=False, overflow="ignore")


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
