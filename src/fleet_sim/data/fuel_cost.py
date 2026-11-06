"""Marginal fuel cost of gas generation.

k_t = HR × (G_t + c_gas × C_t)

where G_t is the daily gas price (£/MWh gas), C_t is the total carbon
price (ETS + CPS, £/tCO₂), HR is the heat rate (MWh gas per MWh
electricity), and c_gas is the gas carbon intensity (tCO₂ per MWh gas).

See ``docs/data/fuel-cost.md``, §Formula.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from fleet_sim.data.carbon_price import load_carbon_prices
from fleet_sim.data.gas_price import load_gas_prices
from fleet_sim.data.settlement import settlement_periods_utc


def compute_fuel_cost(
    *,
    start_year: int,
    end_year: int,
    heat_rate: float,
    gas_carbon_intensity: float,
    include_carbon_price_support: bool,
    cache_dir: Path | None = None,
    gas_opener: Callable[[str], bytes] | None = None,
    carbon_opener: Callable[[str], bytes] | None = None,
) -> list[tuple[datetime, float]]:
    """Return ``(settlement_start_utc, fuel_cost_gbp_per_mwh)`` pairs.

    k_t = HR × (G_t + c_gas × C_t)  (``docs/data/fuel-cost.md``, §Formula)

    The gas price is daily and the carbon price monthly (held constant
    within each month).  Each day's k is assigned to every settlement
    period of that UK calendar day, so the output aligns with the other
    half-hourly series.  Days with no carbon price are skipped.
    """
    gas_rows = load_gas_prices(
        start_year=start_year,
        end_year=end_year,
        cache_dir=cache_dir,
        opener=gas_opener,
    )
    carbon_rows = load_carbon_prices(
        start_year=start_year,
        end_year=end_year,
        include_carbon_price_support=include_carbon_price_support,
        cache_dir=cache_dir,
        opener=carbon_opener,
    )

    carbon_by_month = {
        row.month_start: row.ets_gbp_per_tco2 + row.cps_gbp_per_tco2
        for row in carbon_rows
    }

    results: list[tuple[datetime, float]] = []
    for gas_row in gas_rows:
        d = gas_row.price_date
        c_t = carbon_by_month.get(date(d.year, d.month, 1))
        if c_t is None:
            continue
        k_t = heat_rate * (gas_row.sap_gbp_per_mwh + gas_carbon_intensity * c_t)
        results.extend((stamp, k_t) for stamp in settlement_periods_utc(d))

    results.sort(key=lambda r: r[0])
    return results
