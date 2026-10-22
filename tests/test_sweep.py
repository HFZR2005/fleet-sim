"""Penetration sweep on a two-home fixture. No network."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import FixturePriceSource
from fleet_sim.experiments import first_crossing, run_penetration_sweep
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2024, 6, 15)


def test_the_first_exceeding_level_is_the_crossing() -> None:
    # 10 kW does not exceed 10 kW. 12 kW does. The 1e-3 kW band ignores dust.
    assert first_crossing([0.0, 0.1, 0.25], [10.0, 10.0, 12.0], 10.0) == 0.25
    assert first_crossing([0.0, 1.0], [10.0, 10.0005], 10.0) is None
    assert first_crossing([0.0, 0.5, 1.0], [9.0, 9.5, 9.9], 10.0) is None


def test_a_two_level_sweep_reports_intervals_and_a_crossing(tmp_path: Path) -> None:
    text = (_ROOT / "scenarios" / "penetration-sweep.toml").read_text(encoding="utf-8")
    battery = text.split("[battery]", 1)[1]
    path = tmp_path / "sweep.toml"
    path.write_text(
        "n_homes = 2\n"
        "penetration = [0.0, 1.0]\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 5\n"
        "replications = 2\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    start, _end = london_day_bounds_utc(_DAY)
    prices = FixturePriceSource(
        PriceSeries(
            region="C",
            day=_DAY,
            timestamps_utc=[
                start + timedelta(minutes=30) * index for index in range(48)
            ],
            price_p_per_kwh=[8.0] * 16 + [20.0] * 16 + [35.0] * 10 + [15.0] * 6,
        )
    )

    report = run_penetration_sweep(
        load_scenario(path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=prices,
    )

    assert [level.penetration for level in report.levels] == [0.0, 1.0]
    assert report.levels[0].metrics[0].metric == "peak_demand_kw"
    assert report.levels[0].peak_minus_no_battery.mean == pytest.approx(0.0, abs=1e-6)
    assert len(report.crossing.per_replication) == 2
    assert all(item != 0.0 for item in report.crossing.per_replication)


def test_read_can_stop_after_one_household() -> None:
    pool = HouseholdDemandPool.read(_FIXTURE, max_households=1)

    assert pool.household_ids() == ["MAC000002"]
