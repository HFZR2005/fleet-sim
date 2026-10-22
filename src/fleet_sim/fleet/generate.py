"""Draw a fleet of homes from the household pool and a battery catalogue.

Battery ownership does not depend on demand. The two are drawn from
different streams. ``docs/assumptions.md`` records the catalogue and that
independence.
"""

import math
from collections.abc import Sequence
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.stats import truncnorm

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.fleet.homes import Fleet, Home, identical_homes
from fleet_sim.models.demand import DemandFallback
from fleet_sim.models.home import SLOTS_PER_DAY, BatterySpec
from fleet_sim.models.prices import require_gsp_region
from fleet_sim.models.scenario import (
    BatteryDistribution,
    BatteryProductSpec,
    EfficiencyDistribution,
)
from fleet_sim.random_streams import RandomStreams

# (DT) in docs/formulation.md. Demand from the pool is kWh per half hour.
_HOURS_PER_SLOT = 0.5
_SOC_INITIAL = 0.5

# One-way efficiency. The mean matches home.toml. The bounds stay inside the
# battery model's fraction and inside a lithium home inverter's usual band.
_ETA_MEAN = 0.95
_ETA_SD = 0.01
_ETA_LOW = 0.92
_ETA_HIGH = 0.97
FleetMode = Literal["diverse", "identical"]


class BatteryProduct(BaseModel):
    """One catalogue entry: a usable capacity and the inverters sold with it.

    ``power_kw`` is conditional on ``capacity_kwh``. Charge and discharge
    share one of those inverter ratings. ``weight`` is the relative chance
    of drawing this capacity. The weights in the catalogue are equal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity_kwh: float
    power_kw: tuple[float, ...]
    weight: float


# Usable kWh, then the inverter ratings sold with that size. 3.6 kW sits
# under the 3.68 kW G98 single-phase limit. 5 kW is the continuous rating
# of a Powerwall 2, whose usable capacity is 13.5 kWh, and it is also a
# common rating on a 10 kWh battery. See docs/assumptions.md.
BATTERY_PRODUCTS: tuple[BatteryProduct, ...] = (
    BatteryProduct(capacity_kwh=5.0, power_kw=(3.6,), weight=1.0),
    BatteryProduct(capacity_kwh=10.0, power_kw=(3.6, 5.0), weight=1.0),
    BatteryProduct(capacity_kwh=13.5, power_kw=(5.0,), weight=1.0),
)


class GeneratedFleet(BaseModel):
    """A fleet for one day, plus any trial-day fallbacks behind its demand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fleet: Fleet
    fallbacks: list[DemandFallback]


def generate_fleet(
    pool: HouseholdDemandPool,
    day: date,
    n_homes: int,
    seed: int,
    penetration: float,
    *,
    region: str = "C",
    mode: FleetMode = "diverse",
    distribution: BatteryDistribution | None = None,
) -> GeneratedFleet:
    """Draw ``n_homes`` homes for ``day``.

    ``mode="diverse"`` gives each home its own household and, when it owns a
    battery, its own product. ``mode="identical"`` builds the diverse fleet
    and then returns ``n_homes`` copies of its mean home. The same seed
    returns the same fleet. Households come from the ``demand`` stream,
    ownership from the ``penetration`` stream, and products from the
    ``battery`` stream. ``distribution`` replaces the catalogue in
    ``docs/assumptions.md`` when a scenario names its own.
    """
    gsp = require_gsp_region(region)
    _require_penetration(penetration)
    products = default_battery_distribution() if distribution is None else distribution
    if mode not in ("diverse", "identical"):
        raise ValueError(f"mode must be 'diverse' or 'identical' (got {mode!r})")
    streams = RandomStreams(seed)
    households = pool.assign(n_homes, streams)
    draws = [float(value) for value in streams.generator("penetration").random(n_homes)]
    owned = set(_owned_indices(draws, penetration))
    battery_stream = streams.generator("battery")
    homes: list[Home] = []
    fallbacks: list[DemandFallback] = []
    for index, household_id in enumerate(households):
        load = pool.load(household_id, day)
        demand_kw = [energy / _HOURS_PER_SLOT for energy in load.series.demand_kwh]
        if load.fallback is not None:
            fallbacks.append(load.fallback)
        battery: BatterySpec | None = _draw_battery(battery_stream, products)
        if index not in owned:
            battery = None
        homes.append(
            Home(
                home_id=f"home-{index + 1}",
                region=gsp,
                household_id=household_id,
                battery=battery,
                demand_kw=demand_kw,
            )
        )
    fleet = Fleet(homes=homes)
    if mode == "identical":
        fleet = mean_fleet(fleet)
    return GeneratedFleet(fleet=fleet, fallbacks=fallbacks)


def with_demand(fleet: Fleet, pool: HouseholdDemandPool, day: date) -> GeneratedFleet:
    """Reload each home's demand for ``day`` from the household it was given.

    Batteries, ids, and the region stay as they are. A home with no
    ``household_id`` cannot be reloaded.
    """
    homes: list[Home] = []
    fallbacks: list[DemandFallback] = []
    for home in fleet.homes:
        household_id = home.household_id
        if household_id is None:
            raise ValueError(
                f"home {home.home_id} has no household, so its demand "
                "cannot be reloaded"
            )
        load = pool.load(household_id, day)
        if load.fallback is not None:
            fallbacks.append(load.fallback)
        homes.append(
            home.model_copy(
                update={
                    "demand_kw": [
                        energy / _HOURS_PER_SLOT for energy in load.series.demand_kwh
                    ]
                }
            )
        )
    return GeneratedFleet(fleet=Fleet(homes=homes), fallbacks=fallbacks)


def battery_owner_count(penetration: float, n_homes: int) -> int:
    """How many homes own a battery at ``penetration``.

    Halfway cases round away from zero. Python's ``round`` would give one
    home at 50% no battery, because it rounds halves to even.
    """
    _require_penetration(penetration)
    if isinstance(n_homes, bool) or not isinstance(n_homes, int):
        raise TypeError(f"n_homes must be an int (got {n_homes!r})")
    if n_homes < 1:
        raise ValueError(f"n_homes must be at least 1 (got {n_homes})")
    return math.floor(penetration * n_homes + 0.5)


def _owned_indices(draws: Sequence[float], penetration: float) -> list[int]:
    """Homes with the smallest penetration draws, lowest index on a tie.

    Taking the smallest ``battery_owner_count`` draws makes that count
    exact, and a lower penetration is a subset of a higher one for the same
    draws.
    """
    count = battery_owner_count(penetration, len(draws))
    order = sorted(range(len(draws)), key=lambda index: (float(draws[index]), index))
    return order[:count]


def default_battery_distribution() -> BatteryDistribution:
    """The catalogue and efficiency band in ``docs/assumptions.md``."""
    return BatteryDistribution(
        products=[
            BatteryProductSpec(
                capacity_kwh=product.capacity_kwh,
                power_kw=list(product.power_kw),
                weight=product.weight,
            )
            for product in BATTERY_PRODUCTS
        ],
        efficiency=EfficiencyDistribution(
            mean=_ETA_MEAN,
            standard_deviation=_ETA_SD,
            low=_ETA_LOW,
            high=_ETA_HIGH,
        ),
        soc_initial=_SOC_INITIAL,
    )


def mean_fleet(fleet: Fleet) -> Fleet:
    """N copies of the mean demand and the mean owned battery."""
    return _identical(fleet, [list(home.demand_kw) for home in fleet.homes])


def _draw_battery(
    generator: np.random.Generator, distribution: BatteryDistribution
) -> BatterySpec:
    """One catalogue product, then a one-way efficiency for each direction.

    Capacity is drawn first. The inverter is then drawn from the ratings
    sold with that capacity, and both power limits take that one rating.
    """
    products = distribution.products
    weights = [product.weight for product in products]
    total = sum(weights)
    probabilities = [weight / total for weight in weights]
    picked = int(generator.choice(len(products), p=probabilities))
    product = products[picked]
    power_kw = float(generator.choice(product.power_kw))
    return BatterySpec(
        capacity_kwh=product.capacity_kwh,
        max_charge_kw=power_kw,
        max_discharge_kw=power_kw,
        eta_charge=_efficiency(generator, distribution.efficiency),
        eta_discharge=_efficiency(generator, distribution.efficiency),
        soc_initial=distribution.soc_initial,
    )


def _efficiency(
    generator: np.random.Generator, efficiency: EfficiencyDistribution
) -> float:
    draw = float(generator.random())
    scale = efficiency.standard_deviation
    low = (efficiency.low - efficiency.mean) / scale
    high = (efficiency.high - efficiency.mean) / scale
    value = float(truncnorm.ppf(draw, low, high, loc=efficiency.mean, scale=scale))
    return min(efficiency.high, max(efficiency.low, value))


def _identical(fleet: Fleet, demands: list[list[float]]) -> Fleet:
    """N copies of the mean demand and the mean owned battery."""
    n_homes = len(fleet.homes)
    mean_demand = [
        sum(demand[slot] for demand in demands) / n_homes
        for slot in range(SLOTS_PER_DAY)
    ]
    owned = [home.battery for home in fleet.homes if home.battery is not None]
    battery: BatterySpec | None
    if not owned:
        battery = None
    else:
        battery = BatterySpec(
            capacity_kwh=sum(item.capacity_kwh for item in owned) / len(owned),
            max_charge_kw=sum(item.max_charge_kw for item in owned) / len(owned),
            max_discharge_kw=sum(item.max_discharge_kw for item in owned) / len(owned),
            eta_charge=sum(item.eta_charge for item in owned) / len(owned),
            eta_discharge=sum(item.eta_discharge for item in owned) / len(owned),
            soc_initial=sum(item.soc_initial for item in owned) / len(owned),
        )
    template = Home(
        home_id="home",
        region=fleet.homes[0].region,
        battery=battery,
        demand_kw=mean_demand,
    )
    return identical_homes(template, n_homes)


def _require_penetration(penetration: float) -> None:
    if isinstance(penetration, bool) or not isinstance(penetration, int | float):
        raise TypeError(f"penetration must be a float (got {penetration!r})")
    if not 0 <= float(penetration) <= 1:
        raise ValueError(f"penetration must be in [0, 1] (got {penetration})")
