"""A drawn fleet: products, penetration, and household demand."""

from datetime import date
from pathlib import Path

import pytest

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.fleet.generate import (
    BATTERY_PRODUCTS,
    _owned_indices,
    battery_owner_count,
    generate_fleet,
    with_demand,
)
from fleet_sim.models import BatterySpec

_FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2026, 1, 1)


def _pool() -> HouseholdDemandPool:
    return HouseholdDemandPool.read(_FIXTURE)


def test_the_same_seed_draws_the_same_fleet() -> None:
    pool = _pool()
    first = generate_fleet(pool, _DAY, 2, 11, 1.0)
    second = generate_fleet(pool, _DAY, 2, 11, 1.0)

    assert [home.home_id for home in first.fleet.homes] == ["home-1", "home-2"]
    assert [home.household_id for home in first.fleet.homes] == [
        home.household_id for home in second.fleet.homes
    ]
    assert first.fleet.homes[0].household_id != first.fleet.homes[1].household_id
    for left, right in zip(first.fleet.homes, second.fleet.homes, strict=True):
        assert left.demand_kw == pytest.approx(right.demand_kw)
        assert left.battery == right.battery


def test_demand_is_the_household_day_in_kilowatts() -> None:
    # The pool stores kWh per half hour. Average kW is that energy / 0.5.
    pool = _pool()
    generated = generate_fleet(pool, _DAY, 2, 11, 1.0)

    for home in generated.fleet.homes:
        assert home.household_id is not None
        series = pool.load(home.household_id, _DAY).series
        assert home.demand_kw == pytest.approx(
            [energy / 0.5 for energy in series.demand_kwh]
        )


def test_penetration_count_rounds_half_away_from_zero() -> None:
    # 50% of one home is 0.5, which rounds to 1. Python's round would give 0.
    # 50% of three homes is 1.5, which rounds to 2. 25% of eight is 2.
    assert battery_owner_count(0.5, 1) == 1
    assert battery_owner_count(0.5, 3) == 2
    assert battery_owner_count(0.25, 8) == 2
    assert battery_owner_count(0.5, 8) == 4
    assert battery_owner_count(0, 8) == 0
    assert battery_owner_count(1, 8) == 8


def test_lower_penetration_owns_a_subset_of_the_draws() -> None:
    # Sorted ascending: index 7 (0.05), 1 (0.10), 3 (0.20), 5 (0.30),
    # then 2, 6, 4, 0. The first 2 of those are the 25% owners, and they
    # are among the first 4, which are the 50% owners.
    draws = [0.9, 0.1, 0.4, 0.2, 0.8, 0.3, 0.7, 0.05]

    low = set(_owned_indices(draws, 0.25))
    high = set(_owned_indices(draws, 0.5))

    assert low == {7, 1}
    assert high == {7, 1, 3, 5}
    assert low < high


def test_a_lower_penetration_fleet_is_a_subset_and_keeps_its_products() -> None:
    pool = _pool()
    low = generate_fleet(pool, _DAY, 2, 11, 0.25)
    high = generate_fleet(pool, _DAY, 2, 11, 1.0)
    low_owners = {home.home_id for home in low.fleet.homes if home.battery is not None}
    high_owners = {
        home.home_id for home in high.fleet.homes if home.battery is not None
    }

    assert len(low_owners) == battery_owner_count(0.25, 2)
    assert len(high_owners) == 2
    assert low_owners < high_owners
    for left, right in zip(low.fleet.homes, high.fleet.homes, strict=True):
        assert left.household_id == right.household_id
        assert left.demand_kw == pytest.approx(right.demand_kw)
        if left.battery is not None:
            assert left.battery == right.battery


def test_drawn_batteries_are_catalogue_products_inside_the_efficiency_band() -> None:
    pool = _pool()
    products = {product.capacity_kwh: product.power_kw for product in BATTERY_PRODUCTS}
    generated = generate_fleet(pool, _DAY, 2, 11, 1.0)

    for home in generated.fleet.homes:
        battery = home.battery
        assert isinstance(battery, BatterySpec)
        assert battery.max_charge_kw == battery.max_discharge_kw
        assert battery.max_charge_kw in products[battery.capacity_kwh]
        assert 0.92 <= battery.eta_charge <= 0.97
        assert 0.92 <= battery.eta_discharge <= 0.97
        assert battery.soc_initial == 0.5


def test_identical_mode_copies_the_mean_home() -> None:
    pool = _pool()
    diverse = generate_fleet(pool, _DAY, 2, 11, 1.0)
    identical = generate_fleet(pool, _DAY, 2, 11, 1.0, mode="identical")
    left, right = diverse.fleet.homes
    assert left.battery is not None and right.battery is not None
    mean_demand = [
        (a + b) / 2 for a, b in zip(left.demand_kw, right.demand_kw, strict=True)
    ]
    mean_capacity = (left.battery.capacity_kwh + right.battery.capacity_kwh) / 2

    assert [home.home_id for home in identical.fleet.homes] == ["home-1", "home-2"]
    for home in identical.fleet.homes:
        assert home.demand_kw == pytest.approx(mean_demand)
        assert home.battery is not None
        assert home.battery.capacity_kwh == pytest.approx(mean_capacity)
        assert home.household_id is None
    assert identical.fleet.homes[0].battery == identical.fleet.homes[1].battery


def test_reloading_a_day_keeps_the_battery_and_changes_the_demand() -> None:
    pool = _pool()
    generated = generate_fleet(pool, date(2026, 1, 1), 2, 11, 1.0)
    weekend = with_demand(generated.fleet, pool, date(2026, 1, 3))

    for before, after in zip(generated.fleet.homes, weekend.fleet.homes, strict=True):
        assert after.home_id == before.home_id
        assert after.household_id == before.household_id
        assert after.battery == before.battery
        assert after.household_id is not None
        series = pool.load(after.household_id, date(2026, 1, 3)).series
        assert after.demand_kw == pytest.approx(
            [energy / 0.5 for energy in series.demand_kwh]
        )
    # MAC000002 has a winter weekend in the fixture, so that home's Saturday
    # is not its Thursday. MAC000003 has only a weekday, so its Saturday
    # falls back to the same trial day.
    before_mac = next(
        home for home in generated.fleet.homes if home.household_id == "MAC000002"
    )
    after_mac = next(
        home for home in weekend.fleet.homes if home.household_id == "MAC000002"
    )
    assert after_mac.demand_kw != before_mac.demand_kw


def test_a_fleet_larger_than_the_household_pool_is_rejected() -> None:
    with pytest.raises(ValueError, match="the pool has 2"):
        generate_fleet(_pool(), _DAY, 3, 1, 1.0)


def test_penetration_must_be_a_fraction() -> None:
    pool = _pool()

    with pytest.raises(ValueError, match="in \\[0, 1\\]"):
        generate_fleet(pool, _DAY, 1, 1, 1.5)
    with pytest.raises(TypeError, match="penetration must be a float"):
        generate_fleet(pool, _DAY, 1, 1, True)
