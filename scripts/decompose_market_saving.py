"""Split the headline point's saving loss into its cheap and dear ends.

Not collected by pytest. From the repository root, with the Low Carbon
London zip in ``.cache/lcl`` and the price-curve cache that
``scenarios/market-sweep.toml`` filled in ``.cache/prices``:

    uv run python scripts/decompose_market_saving.py

Re-solves the headline point of ``scenarios/market-sweep.toml`` (ρ = 0,
local penetration 1.0) for each price model and M, on the same fleets as
the sweep, and prints each measure as a mean over replications with its
95% interval. ``docs/results/milestone-4.6.md`` quotes the output.

For one replication, with p⁰ the historical price, p* the equilibrium
price at M, and c⁰, d⁰ the fleet's charging and discharging at M = 0:

- Price change where the herd charged: Σ (p* − p⁰) c⁰ / Σ c⁰, and where it
  discharged: Σ (p* − p⁰) d⁰ / Σ d⁰, in p/kWh, summed over days and slots.
- The change in saving per battery home S (``docs/formulation.md``, Market
  measures) splits exactly into three parts, in p/day:
    charging dearer    −Δ Σ (p* − p⁰) c⁰ / (D N_b)
    discharging cheaper  Δ Σ (p* − p⁰) d⁰ / (D N_b)
    re-scheduling        S(c*, d* at p*) − S(c⁰, d⁰ at p*)
- Peak net power per battery home, max over days and slots of
  Σ_j (c − d) / N_b, in kW (GW per million batteries), for the joint and
  the re-planned allocation.
"""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.experiments.report import replication_seed, t_interval
from fleet_sim.fleet.generate import generate_fleet, with_demand
from fleet_sim.fleet.market import solve_market_day
from fleet_sim.fleet.price_inputs import day_price_inputs
from fleet_sim.fleet.topology import assign_transformers, build_topology
from fleet_sim.models.fleet import SolvedHome
from fleet_sim.models.market import MarketDay
from fleet_sim.prices.config import load_config
from fleet_sim.prices.parameters import load_price_model
from fleet_sim.random_streams import RandomStreams
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).resolve().parents[1]
_SCENARIO = _ROOT / "scenarios" / "market-sweep.toml"
_ZIP = _ROOT / ".cache" / "lcl" / "LCL-FullData.zip"
_CALIBRATION = _ROOT / "calibration" / "price_curves.toml"
_POOL_HOUSEHOLDS = 100
_SLOT_HOURS = 0.5

Array = npt.NDArray[np.float64]


def main() -> None:
    scenario = load_scenario(_SCENARIO)
    if scenario.market is None or scenario.network is None:
        raise ValueError(f"{_SCENARIO} needs [market] and [network] sections")
    settings = scenario.market
    pool = HouseholdDemandPool.read(_ZIP, max_households=_POOL_HOUSEHOLDS)
    calibration = load_config(_CALIBRATION)
    cache = _ROOT / calibration.data.cache_dir
    days = [
        scenario.start + timedelta(days=offset)
        for offset in range((scenario.end - scenario.start).days + 1)
    ]
    rho = scenario.network.rho_levels()[0]
    penetration = max(scenario.penetration_levels())
    levels = settings.national_battery_levels()
    if 0.0 not in levels:
        levels = [0.0, *levels]
    home_ids = [f"home-{i + 1}" for i in range(scenario.n_homes)]
    spec = build_topology(home_ids, scenario.network, RandomStreams(scenario.seed))

    for model in settings.price_models():
        inputs = [
            day_price_inputs(
                day,
                scenario.region,
                cache,
                model=load_price_model(settings.price_parameters_file, model),
                fuel_cost=calibration.fuel_cost,
            )
            for day in days
        ]
        samples: dict[float, dict[str, list[float]]] = {m: {} for m in levels}
        for index in range(scenario.replications):
            generated = generate_fleet(
                pool,
                scenario.start,
                scenario.n_homes,
                replication_seed(scenario.seed, index),
                penetration,
                region=scenario.region,
                distribution=scenario.battery,
                transformer_map=spec.home_transformer,
                rho=rho,
            )
            base = assign_transformers(generated.fleet, spec)
            fleets = [with_demand(base, pool, day).fleet for day in days]
            solved = {
                m: [
                    solve_market_day(fleet, day_inputs, m, settings)
                    for fleet, day_inputs in zip(fleets, inputs, strict=True)
                ]
                for m in levels
            }
            _measure(solved, samples)
        print(model)
        for m in levels:
            print(f"  M = {m / 1e6:g} million")
            for name, values in samples[m].items():
                interval = t_interval(values)
                print(
                    f"    {name}: {interval.mean:.2f} "
                    f"({interval.low:.2f} to {interval.high:.2f})"
                )


def _measure(
    solved: dict[float, list[MarketDay]], samples: dict[float, dict[str, list[float]]]
) -> None:
    """Add one replication's measures at every M to ``samples``."""
    baseline = solved[0.0]
    battery_homes = len(baseline[0].battery_home_ids)
    scale = _SLOT_HOURS / (battery_homes * len(baseline))
    historical = np.array([day.historical_prices.price_p_per_kwh for day in baseline])
    charge_0, discharge_0 = _flows(baseline, "joint")
    for m, market_days in solved.items():
        price = np.array([day.prices.price_p_per_kwh for day in market_days])
        change = price - historical
        charge, discharge = _flows(market_days, "joint")
        replanned_charge, replanned_discharge = _flows(market_days, "replanned")
        values = {
            "price change where the herd charged (p/kWh)": float(
                (change * charge_0).sum() / charge_0.sum()
            ),
            "price change where the herd discharged (p/kWh)": float(
                (change * discharge_0).sum() / discharge_0.sum()
            ),
            "saving change from charging dearer (p/day)": -scale
            * float((change * charge_0).sum()),
            "saving change from discharging cheaper (p/day)": scale
            * float((change * discharge_0).sum()),
            "saving change from re-scheduling (p/day)": scale
            * float((price * (discharge - charge - discharge_0 + charge_0)).sum()),
            "saving per battery home (p/day)": scale
            * float((price * (discharge - charge)).sum()),
            "energy charged per battery home (kWh/day)": scale * float(charge.sum()),
            "energy discharged per battery home (kWh/day)": scale
            * float(discharge.sum()),
            "peak net power per battery home, joint (kW)": float(
                (charge - discharge).max() / battery_homes
            ),
            "peak net power per battery home, re-planned (kW)": float(
                (replanned_charge - replanned_discharge).max() / battery_homes
            ),
        }
        for name, value in values.items():
            samples[m].setdefault(name, []).append(value)


def _flows(days: Sequence[MarketDay], allocation: str) -> tuple[Array, Array]:
    """The battery homes' summed charging and discharging, day by slot, kW."""
    charge = np.array([_total(day, allocation, "charge_kw") for day in days])
    discharge = np.array([_total(day, allocation, "discharge_kw") for day in days])
    return charge, discharge


def _total(day: MarketDay, allocation: str, field: str) -> Array:
    homes: list[SolvedHome] = day.joint if allocation == "joint" else day.replanned
    batteries = set(day.battery_home_ids)
    rows = [
        getattr(home.schedule, field) for home in homes if home.home_id in batteries
    ]
    return np.asarray(rows, dtype=np.float64).sum(axis=0)


if __name__ == "__main__":
    main()
