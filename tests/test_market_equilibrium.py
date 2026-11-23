"""The fleet-day equilibrium as one linear program, and its diagnostics."""

from datetime import date
from pathlib import Path

import pytest

from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.fleet.market import market_metrics, solve_market_day
from fleet_sim.fleet.price_inputs import DayPriceInputs, day_price_inputs
from fleet_sim.fleet.solve import solve_fleet
from fleet_sim.models.fleet import Fleet, Home
from fleet_sim.models.home import BatterySpec
from fleet_sim.models.market import MarketSettings
from fleet_sim.models.prices import PriceSeries
from fleet_sim.prices.config import load_config
from fleet_sim.prices.parameters import load_price_model

_ROOT = Path(__file__).parents[1]
_DAY = date(2024, 6, 15)


class _LinearPrices:
    """P_c(b) = 10 + 2.5b in the cheap slot c, and 20 + 2.5b in every other."""

    def __init__(self, cheap_slot: int = 0) -> None:
        self.cheap_slot = cheap_slot

    def prices(self, added_load_gw: list[float]) -> PriceSeries:
        return PriceSeries(
            region="C",
            day=_DAY,
            timestamps_utc=settlement_periods_utc(_DAY),
            price_p_per_kwh=[
                (10.0 if slot == self.cheap_slot else 20.0) + 2.5 * b
                for slot, b in enumerate(added_load_gw)
            ],
        )

    def out_of_range_slots(
        self, added_load_gw: list[float], curve_range_gw: tuple[float, float]
    ) -> int:
        return 0


def test_two_homes_share_two_slots_at_equal_prices() -> None:
    # Two identical homes: E = 2 kWh, η = 1, s_0 = 0.5, c̄ = d̄ = 2 kW.
    # Demand L = (0, 2) kW in slots 0 and 1. κ = 2e6 / (2 · 1e6) = 1 GW/kW.
    #
    # The day has 48 slots, so slots 2..47 have no demand and price
    # 20 + 2.5b. They stay idle: with no demand a home can't discharge there
    # (g ≥ 0), and charging there costs at least 20 p/kWh against 15 in
    # slot 0. So the two-slot hand answer holds.
    #
    # Each home: g_0 = n_0 ≥ 0, (TERMINAL) with η = 1 gives n_1 = −n_0,
    # and (SOC) after slot 0 caps n_0 at 2. With B = b_0 = −b_1,
    #   Φ = (Δ/κ)[∫_0^B (10 + 2.5β)dβ + ∫_0^{−B} (20 + 2.5β)dβ]
    #     = 0.5 (2.5B² − 10B),
    # minimised at B = 2. So b* = (2, −2) GW and p* = (15, 15) p/kWh.
    # The homes together charge 2 kW in slot 0; how they split it is not
    # determined, since at equal prices any split is an equilibrium.
    # Each home's bill at p* is 0.5 (15 g_0 + 15 g_1) = 0.5 · 15 · 2 = 15 p,
    # since g_0 + g_1 = L_0 + L_1 = 2 kW. Re-planned alone at p* it can do no
    # better than 15 p either, so (CHECK) is 0.
    #
    # Segments: b from −4 to 4 GW in 40 segments of 0.2 GW. b* = 2 is a
    # breakpoint between σ = P_0(1.9) = 14.75 and P_0(2.1) = 15.25, so the
    # error is |15 − 14.75| = 0.25 p/kWh, 0.1 GW × 2.5 p/kWh per GW, either
    # way. Slot 1 at −2 GW and the idle slots at 0 GW are breakpoints too.
    #
    # With M = 0 the prices are historical, (10, 20): each home charges its
    # 2 kW limit in slot 0 and discharges it in slot 1.
    battery = BatterySpec(
        capacity_kwh=2.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        soc_initial=0.5,
    )
    demand = [0.0, 2.0] + [0.0] * 46
    fleet = Fleet(
        homes=[
            Home(home_id=f"home-{i}", region="C", battery=battery, demand_kw=demand)
            for i in (1, 2)
        ]
    )
    settings = MarketSettings(national_batteries=2e6, segments=40)

    day = solve_market_day(fleet, _LinearPrices(), 2e6, settings)
    historical = solve_market_day(fleet, _LinearPrices(), 0.0, settings)

    assert day.added_load_gw == pytest.approx([2.0, -2.0] + [0.0] * 46, abs=1e-6)
    assert day.prices.price_p_per_kwh[:2] == pytest.approx([15.0, 15.0])
    assert sum(h.schedule.charge_kw[0] for h in day.joint) == pytest.approx(2.0)
    assert sum(h.schedule.discharge_kw[1] for h in day.joint) == pytest.approx(2.0)
    assert [h.schedule.cost_pence for h in day.joint] == pytest.approx([15.0, 15.0])
    d = day.diagnostics
    assert d.linearisation_error_p_per_kwh == pytest.approx(0.25)
    assert d.max_replan_saving_p == pytest.approx(0.0, abs=1e-6)
    assert d.total_replan_saving_p == pytest.approx(0.0, abs=1e-6)
    assert not d.exceeds_tolerance
    assert d.mode_break_slots == 0
    assert [h.schedule.charge_kw[0] for h in historical.joint] == [2.0, 2.0]


def test_market_measures_of_the_two_home_case() -> None:
    # The two-home case above, moved to slots 6 and 7 (hour 3): the cheap
    # slot is 6 and demand L = 2 kW is in slot 7. A third home has no
    # battery and the same demand. κ = 2e6 / (2 · 1e6) is unchanged, since
    # N_b = 2. One day, so D = 1, and Δ = 0.5 h.
    #
    # M = 2e6: b* = (2, −2) GW in slots 6 and 7, p* = (15, 15), historical
    # p⁰ = (10, 20). Net power per battery home is (2, −2) / 2 = (1, −1) kW.
    #   peak added load 2 GW, hour ⌊6 / 2⌋ = 3
    #   S = −Δ/N_b Σ_t p*_t Σ_j n_jt = −0.5/2 · (15 · 2 + 15 · (−2)) = 0
    #   C = Δ/N Σ_j Σ_t (p* − p⁰) L = 0.5/3 · 3 · (15 − 20) · 2 = −5 p/day
    #   charging price 15 (all in slot 6), discharging price 15 (slot 7).
    # M = 0: each home charges 2 kW in slot 6 and discharges 2 kW in slot 7,
    # at (10, 20). Net power per battery home is (2, −2) kW.
    #   peak added load 0 GW, hour 3 (the herd's slot)
    #   S = −0.5/2 · (10 · 4 + 20 · (−4)) = 10 p/day; averaged over all three
    #   homes it would be 20/3, so this checks the battery-home count
    #   C = 0, charging price 10, discharging price 20.
    battery = BatterySpec(
        capacity_kwh=2.0,
        max_charge_kw=2.0,
        max_discharge_kw=2.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        soc_initial=0.5,
    )
    demand = [0.0] * 7 + [2.0] + [0.0] * 40
    fleet = Fleet(
        homes=[
            Home(home_id=f"home-{i}", region="C", battery=battery, demand_kw=demand)
            for i in (1, 2)
        ]
        + [Home(home_id="home-3", region="C", demand_kw=demand)]
    )
    prices = _LinearPrices(cheap_slot=6)
    settings = MarketSettings(national_batteries=2e6)

    loop = market_metrics([solve_market_day(fleet, prices, 2e6, settings)])
    herd = market_metrics([solve_market_day(fleet, prices, 0.0, settings)])

    assert loop.peak_added_load_gw == pytest.approx(2.0)
    assert loop.peak_added_load_hour == 3
    assert loop.saving_per_battery_home_p_per_day == pytest.approx(0.0, abs=1e-6)
    assert loop.non_battery_price_change_p_per_day == pytest.approx(-5.0)
    assert loop.mean_charge_price_p_per_kwh == pytest.approx(15.0)
    assert loop.mean_discharge_price_p_per_kwh == pytest.approx(15.0)
    assert loop.net_power_per_battery_home_kw[6:8] == pytest.approx([1.0, -1.0])
    assert herd.peak_added_load_gw == 0.0
    assert herd.peak_added_load_hour == 3
    assert herd.saving_per_battery_home_p_per_day == pytest.approx(10.0)
    assert herd.non_battery_price_change_p_per_day == 0.0
    assert herd.mean_charge_price_p_per_kwh == pytest.approx(10.0)
    assert herd.mean_discharge_price_p_per_kwh == pytest.approx(20.0)
    assert herd.net_power_per_battery_home_kw[6:8] == pytest.approx([2.0, -2.0])


def _inputs(cache: Path) -> DayPriceInputs:
    """15 June 2024 in region C under the main model."""
    model = load_price_model(
        _ROOT / "calibration" / "price_curves.json", "fuel_adjusted/exponential"
    )
    config = load_config(_ROOT / "calibration" / "price_curves.toml")
    return day_price_inputs(_DAY, "C", cache, model=model, fuel_cost=config.fuel_cost)


@pytest.fixture
def fleet() -> Fleet:
    """Three different battery homes and one without, with an evening peak."""
    demand = [0.4] * 34 + [1.5] * 6 + [0.4] * 8
    batteries = [
        BatterySpec(
            capacity_kwh=capacity,
            max_charge_kw=power,
            max_discharge_kw=power,
            eta_charge=0.95,
            eta_discharge=0.95,
            soc_initial=0.5,
        )
        for capacity, power in ((5.0, 3.6), (10.0, 5.0), (13.5, 5.0))
    ]
    homes = [
        Home(home_id=f"home-{i}", region="C", battery=battery, demand_kw=demand)
        for i, battery in enumerate([*batteries, None])
    ]
    return Fleet(homes=homes)


def test_a_tiny_fleet_pays_its_historical_bills(
    price_cache: Path, fleet: Fleet
) -> None:
    # M = 1e-3 batteries: κ = 1e-3 / (3 · 1e6) GW per kW and the homes have
    # 13.6 kW of charge between them, so |b*| < 5e-12 GW and every price is
    # historical. Each home's bill must then be its milestone-4 bill.
    inputs = _inputs(price_cache)
    settings = MarketSettings(national_batteries=1e-3)

    day = solve_market_day(fleet, inputs, 1e-3, settings)
    alone = solve_fleet(fleet, inputs.prices([0.0] * 48), None)

    assert max(abs(b) for b in day.added_load_gw) < 1e-6
    assert [h.schedule.cost_pence for h in day.joint] == pytest.approx(
        [h.schedule.cost_pence for h in alone.homes], abs=1e-6
    )


def test_added_load_never_lowers_the_price(price_cache: Path, fleet: Fleet) -> None:
    # (PRICE) never decreases in b, so a slot the fleet adds load to can't be
    # cheaper than its historical rate.
    inputs = _inputs(price_cache)
    settings = MarketSettings(national_batteries=5e6)

    day = solve_market_day(fleet, inputs, 5e6, settings)
    historical = inputs.historical.price_p_per_kwh

    charged = [t for t, b in enumerate(day.added_load_gw) if b > 1e-9]
    assert charged
    for t in charged:
        assert day.prices.price_p_per_kwh[t] >= historical[t] - 1e-9
