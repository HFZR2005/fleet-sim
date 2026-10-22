"""Optimal one-home schedules. The hand example is the one in the formulation."""

import json
import random
from datetime import date
from pathlib import Path

import pytest

from fleet_sim.data import AgilePriceSource
from fleet_sim.models import BatterySpec, HomeDay, Schedule
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.optimise import optimise_home
from fleet_sim.optimise.home import _solve

_FIXTURES = Path(__file__).parent / "fixtures"

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
    # E=2, max charge 8 kW, max discharge 2 kW, both efficiencies 0.5,
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


def test_realistic_battery_hand_example() -> None:
    # Realistic worked example in docs/formulation.md. T=2, Delta=0.5.
    # E=10, both power limits 5 kW, both efficiencies 0.95, soc_initial=0.5,
    # demand [1, 1] kW, prices [10, 20] p/kWh.
    #
    # (TERMINAL) forces d0 + d1 = 0.9025 (c0 + c1).
    # bill = 15 + (39/80) c0 + (439/80) c1 - 5 d1.
    # The minimum is on g1 = 0: c1 = 0, c0 = 400/361, d1 = 1, d0 = 0.
    # g0 = 761/361, bill = 3805/361 pence. The 5 kW limits do not bind.
    # With no battery the bill is 15 pence.
    day = HomeDay.model_construct(
        battery=_example_battery(
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            eta_charge=0.95,
            eta_discharge=0.95,
            soc_initial=0.5,
        ),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[10.0, 20.0],
    )

    schedule = optimise_home(day)

    assert schedule.charge_kw == pytest.approx([400 / 361, 0.0], abs=_ABS)
    assert schedule.discharge_kw == pytest.approx([0.0, 1.0], abs=_ABS)
    assert schedule.grid_import_kw == pytest.approx([761 / 361, 0.0], abs=_ABS)
    assert schedule.soc == pytest.approx([0.5 + 19 / 361, 0.5], abs=_ABS)
    assert schedule.charge_mode == [1, 0]
    assert schedule.cost_pence == pytest.approx(3805 / 361, abs=_ABS)
    _assert_formulation(day, schedule)


def test_negative_price_cannot_pay_for_same_slot_cycling() -> None:
    # Illustration in the formulation, separate from the worked example.
    # T=1, load 0, price -8, E=2, efficiencies 0.5, power limits 4.
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


def test_zero_price_adjustment_matches_the_unadjusted_schedule() -> None:
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    assert optimise_home(day, [0.0, 0.0]) == optimise_home(day)


def test_a_large_adjustment_moves_charging_off_the_cheap_slot() -> None:
    # Same battery and loads as the worked example. Prices are [2, 10], so
    # with no adjustment the home charges at 4 kW in slot 0.
    #
    # Add 100 p/kWh to slot 0. The objective then sees [102, 10]. Charging
    # belongs in slot 1 and discharging in slot 0.
    # (SOC) and (TERMINAL) still give c0 + c1 = 4 (d0 + d1).
    # With c0 = 0 and d1 = 0, c1 = 4 d0.
    # Slot 0 starts at soc 0.25 and can discharge 0.5 kW before soc hits 0
    # (0.25 * 2 kWh / 0.5 h). Then c1 = 2, g0 = 1 - 0.5 = 0.5, g1 = 1 + 2 = 3,
    # and soc ends [0, 0.25]. The tariff bill is 2*0.5*0.5 + 10*3*0.5 = 15.5.
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    unadjusted = optimise_home(day)
    shifted = optimise_home(day, [100.0, 0.0])

    assert unadjusted.charge_kw == pytest.approx([4.0, 0.0], abs=_ABS)
    assert shifted.charge_kw == pytest.approx([0.0, 2.0], abs=_ABS)
    assert shifted.discharge_kw == pytest.approx([0.5, 0.0], abs=_ABS)
    assert shifted.grid_import_kw == pytest.approx([0.5, 3.0], abs=_ABS)
    assert shifted.soc == pytest.approx([0.0, 0.25], abs=_ABS)
    assert shifted.charge_mode == [0, 1]
    assert shifted.cost_pence == pytest.approx(15.5, abs=_ABS)


def test_price_adjustment_must_cover_the_horizon() -> None:
    day = HomeDay.model_construct(
        battery=_example_battery(),
        demand_kw=[1.0, 1.0],
        price_p_per_kwh=[2.0, 10.0],
    )

    with pytest.raises(ValueError, match="one value per slot"):
        optimise_home(day, [100.0])


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


def test_positive_price_fixture_days_stay_with_the_linear_program() -> None:
    # Flat positive prices from tests/fixtures/fleet_prices_three_days.json.
    # A lossy battery does not cycle when every effective price is positive,
    # so the linear program and the mixed-integer program bill the same day
    # and the linear program has no slot with both powers positive.
    raw = json.loads(
        (_FIXTURES / "fleet_prices_three_days.json").read_text(encoding="utf-8")
    )
    zeros = [0.0] * SLOTS_PER_DAY
    for item in raw["days"]:
        prices = item["price_p_per_kwh"]
        assert all(price > 0.0 for price in prices)
        day = HomeDay(
            battery=_example_battery(
                capacity_kwh=10.0,
                max_charge_kw=5.0,
                max_discharge_kw=5.0,
                eta_charge=0.95,
                eta_discharge=0.95,
                soc_initial=0.5,
            ),
            demand_kw=[0.6] * SLOTS_PER_DAY,
            price_p_per_kwh=prices,
        )
        relaxed = _solve(day, zeros, with_mode=False)
        integral = _solve(day, zeros, with_mode=True)
        assert relaxed.solver == "lp"
        assert all(
            charge <= _ABS or discharge <= _ABS
            for charge, discharge in zip(
                relaxed.charge_kw, relaxed.discharge_kw, strict=True
            )
        )
        assert relaxed.cost_pence == pytest.approx(integral.cost_pence, abs=_ABS)
        assert optimise_home(day).solver == "lp"


def test_negative_price_fixture_day_falls_back_to_the_mixed_integer_program(
    tmp_path: Path,
) -> None:
    # Agile fixture for 2024-06-15, region C, includes a negative price.
    # With the store already full, the linear program's only profit from that
    # price is to cycle and import the loss, so its bill is below the
    # mixed-integer bill. The returned schedule is the mixed-integer one.
    fixture = _FIXTURES / "agile_import_c_2024-06-15.json"
    prices = AgilePriceSource(
        cache_dir=tmp_path, opener=lambda _url: fixture.read_bytes()
    ).load(date(2024, 6, 15), "C")
    # soc_initial is 1, so the negative slot cannot store extra energy for
    # later. The only way the linear program profits from that price is to
    # charge and discharge in the slot and import the round-trip loss.
    day = HomeDay(
        battery=_example_battery(
            max_charge_kw=4.0, max_discharge_kw=4.0, soc_initial=1.0
        ),
        demand_kw=[0.0] * SLOTS_PER_DAY,
        price_p_per_kwh=list(prices.price_p_per_kwh),
    )
    zeros = [0.0] * SLOTS_PER_DAY
    relaxed = _solve(day, zeros, with_mode=False)
    integral = _solve(day, zeros, with_mode=True)
    assert relaxed.cost_pence < integral.cost_pence
    assert any(
        charge > _ABS and discharge > _ABS
        for charge, discharge in zip(
            relaxed.charge_kw, relaxed.discharge_kw, strict=True
        )
    )
    returned = optimise_home(day)
    assert returned.solver == "milp"
    assert returned.charge_kw == pytest.approx(integral.charge_kw, abs=_ABS)
    assert returned.discharge_kw == pytest.approx(integral.discharge_kw, abs=_ABS)
    assert returned.grid_import_kw == pytest.approx(integral.grid_import_kw, abs=_ABS)
    assert returned.cost_pence == pytest.approx(integral.cost_pence, abs=_ABS)


def test_a_negative_adjustment_on_a_positive_tariff_uses_the_effective_price() -> None:
    # Illustration battery, one slot, tariff +2 p/kWh. An adjustment of -10
    # makes the effective price -8, the same price as the negative-price
    # illustration. The tariff is positive. The linear program still cycles,
    # and the returned schedule is the mixed-integer one, whose bill is 0.
    day = HomeDay.model_construct(
        battery=_example_battery(max_charge_kw=4.0, max_discharge_kw=4.0),
        demand_kw=[0.0],
        price_p_per_kwh=[2.0],
    )
    relaxed = _solve(day, [-10.0], with_mode=False)
    integral = _solve(day, [-10.0], with_mode=True)
    assert any(
        charge > _ABS and discharge > _ABS
        for charge, discharge in zip(
            relaxed.charge_kw, relaxed.discharge_kw, strict=True
        )
    )
    returned = optimise_home(day, [-10.0])
    assert returned.solver == "milp"
    assert returned.cost_pence == pytest.approx(integral.cost_pence, abs=_ABS)
    assert returned.cost_pence == pytest.approx(0.0, abs=_ABS)


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
