"""Optimal one-home schedules. The hand example is the one in the formulation."""

import random

import pytest

from fleet_sim.models import BatterySpec, HomeDay, Schedule
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.optimise import optimise_home

_ABS = 1e-5


def _example_battery(**overrides: float) -> BatterySpec:
    data: dict[str, float] = {
        "capacity_kwh": 2.0,
        "max_charge_kw": 8.0,
        "max_discharge_kw": 2.0,
        "eta_charge": 0.5,
        "eta_discharge": 0.5,
        "soc_initial": 0.25,
    }
    data.update(overrides)
    return BatterySpec.model_validate(data)


def _assert_formulation(day: HomeDay, schedule: Schedule) -> None:
    battery = day.battery
    n_slots = len(day.demand_kw)
    assert len(schedule.charge_kw) == n_slots
    no_battery_pence = 0.0
    cost_pence = 0.0
    soc_prev = battery.soc_initial
    for slot in range(n_slots):
        charge = schedule.charge_kw[slot]
        discharge = schedule.discharge_kw[slot]
        imported = schedule.grid_import_kw[slot]
        soc = schedule.soc[slot]
        mode = schedule.charge_mode[slot]
        demand = day.demand_kw[slot]
        price = day.price_p_per_kwh[slot]
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
        assert charge == pytest.approx(0.0, abs=_ABS) or discharge == pytest.approx(
            0.0, abs=_ABS
        )
        if mode == 1:
            assert discharge == pytest.approx(0.0, abs=_ABS)
        else:
            assert charge == pytest.approx(0.0, abs=_ABS)
        soc_prev = soc
        cost_pence += price * imported * 0.5
        no_battery_pence += price * demand * 0.5
    assert schedule.soc[-1] == pytest.approx(battery.soc_initial, abs=_ABS)
    assert schedule.cost_pence == pytest.approx(cost_pence, abs=_ABS)
    assert schedule.cost_pence <= no_battery_pence + 1e-3


def test_hand_solved_example() -> None:
    # Worked example in docs/formulation.md, horizon T=2, Delta=0.5.
    # C=2, max charge 8 kW, max discharge 2 kW, both efficiencies 0.5,
    # soc_initial=0.25, demand [1, 1] kW, prices [2, 10] p/kWh.
    #
    # (SOC) with those efficiencies is s_{t+1} = s_t + 0.125 c_t - 0.5 d_t.
    # (TERMINAL) s_2 = s_0 forces c0 + c1 = 4 (d0 + d1).
    # bill = g0 + 5 g1 = 6 + 3 d0 - d1 + 4 c1.
    # g1 >= 0 forces d1 <= 1 + c1, so bill - 5 >= 3 d0 + 3 c1 >= 0.
    # Equality only at d0=0, c1=0, d1=1, c0=4.
    # Then g=[5, 0], soc at end of slot=[0.75, 0.25], charge_mode=[1, 0].
    # Bill = 2 * 5 * 0.5 = 5 pence. With no battery the bill is 6 pence.
    #
    # HomeDay only accepts 48 slots. This instance is the same equations on
    # a horizon of 2, which is how the formulation states the example.
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    schedule = optimise_home(day)

    assert schedule.charge_kw == pytest.approx([4.0, 0.0], abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0, 1.0], abs=_ABS)
    assert schedule.grid_import_kw == pytest.approx([5.0, 0.0], abs=_ABS)
    assert schedule.soc == pytest.approx([0.75, 0.25], abs=_ABS)
    assert schedule.charge_mode == [1, 0]
    assert schedule.cost_pence == pytest.approx(5.0, abs=_ABS)
    _assert_formulation(day, schedule)


def test_negative_price_cannot_pay_for_same_slot_cycling() -> None:
    # Illustration in the formulation, separate from the worked example.
    # T=1, load 0, price -8, C=2, efficiencies 0.5, power limits 4.
    # The linear program charges at 4 kW and discharges at 1 kW, imports
    # 3 kW, and earns 12 pence. (MODE) forbids that pair. The only feasible
    # schedule imports nothing and the bill is 0.
    day = HomeDay.model_construct(
        battery=_example_battery(max_charge_kw=4.0, max_discharge_kw=4.0),
        demand_kw=[0.0],
        price_p_per_kwh=[-8.0],
    )

    schedule = optimise_home(day)

    assert schedule.charge_kw == pytest.approx([0.0], abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0], abs=_ABS)
    assert schedule.grid_import_kw == pytest.approx([0.0], abs=_ABS)
    assert schedule.soc == pytest.approx([0.25], abs=_ABS)
    assert schedule.cost_pence == pytest.approx(0.0, abs=_ABS)
    _assert_formulation(day, schedule)


def test_flat_positive_prices_leave_the_battery_idle() -> None:
    day = HomeDay(
        battery=_example_battery(),
        demand_kw=[1.0] * SLOTS_PER_DAY,
        price_p_per_kwh=[10.0] * SLOTS_PER_DAY,
    )

    schedule = optimise_home(day)

    assert schedule.charge_kw == pytest.approx([0.0] * SLOTS_PER_DAY, abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0] * SLOTS_PER_DAY, abs=_ABS)
    assert schedule.grid_import_kw == pytest.approx([1.0] * SLOTS_PER_DAY, abs=_ABS)
    assert schedule.soc == pytest.approx([0.25] * SLOTS_PER_DAY, abs=_ABS)
    assert schedule.cost_pence == pytest.approx(240.0, abs=_ABS)
    _assert_formulation(day, schedule)


def test_flat_zero_prices_are_worth_nothing() -> None:
    day = HomeDay(
        battery=_example_battery(),
        demand_kw=[1.0] * SLOTS_PER_DAY,
        price_p_per_kwh=[0.0] * SLOTS_PER_DAY,
    )

    schedule = optimise_home(day)

    assert schedule.cost_pence == pytest.approx(0.0, abs=_ABS)
    _assert_formulation(day, schedule)


def test_random_days_satisfy_the_formulation() -> None:
    rng = random.Random(0)
    for _ in range(5):
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
            price_p_per_kwh=[rng.uniform(-10.0, 40.0) for _ in range(SLOTS_PER_DAY)],
        )
        _assert_formulation(day, optimise_home(day))
