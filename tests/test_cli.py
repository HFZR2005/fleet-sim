"""`fleet-sim run-home` against a saved price fixture. No network."""

import re
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from rich.table import Table
from rich.text import Text

from fleet_sim.cli import main
from fleet_sim.commands import load_run_home_config
from fleet_sim.models.comparison import ComparisonReport
from fleet_sim.render import run_home_view

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agile_import_c_2024-06-15.json"
HOME = ROOT / "home.toml"


def test_shipped_home_config_has_sensible_defaults() -> None:
    config = load_run_home_config(HOME)

    assert config.n == 8
    assert config.battery.capacity_kwh == 10.0
    assert config.battery.max_charge_kw == 5.0
    assert config.battery.max_discharge_kw == 5.0
    assert config.battery.eta_charge == 0.95
    assert config.battery.eta_discharge == 0.95
    assert config.battery.soc_initial == 0.5
    assert config.demand_kw == [0.3] * 16 + [0.6] * 16 + [1.5] * 10 + [0.6] * 6


def test_run_home_prints_the_report_and_saves_the_figure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return FIXTURE.read_bytes()

    output = tmp_path / "day"
    code = main(
        [
            "run-home",
            "--date",
            "2024-06-15",
            "--region",
            "C",
            "--config",
            str(HOME),
            "--output",
            str(output),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
        opener=opener,
    )

    assert code == 0
    assert len(calls) == 1
    text = capsys.readouterr().out
    no_battery = _pence(text, "No battery")
    rule = _pence(text, "Rule (n=8)")
    optimiser = _pence(text, "Optimiser")
    assert optimiser <= no_battery + 0.05
    assert optimiser <= rule + 0.05
    assert "Rule share of optimal savings" in text
    assert str(output.with_suffix(".svg")) in text
    assert str(output.with_suffix(".png")) in text
    svg = output.with_suffix(".svg").read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<?xml")
    assert "Price (p/kWh)" in svg
    assert output.with_suffix(".png").read_bytes().startswith(b"\x89PNG")


def test_clock_change_day_is_rejected_without_a_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def opener(url: str) -> bytes:
        raise AssertionError(url)

    code = main(
        ["run-home", "--date", "2026-10-25", "--region", "C", "--config", str(HOME)],
        opener=opener,
    )

    assert code == 1
    assert "clock-change" in capsys.readouterr().err


def test_missing_config_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "run-home",
            "--date",
            "2024-06-15",
            "--region",
            "C",
            "--config",
            str(tmp_path / "missing.toml"),
        ]
    )

    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_run_home_view_lists_bills_share_and_figure_paths() -> None:
    report = ComparisonReport(
        no_battery_cost_pence=6,
        rule_cost_pence=5,
        optimiser_cost_pence=5,
        rule_savings_share=1,
    )
    buffer = StringIO()
    Console(file=buffer, width=80, no_color=True).print(
        run_home_view(report, 1, Path("figures/day"))
    )
    text = buffer.getvalue()

    assert _pence(text, "No battery") == 6
    assert _pence(text, "Rule (n=1)") == 5
    assert _pence(text, "Optimiser") == 5
    assert "Rule share of optimal savings" in text
    assert "1.000" in text
    assert "figures/day.svg" in text
    assert "figures/day.png" in text


def test_run_home_view_colours_the_strategies_and_the_share() -> None:
    kept = _view(
        ComparisonReport(
            no_battery_cost_pence=6,
            rule_cost_pence=5,
            optimiser_cost_pence=5,
            rule_savings_share=1,
        )
    )
    assert [row.style for row in kept.rows] == ["dim", "cyan", "bold blue"]
    assert _span_style(kept.share, -1) == "green"

    missed = _view(
        ComparisonReport(
            no_battery_cost_pence=6,
            rule_cost_pence=6,
            optimiser_cost_pence=5,
            rule_savings_share=0,
        )
    )
    assert _span_style(missed.share, -1) == "dim"

    lost = _view(
        ComparisonReport(
            no_battery_cost_pence=6,
            rule_cost_pence=7,
            optimiser_cost_pence=5,
            rule_savings_share=-1,
        )
    )
    assert _span_style(lost.share, -1) == "red"
    assert _span_style(lost.figure, 0) == "dim"


def test_date_must_be_iso(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run-home", "--date", "20-10-2026", "--region", "C"])

    assert code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


class _View:
    def __init__(self, table: Table, share: Text, figure: Text) -> None:
        self.rows = table.rows
        self.share = share
        self.figure = figure


def _view(report: ComparisonReport) -> _View:
    table, share, figure = run_home_view(report, 1, Path("figures/day")).renderables
    assert isinstance(table, Table)
    assert isinstance(share, Text)
    assert isinstance(figure, Text)
    return _View(table, share, figure)


def _span_style(text: Text, index: int) -> str:
    style = text.spans[index].style
    assert style is not None
    return str(style)


def _pence(text: str, label: str) -> float:
    match = re.search(
        rf"{re.escape(label)}[^\n]*?([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    assert match is not None
    return float(match.group(1))
