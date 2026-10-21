"""Cheapest-slot rule against the optimiser."""

import random

import pytest

from fleet_sim.models import BatterySpec, ComparisonReport, HomeDay, Schedule
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.optimise import charge_cheapest_slots, compare_cheapest_slots

_ABS = 1e-5


def _example_battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=2.0,
        max_charge_kw=8.0,
        max_discharge_kw=2.0,
        eta_charge=0.5,
        eta_discharge=0.5,
        soc_initial=0.25,
    )


def _assert_feasible(day: HomeDay, schedule: Schedule) -> None:
    battery = day.battery
    n_slots = len(day.demand_kw)
    assert len(schedule.charge_kw) == n_slots
    cost_pence = 0.0
    soc_prev = battery.soc_initial
    for slot in range(n_slots):
        charge = schedule.charge_kw[slot]
        discharge = schedule.discharge_kw[slot]
        imported = schedule.grid_import_kw[slot]
        soc = schedule.soc[slot]
        mode = schedule.charge_mode[slot]
        demand = day.demand_kw[slot]
        assert imported + discharge == pytest.approx(demand + charge, abs=_ABS)
        expected_soc = (
            soc_prev
            + (
                battery.eta_charge * charge * 0.5
                - discharge * 0.5 / battery.eta_discharge
            )
            / battery.capacity_kwh
        )
        assert soc == pytest.approx(expected_soc, abs=_ABS)
        assert 0.0 <= soc <= 1.0
        assert 0.0 <= charge <= battery.max_charge_kw + _ABS
        assert 0.0 <= discharge <= battery.max_discharge_kw + _ABS
        assert imported >= -_ABS
        if mode == 1:
            assert discharge == pytest.approx(0.0, abs=_ABS)
        else:
            assert charge == pytest.approx(0.0, abs=_ABS)
        soc_prev = soc
        cost_pence += day.price_p_per_kwh[slot] * imported * 0.5
    assert schedule.soc[-1] == pytest.approx(battery.soc_initial, abs=_ABS)
    assert schedule.cost_pence == pytest.approx(cost_pence, abs=_ABS)


def test_n_equals_one_on_the_worked_example() -> None:
    # Formulation example, T=2. Prices [2, 10], so N=1 charges slot 0 and
    # discharges slot 1. Demand is 1 kW, so the no-export limit is
    # discharge_kw <= 1, tighter than max_discharge_kw of 2.
    # Later discharge can remove min(2, 1) * 0.5 / 0.5 = 1 kWh from the store.
    # Charge power is then 1 / (0.5 * 0.5) = 4 kW. State of charge goes
    # 0.25 -> 0.75. Slot 1 discharges 1 kW and returns it to 0.25.
    # Bill = 2 * 5 * 0.5 = 5 pence. No battery costs 6. The rule takes the
    # whole optimal saving, so the share is 1.
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    schedule = charge_cheapest_slots(day, 1)
    report = compare_cheapest_slots(day, 1)

    assert isinstance(schedule, Schedule)
    assert schedule.charge_kw == pytest.approx([4.0, 0.0], abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0, 1.0], abs=_ABS)
    assert schedule.grid_import_kw == pytest.approx([5.0, 0.0], abs=_ABS)
    assert schedule.soc == pytest.approx([0.75, 0.25], abs=_ABS)
    assert schedule.charge_mode == [1, 0]
    assert schedule.cost_pence == pytest.approx(5.0, abs=_ABS)
    assert isinstance(report, ComparisonReport)
    assert report.no_battery_cost_pence == pytest.approx(6.0, abs=_ABS)
    assert report.rule_cost_pence == pytest.approx(5.0, abs=_ABS)
    assert report.optimiser_cost_pence == pytest.approx(5.0, abs=_ABS)
    assert report.rule_savings_share == pytest.approx(1.0, abs=_ABS)
    _assert_feasible(day, schedule)


def test_four_slots_charge_the_cheap_one_and_discharge_the_dear_one() -> None:
    # Prices [5, 1, 5, 9], N=1. Slot 1 is cheapest, slot 3 is dearest.
    # Same battery and 1 kW demand as the worked example.
    # Slot 1 can store 1 kWh for slot 3 to remove, so it charges at 4 kW
    # (soc 0.25 -> 0.75). Slot 3 discharges at 1 kW (soc -> 0.25).
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0, 1.0, 1.0],
        price_p_per_kwh=[5.0, 1.0, 5.0, 9.0],
    )

    schedule = charge_cheapest_slots(day, 1)

    assert schedule.charge_kw == pytest.approx([0.0, 4.0, 0.0, 0.0], abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0, 0.0, 0.0, 1.0], abs=_ABS)
    assert schedule.charge_mode == [0, 1, 0, 0]
    _assert_feasible(day, schedule)


def test_overlapping_slots_stay_idle() -> None:
    # N=2 on a 2-slot day puts both slots in both groups. (MODE) leaves them
    # idle, so the rule bill is the no-battery bill of 6 pence. The optimiser
    # still saves 1 pence. Its saving is above the rule's, and the share is 0.
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    report = compare_cheapest_slots(day, 2)

    assert report.no_battery_cost_pence == pytest.approx(6.0, abs=_ABS)
    assert report.rule_cost_pence == pytest.approx(6.0, abs=_ABS)
    assert report.optimiser_cost_pence == pytest.approx(5.0, abs=_ABS)
    assert report.rule_savings_share == pytest.approx(0.0, abs=_ABS)
    _assert_savings(report)


def test_flat_positive_prices_make_the_rule_lose_the_round_trip() -> None:
    day = HomeDay(
        battery=_example_battery(),
        demand_kw=[1.0] * SLOTS_PER_DAY,
        price_p_per_kwh=[10.0] * SLOTS_PER_DAY,
    )

    report = compare_cheapest_slots(day, 1)

    assert report.optimiser_cost_pence == pytest.approx(240.0, abs=_ABS)
    assert report.rule_cost_pence > report.optimiser_cost_pence
    assert report.rule_savings_share == pytest.approx(0.0, abs=_ABS)
    _assert_savings(report)


def test_optimiser_saves_at_least_as_much_as_the_rule() -> None:
    rng = random.Random(0)
    for n in (0, 1, 4, 24):
        for _ in range(3):
            day = HomeDay(
                battery=BatterySpec(
                    capacity_kwh=rng.uniform(1.0, 20.0),
                    max_charge_kw=rng.uniform(0.0, 8.0),
                    max_discharge_kw=rng.uniform(0.0, 8.0),
                    eta_charge=rng.uniform(0.5, 1.0),
                    eta_discharge=rng.uniform(0.5, 1.0),
                    soc_initial=rng.uniform(0.0, 1.0),
                ),
                demand_kw=[rng.uniform(0.0, 4.0) for _ in range(SLOTS_PER_DAY)],
                price_p_per_kwh=[
                    rng.uniform(-10.0, 40.0) for _ in range(SLOTS_PER_DAY)
                ],
            )
            schedule = charge_cheapest_slots(day, n)
            _assert_feasible(day, schedule)
            _assert_savings(compare_cheapest_slots(day, n))


def test_n_cannot_be_negative() -> None:
    day = HomeDay(
        battery=_example_battery(),
        demand_kw=[1.0] * SLOTS_PER_DAY,
        price_p_per_kwh=[10.0] * SLOTS_PER_DAY,
    )
    with pytest.raises(ValueError, match="at least 0"):
        charge_cheapest_slots(day, -1)


def _assert_savings(report: ComparisonReport) -> None:
    optimiser_savings = report.no_battery_cost_pence - report.optimiser_cost_pence
    rule_savings = report.no_battery_cost_pence - report.rule_cost_pence
    assert optimiser_savings + 1e-4 >= rule_savings
