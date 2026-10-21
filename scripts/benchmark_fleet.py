"""Time one simulated day for a fleet of identical homes.

Not run in CI. From the repository root:

    uv run python scripts/benchmark_fleet.py
"""

import time
from datetime import date, timedelta

from fleet_sim.fleet import Home, identical_homes, solve_fleet
from fleet_sim.models import BatterySpec, PriceSeries
from fleet_sim.models.prices import london_day_bounds_utc

_SIZES = (100, 1_000, 10_000)


def _prices() -> PriceSeries:
    day = date(2024, 6, 15)
    start, _end = london_day_bounds_utc(day)
    # A cheap night and a dear evening, so the solve has something to move.
    prices = [8.0] * 16 + [20.0] * 16 + [35.0] * 10 + [15.0] * 6
    return PriceSeries(
        region="C",
        day=day,
        timestamps_utc=[start + timedelta(minutes=30) * index for index in range(48)],
        price_p_per_kwh=prices,
    )


def main() -> None:
    prices = _prices()
    template = Home(
        home_id="home",
        region="C",
        battery=BatterySpec(
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            eta_charge=0.95,
            eta_discharge=0.95,
            soc_initial=0.5,
        ),
        demand_kw=[0.3] * 16 + [0.6] * 16 + [1.5] * 10 + [0.6] * 6,
    )
    for n_homes in _SIZES:
        fleet = identical_homes(template, n_homes)
        started = time.perf_counter()
        solve_fleet(fleet, prices, None)
        elapsed = time.perf_counter() - started
        print(f"{n_homes} homes: {elapsed:.2f} s per simulated day")


if __name__ == "__main__":
    main()
