"""A [market] scenario runs end to end with no stubs, and --release accepts it.

Its prices come from the price-curve fixture cache, so nothing is downloaded.
"""

import json
from pathlib import Path

import pytest

from fleet_sim.cli import main

_ROOT = Path(__file__).parents[1]
_HOUSEHOLDS = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_SCENARIO = _ROOT / "scenarios" / "smoke-market.toml"
_FIGURES = ("added_load", "saving_by_model", "overload_by_penetration")


def test_the_smoke_market_scenario_runs_in_release_with_no_stubs(
    tmp_path: Path, price_cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # smoke-market.toml: M = 0 and 1 million, ρ = 0 and 0.8, one local
    # penetration, and one robustness model at the headline point. That is
    # (2 + 2) points at ρ = 0 and 2 at ρ = 0.8, × 2 replications × 1 day.
    output = tmp_path / "out"
    code = main(_argv(output, price_cache))

    assert code == 0
    text = capsys.readouterr().out
    assert "STUB" not in text
    assert "12 fleet-day solves" in text
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["stubs"] == []
    market = metrics["market"]
    assert market["solve_count"] == 12
    assert market["wall_time_s"] > 0
    points = [
        (level["price_model"], level["rho"], level["national_batteries"])
        for level in market["levels"]
    ]
    assert points == [
        ("fuel_adjusted/exponential", 0.0, 0.0),
        ("fuel_adjusted/exponential", 0.0, 1_000_000.0),
        ("fuel_adjusted/cubic", 0.0, 0.0),
        ("fuel_adjusted/cubic", 0.0, 1_000_000.0),
        ("fuel_adjusted/exponential", 0.8, 0.0),
        ("fuel_adjusted/exponential", 0.8, 1_000_000.0),
    ]
    # M = 0 paired with itself is zero in every replication.
    baseline = market["levels"][0]
    assert all(
        change["interval"]["mean"] == 0.0 for change in baseline["market_change"]
    )
    diagnostics = json.loads((output / "diagnostics.json").read_text("utf-8"))
    assert len(diagnostics) == 12
    for stem in _FIGURES:
        assert (output / f"{stem}.svg").exists()
        assert (output / f"{stem}.png").exists()


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
        "--release",
    ]
