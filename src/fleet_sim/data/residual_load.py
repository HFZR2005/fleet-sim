"""Half-hourly GB residual load: demand minus wind and solar.

R = ND − W_tx + F̄

where ND is National Demand (NESO), W_tx is transmission-connected wind
generation (Elexon), and F̄ is the daily mean of net exports plus
pumped-storage consumption (NESO).

See ``docs/data/residual-load.md`` for the full derivation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from statistics import fmean

from fleet_sim.data.elexon_generation import ElexonWindRow, load_elexon_wind
from fleet_sim.data.neso_demand import NesoDemandRow, load_neso_demand
from fleet_sim.data.settlement import period_to_utc


def load_residual_load(
    *,
    start_year: int,
    end_year: int,
    cache_dir: Path | None = None,
    opener_neso: Callable[[str], bytes] | None = None,
    opener_elexon: Callable[[str], bytes] | None = None,
) -> list[tuple[datetime, float]]:
    """Return ``(timestamp_utc, residual_load_gw)`` pairs.

    Loads NESO demand and Elexon wind data, computes residual load
    R = ND − W_tx + F̄ in MW, then converts to GW once at the end.

    See ``docs/data/residual-load.md``, §Derivation.
    """
    demand_by_key: dict[tuple[date, int], NesoDemandRow] = {}
    wind_by_key: dict[tuple[date, int], ElexonWindRow] = {}

    for year in range(start_year, end_year + 1):
        for d_row in load_neso_demand(
            year=year, cache_dir=cache_dir, opener=opener_neso
        ):
            demand_by_key[(d_row.settlement_date, d_row.settlement_period)] = d_row

        for w_row in load_elexon_wind(
            year=year, cache_dir=cache_dir, opener=opener_elexon
        ):
            wind_by_key[(w_row.settlement_date, w_row.settlement_period)] = w_row

    common_keys = sorted(set(demand_by_key) & set(wind_by_key))
    if not common_keys:
        raise ValueError(
            "no overlapping settlement periods between NESO and Elexon data"
        )

    f_bar = _daily_mean_flexibility(demand_by_key, common_keys)

    results: list[tuple[datetime, float]] = []
    for sd, sp in common_keys:
        demand = demand_by_key[(sd, sp)]
        wind = wind_by_key[(sd, sp)]
        r_mw = demand.nd_mw - wind.generation_mw + f_bar[sd]
        r_gw = r_mw / 1000.0
        utc = period_to_utc(sd, sp)
        results.append((utc, r_gw))

    return results


def _daily_mean_flexibility(
    demand_by_key: dict[tuple[date, int], NesoDemandRow],
    keys: list[tuple[date, int]],
) -> dict[date, float]:
    r"""Compute F̄ per day: daily mean of net exports + pump-storage consumption.

    NESO sign convention: interconnector flow is positive when GB imports.
    Net exports = −interconnector_flow.
    Pump-storage pumping is positive when consuming electricity.

    F̄ = mean(−interconnector_flow + pump_storage_pumping) over the day.
    """
    daily_values: dict[date, list[float]] = defaultdict(list)
    for sd, sp in keys:
        row = demand_by_key[(sd, sp)]
        flexibility_mw = -row.interconnector_flow_mw + row.pump_storage_pumping_mw
        daily_values[sd].append(flexibility_mw)

    return {day: fmean(vals) for day, vals in daily_values.items()}
