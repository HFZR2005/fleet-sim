"""Solve a small fleet and add its imports at the root node."""

from datetime import date, timedelta

import pytest

from fleet_sim.fleet import (
    Fleet,
    Home,
    HomeProfile,
    Network,
    identical_homes,
    solve_fleet,
)
from fleet_sim.models import BatterySpec, PriceSeries
from fleet_sim.models.prices import london_day_bounds_utc

DAY = date(2024, 6, 15)


def _battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=2.0,
        max_charge_kw=8.0,
        max_discharge_kw=2.0,
        eta_charge=0.5,
        eta_discharge=0.5,
        soc_initial=0.25,
    )


def _prices(values: list[float]) -> PriceSeries:
    start, _end = london_day_bounds_utc(DAY)
    return PriceSeries(
        region="C",
        day=DAY,
        timestamps_utc=[start + timedelta(minutes=30) * index for index in range(48)],
        price_p_per_kwh=values,
    )


def test_root_flow_is_the_sum_of_home_imports_and_never_overloads() -> None:
    # Flat positive prices and a lossy battery: each home leaves the battery
    # idle, so its import equals its demand. Home demands are 1 kW and 3 kW,
    # so the root flow is 4 kW in every slot and the overload is 0.
    template = Home(
        home_id="home",
        region="C",
        battery=_battery(),
        demand_kw=[1.0] * 48,
    )
    fleet = identical_homes(template, 2)
    fleet = Fleet(
        homes=[
            fleet.homes[0],
            fleet.homes[1].model_copy(update={"demand_kw": [3.0] * 48}),
        ]
    )

    day = solve_fleet(fleet, _prices([10.0] * 48), None)
    root = day.nodes[0]

    assert root.node_id == "root"
    assert root.limit_kw is None
    assert root.flow_kw == pytest.approx([4.0] * 48)
    assert root.overload_kw == [0.0] * 48
    assert day.homes[0].schedule.grid_import_kw == pytest.approx([1.0] * 48)
    assert day.homes[1].schedule.grid_import_kw == pytest.approx([3.0] * 48)


def test_network_adds_profiles_slot_by_slot() -> None:
    feedback = Network().evaluate(
        [
            HomeProfile(home_id="a", grid_import_kw=[1.0, 4.0]),
            HomeProfile(home_id="b", grid_import_kw=[2.0, 0.5]),
        ]
    )

    assert len(feedback) == 1
    assert feedback[0].flow_kw == pytest.approx([3.0, 4.5])
    assert feedback[0].overload_kw == [0.0, 0.0]


def test_signals_must_line_up_with_the_homes() -> None:
    template = Home(
        home_id="home",
        region="C",
        battery=_battery(),
        demand_kw=[1.0] * 48,
    )
    fleet = identical_homes(template, 1)

    with pytest.raises(ValueError, match="one adjustment per home"):
        solve_fleet(fleet, _prices([10.0] * 48), [])
