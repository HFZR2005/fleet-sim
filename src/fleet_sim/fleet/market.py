"""The fleet in the loop for one day: price inputs, the equilibrium, metrics.

See ``docs/formulation.md``, Fleet in the loop.
"""

from datetime import date

from fleet_sim.data.source import PriceSource
from fleet_sim.fleet.solve import solve_fleet
from fleet_sim.models.fleet import Fleet
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.models.market import (
    DayPriceInputs,
    EquilibriumDiagnostics,
    MarketDay,
    MarketMetrics,
    MarketSettings,
)
from fleet_sim.stubs import stub


@stub("historical Agile rates with R, k and π left at zero")
def day_price_inputs(
    day: date, region: str, price_source: PriceSource
) -> DayPriceInputs:
    """R, k and π for each slot of ``day``, and its historical Agile rates."""
    historical = price_source.load(day, region)
    zeros = [0.0] * SLOTS_PER_DAY
    return DayPriceInputs(
        region=historical.region,
        day=day,
        residual_load_gw=zeros,
        fuel_cost_gbp_per_mwh=zeros,
        wholesale_gbp_per_mwh=zeros,
        censored=[False] * SLOTS_PER_DAY,
        wholesale_upper_gbp_per_mwh=[None] * SLOTS_PER_DAY,
        historical=historical,
    )


@stub("solves every home at historical prices with b = 0")
def solve_market_day(
    fleet: Fleet,
    inputs: DayPriceInputs,
    national_batteries: float,
    settings: MarketSettings,
) -> MarketDay:
    """The equilibrium (EQ) of one fleet-day, by (JOINT) subject to (LINK).

    ``docs/formulation.md``, Computing it. With κ = M / (N_b · 10⁶) GW per kW
    from (LOAD), minimise (Δ/κ) Σ_t Σ_k σ_tk u_tk over every battery home's
    feasible set.
    """
    added_load_gw = [0.0] * SLOTS_PER_DAY
    prices = inputs.prices(added_load_gw)
    solved = solve_fleet(fleet, prices, None)
    return MarketDay(
        day=inputs.day,
        added_load_gw=added_load_gw,
        prices=prices,
        joint=solved.homes,
        replanned=solved.homes,
        diagnostics=equilibrium_diagnostics(),
    )


@stub("returns zeros")
def equilibrium_diagnostics() -> EquilibriumDiagnostics:
    """Linearisation error, (MODE) breaks, (CHECK) and out-of-range slots."""
    return EquilibriumDiagnostics(
        linearisation_error_p_per_kwh=0.0,
        mode_break_slots=0,
        max_replan_saving_p=0.0,
        total_replan_saving_p=0.0,
        out_of_range_slots=0,
    )


@stub("returns zeros")
def market_metrics(days: list[MarketDay]) -> MarketMetrics:
    """National added load, bills and prices over one replication's days."""
    if len(days) == 0:
        raise ValueError("market metrics need at least one day")
    return MarketMetrics(
        peak_added_load_gw=0.0,
        peak_added_load_hour=0,
        saving_per_battery_home_p_per_day=0.0,
        non_battery_price_change_p_per_day=0.0,
        mean_charge_price_p_per_kwh=0.0,
        mean_discharge_price_p_per_kwh=0.0,
    )
