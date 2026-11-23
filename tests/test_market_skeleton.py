"""A [market] scenario runs end to end on stubs, and --release refuses it.

Its prices come from the price-curve fixture cache, so nothing is downloaded.
"""

import json
from pathlib import Path

import pytest

from fleet_sim.cli import main

_ROOT = Path(__file__).parents[1]
_HOUSEHOLDS = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_SCENARIO = _ROOT / "scenarios" / "smoke-market.toml"
_STUBS = (
    "solve_market_day",
    "equilibrium_diagnostics",
    "market_metrics",
    "plot_market_placeholder",
)


def test_the_smoke_market_scenario_runs_and_lists_its_stubs(
    tmp_path: Path, price_cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    code = main(_argv(output, price_cache))

    assert code == 0
    text = capsys.readouterr().out
    assert "STUB" in text
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    for name in _STUBS:
        assert name in text
        assert any(item.startswith(f"{name}:") for item in metrics["stubs"])
    assert [level["national_batteries"] for level in metrics["market_levels"]] == [
        0.0,
        1_000_000.0,
    ]
    assert "STUB" in (output / "market.svg").read_text(encoding="utf-8")


def test_release_fails_while_stubs_remain(
    tmp_path: Path, price_cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    code = main([*_argv(output, price_cache), "--release"])

    assert code == 1
    assert "solve_market_day" in capsys.readouterr().err
    assert not (output / "metrics.json").exists()


def _argv(output: Path, cache: Path) -> list[str]:
    return [
        "run-scenario",
        str(_SCENARIO),
        "--households",
        str(_HOUSEHOLDS),
        "--output",
        str(output),
        "--max-households",
        "2",
        "--cache-dir",
        str(cache),
    ]
