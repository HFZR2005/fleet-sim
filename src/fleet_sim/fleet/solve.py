"""Solve each home in a fleet for one day, then add up the imports.

Callers that want a fleet result call ``solve_fleet`` and not the one-home
solver. The loop solves every home on its own, including identical ones.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from fleet_sim.fleet.homes import Fleet
from fleet_sim.fleet.network import HomeProfile, Network, NodeFeedback
from fleet_sim.models.home import HomeDay
from fleet_sim.models.prices import PriceSeries, require_gsp_region
from fleet_sim.models.schedule import Schedule
from fleet_sim.optimise.home import optimise_home


class SolvedHome(BaseModel):
    """One home's schedule for the day, with the demand it was given."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    transformer_id: str | None
    demand_kw: list[float]
    schedule: Schedule


class FleetDay(BaseModel):
    """Schedules for every home, and the network's flow for the day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    homes: list[SolvedHome]
    nodes: list[NodeFeedback]


def solve_fleet(
    homes: Fleet,
    prices: PriceSeries,
    signals: Sequence[Sequence[float]] | None,
) -> FleetDay:
    """Solve each home against ``prices`` and report the root-node flow.

    ``signals`` is one price adjustment per home, in the same order as
    ``homes``. ``None`` leaves every adjustment at zero. The network is one
    unconstrained root, and every home sits under it.
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
        schedule = optimise_home(
            HomeDay(
                home_id=home.home_id,
                region=region,
                transformer_id=home.transformer_id,
                battery=home.battery,
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
