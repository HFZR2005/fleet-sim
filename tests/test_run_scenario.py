"""`fleet-sim run-scenario` against a saved price fixture. No network."""

import json
from pathlib import Path

import pytest

from fleet_sim.cli import main

_ROOT = Path(__file__).parents[1]
_PRICES = _ROOT / "tests" / "fixtures" / "agile_import_c_2024-06-15.json"
_HOUSEHOLDS = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = "2024-06-15"


def test_run_scenario_prints_intervals_and_writes_the_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _write_scenario(tmp_path, "0.0", replications=2)
    output = tmp_path / "out"

    code = main(
        _argv(scenario, output, tmp_path / "cache"),
        opener=lambda _url: _PRICES.read_bytes(),
    )

    assert code == 0
    captured = capsys.readouterr()
    text = captured.out
    assert "finished in" in captured.err
    assert f"2 homes, region C, {_DAY} to {_DAY}, 2 replications, diverse" in text
    assert "Peak demand (kW)" in text
    assert "Diverse minus identical" in text
    assert "With batteries minus without" in text
    frames = json.loads((output / "frames.json").read_text(encoding="utf-8"))
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert frames["schema_version"] == 1
    assert len(frames["frames"]) == 48
    assert metadata["seed"] == 4
    assert metadata["scenario"]["n_homes"] == 2
    diversity = (output / "diversity.svg").read_text(encoding="utf-8")
    assert diversity.lstrip().startswith("<?xml")
    assert "Grid import (kW)" in diversity
    assert "Mean peak difference" in diversity
    assert (output / "penetration.png").read_bytes().startswith(b"\x89PNG")


def test_a_penetration_list_prints_each_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _write_scenario(tmp_path, "[0.0, 1.0]", replications=2)

    code = main(
        _argv(scenario, tmp_path / "out", tmp_path / "cache"),
        opener=lambda _url: _PRICES.read_bytes(),
    )

    assert code == 0
    text = capsys.readouterr().out
    assert "Penetration" in text
    assert "0%" in text
    assert "100%" in text


def test_one_replication_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _write_scenario(tmp_path, "0.0", replications=1)

    code = main(
        _argv(scenario, tmp_path / "out", tmp_path / "cache"),
        opener=lambda _url: _PRICES.read_bytes(),
    )

    assert code == 1
    assert "at least 2" in capsys.readouterr().err


def test_a_clock_change_is_rejected_without_a_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _write_scenario(tmp_path, "0.0", replications=2, day="2024-10-27")

    def opener(url: str) -> bytes:
        raise AssertionError(url)

    code = main(_argv(scenario, tmp_path / "out", tmp_path / "cache"), opener=opener)

    assert code == 1
    assert "clock-change" in capsys.readouterr().err


def _argv(scenario: Path, output: Path, cache: Path) -> list[str]:
    return [
        "run-scenario",
        str(scenario),
        "--households",
        str(_HOUSEHOLDS),
        "--output",
        str(output),
        "--max-households",
        "2",
        "--cache-dir",
        str(cache),
    ]


def _write_scenario(
    tmp_path: Path,
    penetration: str,
    *,
    replications: int,
    day: str = _DAY,
) -> Path:
    battery = (
        (_ROOT / "scenarios" / "diverse.toml")
        .read_text(encoding="utf-8")
        .split("[battery]", 1)[1]
    )
    path = tmp_path / "scenario.toml"
    path.write_text(
        "n_homes = 2\n"
        f"penetration = {penetration}\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {day}\n"
        f"end = {day}\n"
        "seed = 4\n"
        f"replications = {replications}\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    return path
