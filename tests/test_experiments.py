"""Replication means and t-intervals. The coverage check uses a known normal."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import FixturePriceSource
from fleet_sim.experiments import replication_seed, run_experiment, t_interval
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2024, 6, 15)


def _prices() -> FixturePriceSource:
    start, _end = london_day_bounds_utc(_DAY)
    return FixturePriceSource(
        PriceSeries(
            region="C",
            day=_DAY,
            timestamps_utc=[
                start + timedelta(minutes=30) * index for index in range(48)
            ],
            price_p_per_kwh=[10.0] * 48,
        )
    )


def _scenario(
    directory: Path,
    replications: int,
    mode: str = "diverse",
    penetration: str = "0.0",
):
    text = (_ROOT / "scenarios" / "diverse.toml").read_text(encoding="utf-8")
    battery = text.split("[battery]", 1)[1]
    path = directory / "scenario.toml"
    path.write_text(
        "n_homes = 2\n"
        f"penetration = {penetration}\n"
        f'mode = "{mode}"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 5\n"
        f"replications = {replications}\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    return load_scenario(path)


def test_the_interval_covers_the_true_mean_at_about_the_stated_rate() -> None:
    # 500 independent samples of 30 draws from N(10, 4). A 95% t-interval
    # should cover 10 on about 95% of them. The sampling noise on 500
    # trials is a few percentage points.
    generator = np.random.default_rng(7)
    covers = 0
    trials = 500
    for _ in range(trials):
        samples = generator.normal(10.0, 2.0, size=30)
        interval = t_interval([float(value) for value in samples], level=0.95)
        if interval.low <= 10.0 <= interval.high:
            covers += 1
    rate = covers / trials
    assert 0.91 <= rate <= 0.99


def test_three_known_samples_match_the_hand_interval() -> None:
    # Mean 2, sample variance 1, df 2. t_0.975,2 = 4.302652729911275.
    # Half-width 4.302652729911275 / sqrt(3) = 2.4841377115787966.
    interval = t_interval([1.0, 2.0, 3.0])

    assert interval.mean == pytest.approx(2.0)
    assert interval.low == pytest.approx(2.0 - 2.4841377115787966)
    assert interval.high == pytest.approx(2.0 + 2.4841377115787966)
    assert interval.replications == 3


def test_replication_seeds_depend_on_the_master_and_the_index() -> None:
    assert replication_seed(5, 0) == replication_seed(5, 0)
    assert replication_seed(5, 0) != replication_seed(5, 1)
    assert replication_seed(5, 0) != replication_seed(6, 0)


def test_paired_runs_share_a_replication_seed(tmp_path: Path) -> None:
    # Penetration 0, so with and without batteries are the same fleet and
    # the paired difference is 0. Diverse and identical still differ,
    # because identical copies the mean demand.
    scenario = _scenario(tmp_path, 2)
    report = run_experiment(
        scenario,
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
    )

    assert report.seeds == [replication_seed(5, 0), replication_seed(5, 1)]
    peak = next(item for item in report.battery if item.metric == "peak_demand_kw")
    assert peak.left == "with_batteries"
    assert peak.right == "without_batteries"
    assert peak.interval.mean == pytest.approx(0.0)
    assert peak.interval.low == pytest.approx(0.0)
    assert peak.interval.high == pytest.approx(0.0)
    diversity = next(
        item for item in report.diversity if item.metric == "coincidence_factor"
    )
    assert diversity.left == "diverse"
    assert diversity.right == "identical"


def test_one_replication_cannot_make_an_interval(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path, 1)

    with pytest.raises(ValueError, match="at least 2"):
        run_experiment(
            scenario,
            pool=HouseholdDemandPool.read(_FIXTURE),
            price_source=_prices(),
        )
