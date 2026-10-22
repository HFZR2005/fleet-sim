"""Solve each home in a fleet for one day, then add up the imports.

Callers that want a fleet result call ``solve_fleet`` and not the one-home
solver. The loop solves every home on its own, including identical ones.
"""

from collections.abc import Sequence

from fleet_sim.fleet.network import Network
from fleet_sim.models.fleet import Fleet, FleetDay, SolvedHome
from fleet_sim.models.home import HomeDay, Schedule
from fleet_sim.models.network import HomeProfile
from fleet_sim.models.prices import PriceSeries, require_gsp_region
from fleet_sim.optimise.home import optimise_home


def solve_fleet(
    homes: Fleet,
    prices: PriceSeries,
    signals: Sequence[Sequence[float]] | None,
) -> FleetDay:
    """Solve each home against ``prices`` and report the root-node flow.

    ``signals`` is one price adjustment per home, in the same order as
    ``homes``. ``None`` leaves every adjustment at zero. A home with no
    battery is not optimised: its import equals its demand, and the schedule
    has the same fields as an optimised home, so the network adds every home
    the same way. The network is one unconstrained root, and every home sits
    under it.
    """
    adjustments = _adjustments(homes, signals)
    solved: list[SolvedHome] = []
    profiles: list[HomeProfile] = []
    for home, adjustment in zip(homes.homes, adjustments, strict=True):
        region = require_gsp_region(home.region)
        if region != prices.region:
            raise ValueError(
                f"home {home.home_id} is in region {region}, not {prices.region}"
            )
        battery = home.battery
        if battery is None:
            schedule = _demand_only_schedule(
                list(home.demand_kw), list(prices.price_p_per_kwh)
            )
        else:
            schedule = optimise_home(
                HomeDay(
                    home_id=home.home_id,
                    region=region,
                    transformer_id=home.transformer_id,
                    battery=battery,
                    demand_kw=list(home.demand_kw),
                    price_p_per_kwh=list(prices.price_p_per_kwh),
                ),
                adjustment,
            )
        solved.append(
            SolvedHome(
                home_id=home.home_id,
                transformer_id=home.transformer_id,
                demand_kw=list(home.demand_kw),
                schedule=schedule,
            )
        )
        profiles.append(
            HomeProfile(home_id=home.home_id, grid_import_kw=schedule.grid_import_kw)
        )
    return FleetDay(homes=solved, nodes=Network().evaluate(profiles))


def _demand_only_schedule(
    demand_kw: list[float], price_p_per_kwh: list[float]
) -> Schedule:
    """Import the demand and leave the battery idle.

    With no battery, ``g_t = L_t``. The tariff bill is the sum of
    ``p_t * g_t * 0.5``, which is (COST) in ``docs/formulation.md`` when
    every adjustment is zero and there is nothing to store. State of charge
    is reported as 0. ``0.5`` is (DT).
    """
    slots = len(demand_kw)
    cost_pence = sum(
        price * demand * 0.5
        for price, demand in zip(price_p_per_kwh, demand_kw, strict=True)
    )
    return Schedule(
        charge_kw=[0.0] * slots,
        discharge_kw=[0.0] * slots,
        grid_import_kw=list(demand_kw),
        soc=[0.0] * slots,
        charge_mode=[0] * slots,
        cost_pence=cost_pence,
    )


def _adjustments(
    homes: Fleet, signals: Sequence[Sequence[float]] | None
) -> list[Sequence[float] | None]:
    if signals is None:
        return [None] * len(homes.homes)
    if len(signals) != len(homes.homes):
        raise ValueError(
            "signals must contain one adjustment per home "
            f"(got {len(signals)} for {len(homes.homes)} homes)"
        )
    return [list(signal) for signal in signals]
