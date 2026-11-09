"""Anchored price response: historical prices moved by a change in load.

``price_response`` takes one day of historical slots, a fitted curve and
the load a fleet adds in each slot, and returns the Agile import rates
that day would have had.  Each slot keeps its historical residual εₜ and
moves along the fitted curve.

See ``docs/formulation.md``, Price curves, Anchoring.
"""

from __future__ import annotations

import math
from zoneinfo import ZoneInfo

from fleet_sim.data.agile_formula import (
    EPG_ADJUSTMENTS,
    VAT_MULTIPLIER,
    apply_agile,
    best_version_for_date,
    is_peak,
)
from fleet_sim.models.prices import PriceSeries
from fleet_sim.prices.curves import FittedCurve
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.targets import Target

_LONDON = ZoneInfo("Europe/London")
_EPG_START = min(e.start for e in EPG_ADJUSTMENTS)
_EPG_END = max(e.end for e in EPG_ADJUSTMENTS)


def price_response(
    day: PriceDataset,
    fitted: FittedCurve,
    target: Target,
    added_load_gw: list[float],
    *,
    region: str,
) -> PriceSeries:
    """Agile import rates for ``day`` with ``added_load_gw`` added to R.

    ``day`` is one UK day's 48 slots and ``added_load_gw`` holds bₜ for
    each, in the same order.  In £/MWh, the new wholesale price is

        π′ₜ = πₜ + kₜ·[h(Rₜ + bₜ) − h(Rₜ)]    (fuel-adjusted)
        π′ₜ = πₜ + f(Rₜ + bₜ) − f(Rₜ)          (raw)

    which is ``target.to_price`` applied to h(Rₜ + bₜ) − h(Rₜ), with
    kₜ = 1 for the raw target.  The residual εₜ = πₜ − kₜ·h(Rₜ) is held
    at its historical value.  A censored slot has no exact πₜ, so it is
    anchored on the fitted price clipped to its bounds,
    clip(kₜ·h(Rₜ), π⁻ₜ, π⁺ₜ), with π⁺ₜ = ∞ when unknown.

    Each π′ₜ becomes an Agile rate with ``apply_agile`` (π′ₜ / 10 in
    p/kWh, the product and peak window the inversion used), then VAT.
    Days of the Energy Price Guarantee are rejected: its discount is
    unknown for most of it, so the billed rate can't be recomputed.

    See ``docs/formulation.md``, Price curves, Anchoring.
    """
    observations = day.observations
    if len(added_load_gw) != len(observations):
        raise ValueError(
            f"added_load_gw must have one value per slot "
            f"({len(observations)}, got {len(added_load_gw)})"
        )
    london_day = observations[0].settlement_start.astimezone(_LONDON).date()
    if _EPG_START <= london_day <= _EPG_END:
        raise ValueError(
            f"{london_day} is in the Energy Price Guarantee "
            f"({_EPG_START} to {_EPG_END}); its Agile rates can't be recomputed"
        )

    rates: list[float] = []
    for obs, added in zip(observations, added_load_gw, strict=True):
        r = obs.residual_load_gw
        shift = target.to_price(fitted.predict(r + added) - fitted.predict(r), obs)
        wholesale_gbp_per_mwh = _anchor(obs, fitted, target) + shift
        start = obs.settlement_start
        rate_exc_vat, _ = apply_agile(
            wholesale_gbp_per_mwh / 10,
            region=region,
            peak=is_peak(start),
            version=best_version_for_date(start.date()),
        )
        rates.append(rate_exc_vat * VAT_MULTIPLIER)

    return PriceSeries(
        region=region,
        day=london_day,
        timestamps_utc=[o.settlement_start for o in observations],
        price_p_per_kwh=rates,
    )


def _anchor(obs: PriceObservation, fitted: FittedCurve, target: Target) -> float:
    """πₜ for an exact slot; clip(kₜ·h(Rₜ), π⁻ₜ, π⁺ₜ) for a censored one."""
    if not obs.censored:
        return obs.wholesale_price_gbp_per_mwh
    predicted = target.to_price(fitted.predict(obs.residual_load_gw), obs)
    upper = obs.wholesale_upper_gbp_per_mwh
    lower = obs.wholesale_price_gbp_per_mwh
    return min(max(predicted, lower), math.inf if upper is None else upper)
