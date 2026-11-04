"""Network penetration sweep on a two-home fixture.

Uses tiny transformer ratings so base demand alone already overloads,
and the sweep shows how overload metrics change with penetration.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from fleet_sim.commands.network import _overload_crossing, run_network_scenario
from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import FixturePriceSource
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2024, 6, 15)
_METRICS = (
    "transformers_overloaded_share",
    "mean_peak_utilisation",
    "worst_peak_utilisation",
    "total_overload_energy_kwh",
    "hidden_overload_share",
)


def _prices() -> FixturePriceSource:
    start, _end = london_day_bounds_utc(_DAY)
    return FixturePriceSource(
        PriceSeries(
            region="C",
            day=_DAY,
            timestamps_utc=[
                start + timedelta(minutes=30) * index for index in range(48)
            ],
            price_p_per_kwh=[8.0] * 16 + [20.0] * 16 + [35.0] * 10 + [15.0] * 6,
        )
    )


def _sweep_scenario(tmp_path: Path) -> Path:
    """Two-home, two-level network sweep with tiny ratings to force overloads."""
    text = (_ROOT / "scenarios" / "smoke-network.toml").read_text(encoding="utf-8")
    battery = text.split("[battery]", 1)[1]
    path = tmp_path / "net-sweep.toml"
    path.write_text(
        "n_homes = 2\n"
        "penetration = [0.0, 1.0]\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 5\n"
        "replications = 2\n"
        "\n"
        "[network]\n"
        "n_transformers = 2\n"
        "rho = 0.0\n"
        "admd_kw = 0.001\n"
        "headroom = 1.0\n"
        "power_factor = 1.0\n"
        "ratings_kva = [0.001]\n"
        "\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    return path


def test_a_two_level_network_sweep_reports_intervals_and_a_crossing(
    tmp_path: Path,
) -> None:
    path = _sweep_scenario(tmp_path)
    output = tmp_path / "out"
    result = run_network_scenario(
        load_scenario(path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
        output_dir=output,
    )

    assert [level.penetration for level in result.network_levels] == [0.0, 1.0]
    for level in result.network_levels:
        assert len(level.metrics) == len(_METRICS)
        assert len(level.without_batteries) == len(_METRICS)
        assert len(level.battery_effect) == len(_METRICS)
        for m in level.metrics:
            assert m.interval.replications == 2

    assert result.overload_crossing is not None
    assert result.overload_crossing.metric == "transformers_overloaded_share"
    assert len(result.overload_crossing.per_replication) == 2


def test_without_battery_metrics_are_identical_across_penetrations(
    tmp_path: Path,
) -> None:
    """The without-batteries pass runs at penetration=0 regardless of the
    target penetration, so the without-battery metrics should be the same
    at every level within a replication.

    # Hand-worked reasoning: at penetration=0, no home has a battery.
    # The fleet is the same homes with the same demand on the same topology.
    # Therefore the overload metrics are identical at every level.
    """
    path = _sweep_scenario(tmp_path)
    output = tmp_path / "out"
    result = run_network_scenario(
        load_scenario(path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
        output_dir=output,
    )

    assert len(result.network_levels) == 2
    for m0, m1 in zip(
        result.network_levels[0].without_batteries,
        result.network_levels[1].without_batteries,
        strict=True,
    ):
        assert m0.interval.mean == pytest.approx(m1.interval.mean)


def test_paired_difference_is_with_minus_without(tmp_path: Path) -> None:
    """The battery_effect is the paired difference: with minus without.

    # At penetration=0 the with-battery and without-battery passes are
    # identical (no homes own batteries), so the paired difference is zero.
    """
    path = _sweep_scenario(tmp_path)
    output = tmp_path / "out"
    result = run_network_scenario(
        load_scenario(path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
        output_dir=output,
    )

    level_0 = result.network_levels[0]
    for diff in level_0.battery_effect:
        assert diff.interval.mean == pytest.approx(0.0, abs=1e-6)


# --- Unit tests for crossing detection ---
#
# Hand-worked case: 3 penetrations, 2 replications.
#
#   Replication 0: overloaded share = [0.0, 0.5, 1.0] → crosses at 0.5
#   Replication 1: overloaded share = [0.0, 0.0, 0.8] → crosses at 1.0
#
#   lowest = 0.5, highest = 1.0
#   CI at 0.5: mean = 0.25, and with 2 samples the CI is wide — need to check
#   CI at 1.0: mean = 0.9, both above zero → interval_above_zero_from = 1.0


def test_overload_crossing_detection() -> None:
    penetrations = [0.0, 0.5, 1.0]
    samples: dict[float, dict[str, dict[str, list[float]]]] = {
        0.0: {
            "with": {"transformers_overloaded_share": [0.0, 0.0]},
            "without": {"transformers_overloaded_share": [0.0, 0.0]},
        },
        0.5: {
            "with": {"transformers_overloaded_share": [0.5, 0.0]},
            "without": {"transformers_overloaded_share": [0.0, 0.0]},
        },
        1.0: {
            "with": {"transformers_overloaded_share": [1.0, 0.8]},
            "without": {"transformers_overloaded_share": [0.0, 0.0]},
        },
    }

    crossing = _overload_crossing(penetrations, samples)

    assert crossing is not None
    assert crossing.metric == "transformers_overloaded_share"
    assert crossing.per_replication == [0.5, 1.0]
    assert crossing.lowest == 0.5
    assert crossing.highest == 1.0


def test_overload_crossing_none_when_no_overload() -> None:
    penetrations = [0.0, 1.0]
    samples: dict[float, dict[str, dict[str, list[float]]]] = {
        0.0: {
            "with": {"transformers_overloaded_share": [0.0, 0.0]},
            "without": {"transformers_overloaded_share": [0.0, 0.0]},
        },
        1.0: {
            "with": {"transformers_overloaded_share": [0.0, 0.0]},
            "without": {"transformers_overloaded_share": [0.0, 0.0]},
        },
    }

    crossing = _overload_crossing(penetrations, samples)

    assert crossing is not None
    assert crossing.per_replication == [None, None]
    assert crossing.lowest is None
    assert crossing.highest is None


def test_single_penetration_returns_no_crossing(tmp_path: Path) -> None:
    """A single penetration level does not produce a crossing."""
    text = (_ROOT / "scenarios" / "smoke-network.toml").read_text(encoding="utf-8")
    battery = text.split("[battery]", 1)[1]
    path = tmp_path / "single.toml"
    path.write_text(
        "n_homes = 2\n"
        "penetration = 0.0\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 5\n"
        "replications = 2\n"
        "\n"
        "[network]\n"
        "n_transformers = 2\n"
        "rho = 0.0\n"
        "admd_kw = 0.001\n"
        "headroom = 1.0\n"
        "power_factor = 1.0\n"
        "ratings_kva = [0.001]\n"
        "\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    result = run_network_scenario(
        load_scenario(path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
        output_dir=output,
    )

    assert result.overload_crossing is None
    assert len(result.network_levels) == 1
