"""`fleet-sim run-fleet` against a saved price fixture. No network."""

import json
from datetime import date
from pathlib import Path

import pytest

from fleet_sim.cli import main
from fleet_sim.models.fleet import FleetDay, SolvedHome
from fleet_sim.models.home import Schedule
from fleet_sim.models.network import NodeFeedback
from fleet_sim.models.results import DayReport, FleetMetrics, FleetRange, Spread
from fleet_sim.render.run_fleet import run_fleet_view

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agile_import_c_2024-06-15.json"
HOME = ROOT / "home.toml"


def test_run_fleet_prints_the_summary_and_saves_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return FIXTURE.read_bytes()

    frames = tmp_path / "frames.json"
    herding = tmp_path / "figures" / "herding"
    peaks = tmp_path / "figures" / "peaks"
    code = main(
        [
            "run-fleet",
            "--homes",
            "2",
            "--start",
            "2024-06-15",
            "--end",
            "2024-06-15",
            "--region",
            "C",
            "--config",
            str(HOME),
            "--frames",
            str(frames),
            "--herding",
            str(herding),
            "--peaks",
            str(peaks),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
        opener=opener,
    )

    assert code == 0
    captured = capsys.readouterr()
    text = captured.out
    assert len(calls) == 1
    assert "finished in" in captured.err
    assert "2 homes, region C, 2024-06-15 to 2024-06-15" in text
    assert "Peak with batteries (kW)" in text
    assert "Peak without batteries (kW)" in text
    assert "Herding day  2024-06-15" in text
    assert str(frames) in text
    assert str(herding.with_suffix(".svg")) in text
    assert str(peaks.with_suffix(".png")) in text
    log = json.loads(frames.read_text(encoding="utf-8"))
    assert log["schema_version"] == 1
    assert len(log["frames"]) == 48
    svg = herding.with_suffix(".svg").read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<?xml")
    assert "Grid import (kW)" in svg
    assert peaks.with_suffix(".png").read_bytes().startswith(b"\x89PNG")


def test_clock_change_range_is_rejected_without_a_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def opener(url: str) -> bytes:
        raise AssertionError(url)

    code = main(
        [
            "run-fleet",
            "--homes",
            "2",
            "--start",
            "2024-10-27",
            "--end",
            "2024-10-27",
            "--region",
            "C",
            "--config",
            str(HOME),
        ],
        opener=opener,
    )

    assert code == 1
    assert "clock-change" in capsys.readouterr().err


def test_run_fleet_view_colours_the_new_peak_and_the_savings() -> None:
    view = run_fleet_view(
        _range(savings=12.5),
        n_homes=2,
        region="C",
        frames_path=Path("frames.json"),
        herding_path=Path("figures/herding"),
        peaks_path=Path("figures/peaks"),
        herding_day=date(2024, 6, 15),
    )
    table = view.renderables[1]
    assert table.rows[0].style == "bold blue"
    assert table.rows[1].style == "dim"
    assert table.rows[4].style == "green"
    assert table.rows[5].style == "green"

    lost = run_fleet_view(
        _range(savings=-3.0),
        n_homes=2,
        region="C",
        frames_path=Path("frames.json"),
        herding_path=Path("figures/herding"),
        peaks_path=Path("figures/peaks"),
        herding_day=date(2024, 6, 15),
    )
    lost_table = lost.renderables[1]
    assert lost_table.rows[4].style == "red"
    assert lost_table.rows[5].style == "red"


def _range(savings: float) -> FleetRange:
    metrics = FleetMetrics(
        peak_demand_kw=4.0,
        peak_slot=0,
        peak_demand_without_battery_kw=3.0,
        peak_slot_without_battery=1,
        peak_to_average_ratio=1.5,
        coincidence_factor=0.8,
        total_savings_pence=savings,
        savings_per_home_pence=savings / 2,
    )
    day = DayReport(
        day=date(2024, 6, 15),
        metrics=metrics,
        solution=FleetDay(
            homes=[
                SolvedHome(
                    home_id="home-1",
                    transformer_id=None,
                    demand_kw=[1.0],
                    schedule=Schedule(
                        charge_kw=[0.0],
                        discharge_kw=[0.0],
                        grid_import_kw=[1.0],
                        soc=[0.5],
                        charge_mode=[0],
                        cost_pence=1.0,
                    ),
                )
            ],
            nodes=[
                NodeFeedback(
                    node_id="root",
                    flow_kw=[1.0],
                    limit_kw=None,
                    overload_kw=[0.0],
                )
            ],
        ),
    )
    return FleetRange(
        days=[day],
        peak_demand_kw=_spread(4.0),
        peak_slot=_spread(0.0),
        peak_demand_without_battery_kw=_spread(3.0),
        peak_slot_without_battery=_spread(1.0),
        peak_to_average_ratio=_spread(1.5),
        coincidence_factor=_spread(0.8),
        total_savings_pence=_spread(savings),
        savings_per_home_pence=_spread(savings / 2),
    )


def _spread(value: float) -> Spread:
    return Spread(median=value, minimum=value, maximum=value)
