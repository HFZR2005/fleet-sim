"""A scenario file is enough to repeat a run. Tests never touch the network."""

from datetime import date, timedelta
from importlib.metadata import version
from pathlib import Path

import pytest

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import FixturePriceSource
from fleet_sim.fleet.frames import read_frames
from fleet_sim.fleet.generate import generate_fleet
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.models.scenario import BatteryDistribution, BatteryProductSpec
from fleet_sim.scenario import git_commit, load_scenario, read_metadata, run_scenario

_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2024, 6, 15)


def _prices() -> FixturePriceSource:
    start, _end = london_day_bounds_utc(_DAY)
    series = PriceSeries(
        region="C",
        day=_DAY,
        timestamps_utc=[start + timedelta(minutes=30) * index for index in range(48)],
        price_p_per_kwh=[10.0] * 48,
    )
    return FixturePriceSource(series)


def _scenario_text() -> str:
    battery = (_ROOT / "scenarios" / "diverse.toml").read_text(encoding="utf-8")
    battery = battery.split("[battery]", 1)[1]
    return (
        "n_homes = 2\n"
        "penetration = 0.0\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 3\n"
        "replications = 1\n"
        "[battery]"
        f"{battery}"
    )


def test_example_scenarios_load() -> None:
    identical = load_scenario(_ROOT / "scenarios" / "identical.toml")
    diverse = load_scenario(_ROOT / "scenarios" / "diverse.toml")
    sweep = load_scenario(_ROOT / "scenarios" / "penetration-sweep.toml")

    assert identical.mode == "identical"
    assert identical.penetration == 1.0
    assert diverse.mode == "diverse"
    assert diverse.n_homes == 8
    assert diverse.seed == 1
    assert sweep.penetration_levels() == [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]


def test_a_scenario_rejects_a_bad_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        _scenario_text().replace("penetration = 0.0", "penetration = 1.5"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid"):
        load_scenario(path)

    backwards = _scenario_text().replace(
        f"end = {_DAY.isoformat()}", "end = 2024-06-14"
    )
    path.write_text(backwards, encoding="utf-8")
    with pytest.raises(ValueError, match="before start"):
        load_scenario(path)


def test_the_drawn_battery_comes_from_the_scenario_distribution() -> None:
    scenario = load_scenario(_ROOT / "scenarios" / "diverse.toml")
    only_small = scenario.battery.model_copy(
        update={
            "products": [
                BatteryProductSpec(capacity_kwh=5.0, power_kw=[3.6], weight=1.0)
            ]
        }
    )
    assert isinstance(only_small, BatteryDistribution)
    fleet = generate_fleet(
        HouseholdDemandPool.read(_FIXTURE),
        _DAY,
        2,
        3,
        1.0,
        distribution=only_small,
    )

    for home in fleet.fleet.homes:
        assert home.battery is not None
        assert home.battery.capacity_kwh == 5.0
        assert home.battery.max_charge_kw == 3.6
        assert home.battery.max_discharge_kw == 3.6


def test_rerunning_a_saved_scenario_reproduces_its_metrics(tmp_path: Path) -> None:
    path = tmp_path / "scenario.toml"
    path.write_text(_scenario_text(), encoding="utf-8")
    scenario = load_scenario(path)
    pool = HouseholdDemandPool.read(_FIXTURE)
    prices = _prices()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = run_scenario(scenario, pool=pool, price_source=prices, output_dir=first_dir)
    saved = read_metadata(first_dir / "metadata.json")
    second = run_scenario(
        saved.scenario, pool=pool, price_source=prices, output_dir=second_dir
    )
    frames = read_frames(first_dir / "frames.json")

    assert saved.seed == scenario.seed
    assert saved.package_version == version("fleet-sim")
    assert saved.git_commit == git_commit()
    assert frames.metadata == saved
    assert [day.metrics for day in second.days] == [day.metrics for day in first.days]


def test_a_penetration_sweep_is_not_run_here(tmp_path: Path) -> None:
    sweep = load_scenario(_ROOT / "scenarios" / "penetration-sweep.toml")

    with pytest.raises(ValueError, match="later step"):
        run_scenario(
            sweep,
            pool=HouseholdDemandPool.read(_FIXTURE),
            price_source=_prices(),
            output_dir=tmp_path / "sweep",
        )
