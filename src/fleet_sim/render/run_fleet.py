"""Rich view of a ``run-fleet`` result."""

from datetime import date
from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from fleet_sim.models.results import FleetRange, Spread

# The new peak is the one the fleet creates, so it is the bold row.
_WITH_BATTERY = "bold blue"
_WITHOUT_BATTERY = "dim"


def run_fleet_view(
    report: FleetRange,
    *,
    n_homes: int,
    region: str,
    frames_path: Path,
    herding_path: Path,
    peaks_path: Path,
    herding_day: date,
) -> Group:
    """The spread of each fleet measure, then the files the run wrote.

    Savings are green when the median is above zero, dim when it is zero,
    and red when the fleet paid more than it would have without batteries.
    """
    start = report.days[0].day
    end = report.days[-1].day
    heading = Text(f"{n_homes} homes, region {region}, {start} to {end}")
    return Group(
        heading,
        _spread_table(report),
        _labelled("Herding day", herding_day.isoformat()),
        _path_line("Frames", frames_path),
        _path_line("Herding figure", herding_path),
        _path_line("Peaks figure", peaks_path),
    )


def show_run_fleet(
    report: FleetRange,
    *,
    n_homes: int,
    region: str,
    frames_path: Path,
    herding_path: Path,
    peaks_path: Path,
    herding_day: date,
) -> None:
    """Print ``run_fleet_view`` to the terminal.

    ``crop`` is off so a figure path longer than the terminal stays intact.
    """
    Console().print(
        run_fleet_view(
            report,
            n_homes=n_homes,
            region=region,
            frames_path=frames_path,
            herding_path=herding_path,
            peaks_path=peaks_path,
            herding_day=herding_day,
        ),
        crop=False,
        overflow="ignore",
    )


def _spread_table(report: FleetRange) -> Table:
    table = Table(title="Across days")
    table.add_column("Measure")
    table.add_column("Median", justify="right")
    table.add_column("Minimum", justify="right")
    table.add_column("Maximum", justify="right")
    _power_row(table, "Peak with batteries (kW)", report.peak_demand_kw, _WITH_BATTERY)
    _power_row(
        table,
        "Peak without batteries (kW)",
        report.peak_demand_without_battery_kw,
        _WITHOUT_BATTERY,
    )
    _ratio_row(table, "Peak-to-average ratio", report.peak_to_average_ratio)
    _ratio_row(table, "Coincidence factor", report.coincidence_factor)
    savings = _savings_style(report.total_savings_pence.median)
    _pence_row(table, "Total savings (pence)", report.total_savings_pence, savings)
    _pence_row(
        table, "Savings per home (pence)", report.savings_per_home_pence, savings
    )
    return table


def _power_row(table: Table, label: str, spread: Spread, style: str) -> None:
    table.add_row(
        label,
        f"{spread.median:.2f}",
        f"{spread.minimum:.2f}",
        f"{spread.maximum:.2f}",
        style=style,
    )


def _pence_row(table: Table, label: str, spread: Spread, style: str) -> None:
    table.add_row(
        label,
        f"{spread.median:.2f}",
        f"{spread.minimum:.2f}",
        f"{spread.maximum:.2f}",
        style=style,
    )


def _ratio_row(table: Table, label: str, spread: Spread) -> None:
    table.add_row(
        label,
        f"{spread.median:.3f}",
        f"{spread.minimum:.3f}",
        f"{spread.maximum:.3f}",
    )


def _savings_style(median_pence: float) -> str:
    shown = f"{median_pence:.2f}"
    if shown.startswith("-"):
        return "red"
    if shown == "0.00":
        return "dim"
    return "green"


def _labelled(label: str, value: str) -> Text:
    line = Text(no_wrap=True, overflow="ignore")
    line.append(f"{label}  ", style="dim")
    line.append(value)
    return line


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
