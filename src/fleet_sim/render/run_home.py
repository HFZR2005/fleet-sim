"""Rich view of a ``run-home`` result."""

from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from fleet_sim.models.results import ComparisonReport

# Terminal styles, so a light or dark background can still read them.
# Dim is the baseline, cyan the rule, blue the optimiser.
_NO_BATTERY = "dim"
_RULE = "cyan"
_OPTIMISER = "bold blue"


def run_home_view(report: ComparisonReport, n: int, output: Path) -> Group:
    """Bills, the rule's share of the optimal saving, and the figure paths.

    The figure path is one line, so a long path is not folded in half.
    A positive share is green, a zero share is dim, and a negative share is red.
    """
    bills = Table(title="Bills")
    bills.add_column("Strategy")
    bills.add_column("Pence", justify="right")
    bills.add_row(
        "No battery",
        f"{report.no_battery_cost_pence:.2f}",
        style=_NO_BATTERY,
    )
    bills.add_row(
        f"Rule (n={n})",
        f"{report.rule_cost_pence:.2f}",
        style=_RULE,
    )
    bills.add_row(
        "Optimiser",
        f"{report.optimiser_cost_pence:.2f}",
        style=_OPTIMISER,
    )
    return Group(
        bills,
        _share_line(report.rule_savings_share),
        _figure_line(output),
    )


def _share_line(share: float) -> Text:
    shown = f"{share:.3f}"
    if shown.startswith("-"):
        style = "red"
    elif shown == "0.000":
        style = "dim"
    else:
        style = "green"
    line = Text()
    line.append("Rule share of optimal savings  ")
    line.append(shown, style=style)
    return line


def _figure_line(output: Path) -> Text:
    line = Text(no_wrap=True, overflow="ignore")
    line.append("Figure  ", style="dim")
    line.append(str(output.with_suffix(".svg")))
    line.append(" and ", style="dim")
    line.append(str(output.with_suffix(".png")))
    return line


def show_run_home(report: ComparisonReport, n: int, output: Path) -> None:
    """Print ``run_home_view`` to the terminal.

    ``crop`` is off so a figure path longer than the terminal stays intact.
    """
    Console().print(run_home_view(report, n, output), crop=False, overflow="ignore")
