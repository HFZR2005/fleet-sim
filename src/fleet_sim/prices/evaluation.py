"""Score a fitted price curve on a year of data.

``evaluate`` measures the curve's level error, its slope error between
consecutive half-hours, and that slope error weighted by where a fleet's
batteries charge and discharge.  ``comparison_table`` renders a report as
Markdown, and ``residuals`` gives each exact slot's residual for
anchoring.

Every error is in £/MWh, whatever the target: each prediction is turned
back into a price with ``Target.to_price``.  Censored slots have no
exact price, so they are left out of every error.  They count instead
through the censored log-likelihood and the hit rate.  ``bracket`` fits
one year three ways to show how much the treatment of censored slots
moves a curve.

See ``docs/formulation.md``, Price curves, Evaluation.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel, ConfigDict

from fleet_sim.prices.curves import FittedCurve, PriceCurve, censored_log_likelihood
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.fleet_weights import FleetCharging
from fleet_sim.prices.targets import Target

_LONDON = ZoneInfo("Europe/London")
_HALF_HOUR = timedelta(minutes=30)
_SEASONS = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}  # fmt: skip
# Points on the grid over the training range of R for the sanity checks.
_GRID_POINTS = 200

Split = Literal["held-out", "in-sample"]
BracketMethod = Literal["dropped", "lower_bound", "censored"]


class WeightedSlope(BaseModel):
    """Slope metrics weighted by the fleet's battery power on one side.

    ``weight_kw`` is the total weight, Σ|net battery kW| over the test
    slots on this side.  The two metrics are None when it is zero.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    weight_kw: float
    slope_rmse_gbp_per_mwh: float | None
    mean_slope_gbp_per_mwh_per_gw: float | None


class SlopeSanity(BaseModel):
    """The curve over the training range of R, in target units.

    ``min_slope`` is the least h′(R) on a grid of ``_GRID_POINTS`` points
    from ``r_min_gw`` to ``r_max_gw``; a negative value means the curve
    falls somewhere in the observed range.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    r_min_gw: float
    r_max_gw: float
    min_slope: float
    value_at_r_min: float
    slope_at_r_min: float
    value_at_r_max: float
    slope_at_r_max: float


class FitResult(BaseModel):
    """Metrics for one (curve family, target) model on one year.

    ``split`` is ``held-out`` when the curve was fitted to other years,
    and ``in-sample`` when it was fitted to this year (per-year targets).
    RMSEs are over exact slots only; seasons are DJF, MAM, JJA, SON and
    hours are Europe/London clock hours.  ``log_likelihood_per_slot`` is
    over every slot, in target units, so it compares families of one
    target but not targets.  ``hit_rate`` is None with no censored slot.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    curve_family: str
    target_name: str
    year: int
    split: Split
    exact_slots: int
    censored_slots: int
    rmse_gbp_per_mwh: float
    rmse_by_season_gbp_per_mwh: dict[str, float]
    rmse_by_hour_gbp_per_mwh: dict[int, float]
    slope_pairs: int
    slope_rmse_gbp_per_mwh: float
    charging: WeightedSlope
    discharging: WeightedSlope
    sanity: SlopeSanity
    log_likelihood_per_slot: float
    hit_rate: float | None


class Bracket(BaseModel):
    """One family fitted to one year by one treatment of censored slots.

    ``dropped`` fits the exact slots only, ``lower_bound`` takes each
    censored slot as exactly its lower bound, and ``censored`` uses the
    censored likelihood.  ``slope_at_r95`` is h′ at ``r95_gw``, the 95th
    percentile of the year's R, in target units per GW.  ``parameters``
    are the fit's scalar fields, σ included.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    curve_family: str
    target_name: str
    year: int
    method: BracketMethod
    censored_slots: int
    r95_gw: float
    slope_at_r95: float
    parameters: dict[str, float]


class EvaluationReport(BaseModel):
    """Comparison of all fitted models, and their censoring brackets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[FitResult]
    brackets: list[Bracket] = []


class SlotResidual(BaseModel):
    """One exact slot's residual ε_t, in £/MWh."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_start: datetime
    residual_gbp_per_mwh: float


class ResidualSeries(BaseModel):
    """A model's residuals over its training slots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    slots: list[SlotResidual]


def evaluate(
    fitted: FittedCurve,
    train_data: PriceDataset,
    test_data: PriceDataset,
    target: Target,
    charging: FleetCharging,
    *,
    model_name: str,
    curve_family: str,
    target_name: str,
    split: Split,
) -> FitResult:
    """Score ``fitted`` on ``test_data``, a single year.

    Level: e_t = π_t − to_price(h(R_t)), and RMSE = √(mean e_t²) over the
    exact slots, overall, by season and by hour.

    Slope: for consecutive exact slots t, t+1 half an hour apart,
    Δπ_t = π_{t+1} − π_t is compared with k_t·h′(R_t)·ΔR_t, where
    ΔR_t = R_{t+1} − R_t and k_t = 1 for raw targets.  It is computed as
    to_price(h′(R_t)·ΔR_t), since both targets are y times a factor.

    Fleet weighting: w_t = |n_t|, the fleet's net battery power in slot t
    from ``charging``, on the charging side when n_t > 0 and the
    discharging side when n_t < 0.  Each side reports
    √(Σ w_t·(Δπ_t − k_t·h′(R_t)·ΔR_t)² / Σ w_t) over the slope pairs, and
    the mean price slope Σ w_t·k_t·h′(R_t) / Σ w_t over every test slot,
    censored ones included: the slope needs no price.

    Censored slots: the mean censored log-likelihood ℓ/n over every
    test slot (the fitting objective of ``censored_log_likelihood``, with
    the fit's σ), and the hit rate, the share of censored slots with
    l_t ≤ h(R_t) ≤ u_t.  Every target is increasing in π, so that is the
    same as the predicted price lying in the slot's price bounds.

    ``train_data`` sets the range of R for the sanity checks.
    See ``docs/formulation.md``, Price curves, Evaluation.
    """
    years = test_data.years
    if len(years) != 1:
        raise ValueError(f"test_data must be a single year (got {years})")
    observations = sorted(test_data.observations, key=lambda o: o.settlement_start)
    exact = [o for o in observations if not o.censored]
    if not exact:
        raise ValueError(f"{years[0]} has no exact slots to score")

    errors = [
        _price(o) - target.to_price(fitted.predict(o.residual_load_gw), o)
        for o in exact
    ]
    by_season: dict[str, list[float]] = defaultdict(list)
    by_hour: dict[int, list[float]] = defaultdict(list)
    for obs, error in zip(exact, errors, strict=True):
        local = obs.settlement_start.astimezone(_LONDON)
        by_season[_SEASONS[local.month]].append(error)
        by_hour[local.hour].append(error)

    pairs: list[tuple[PriceObservation, float]] = []
    for a, b in itertools.pairwise(observations):
        if (
            a.censored
            or b.censored
            or b.settlement_start - a.settlement_start != _HALF_HOUR
        ):
            continue
        actual = _price(b) - _price(a)
        delta_r = b.residual_load_gw - a.residual_load_gw
        predicted = target.to_price(fitted.slope(a.residual_load_gw) * delta_r, a)
        pairs.append((a, actual - predicted))
    if not pairs:
        raise ValueError(
            f"{years[0]} has no consecutive exact slots for the slope check"
        )

    fitted_y = [fitted.predict(o.residual_load_gw) for o in observations]
    bounds = [target.to_target_bounds(o) for o in observations]
    lower = [b[0] for b in bounds]
    upper = [b[1] for b in bounds]
    log_likelihood = censored_log_likelihood(fitted_y, lower, upper, fitted.sigma)
    hits = [
        lo <= h <= hi
        for h, lo, hi, o in zip(fitted_y, lower, upper, observations, strict=True)
        if o.censored
    ]

    net = charging.by_slot()
    return FitResult(
        model_name=model_name,
        curve_family=curve_family,
        target_name=target_name,
        year=years[0],
        split=split,
        exact_slots=len(exact),
        censored_slots=len(hits),
        rmse_gbp_per_mwh=_rmse(errors),
        rmse_by_season_gbp_per_mwh={k: _rmse(v) for k, v in sorted(by_season.items())},
        rmse_by_hour_gbp_per_mwh={k: _rmse(v) for k, v in sorted(by_hour.items())},
        slope_pairs=len(pairs),
        slope_rmse_gbp_per_mwh=_rmse(e for _, e in pairs),
        charging=_weighted(fitted, target, observations, pairs, net, sign=1.0),
        discharging=_weighted(fitted, target, observations, pairs, net, sign=-1.0),
        sanity=_sanity(fitted, train_data),
        log_likelihood_per_slot=log_likelihood / len(observations),
        hit_rate=sum(hits) / len(hits) if hits else None,
    )


def bracket(
    family: PriceCurve,
    data: PriceDataset,
    target: Target,
    *,
    model_name: str,
    curve_family: str,
    target_name: str,
) -> list[Bracket]:
    """Fit ``family`` to ``data``, one year, three ways (see ``Bracket``).

    ``dropped`` fits the exact slots, ``lower_bound`` fits (Rₜ, lₜ) with
    every slot exact, and ``censored`` fits the bounds [lₜ, uₜ].  The
    slope is read at R95, the 95th percentile of the year's R, where
    most censored slots are.  See ``docs/formulation.md``, Price curves,
    Evaluation.
    """
    years = data.years
    if len(years) != 1:
        raise ValueError(f"data must be a single year (got {years})")
    loads = [o.residual_load_gw for o in data.observations]
    lower = [target.to_target_bounds(o)[0] for o in data.observations]
    upper = [target.to_target_bounds(o)[1] for o in data.observations]
    exact = [i for i, o in enumerate(data.observations) if not o.censored]
    fits: dict[BracketMethod, FittedCurve] = {
        "dropped": family.fit(
            [loads[i] for i in exact],
            [lower[i] for i in exact],
            [lower[i] for i in exact],
        ),
        "lower_bound": family.fit(loads, lower, lower),
        "censored": family.fit(loads, lower, upper),
    }
    r95 = float(np.percentile(loads, 95))
    return [
        Bracket(
            model_name=model_name,
            curve_family=curve_family,
            target_name=target_name,
            year=years[0],
            method=method,
            censored_slots=len(loads) - len(exact),
            r95_gw=r95,
            slope_at_r95=fitted.slope(r95),
            parameters=_parameters(fitted),
        )
        for method, fitted in fits.items()
    ]


def residuals(
    fitted: FittedCurve, data: PriceDataset, target: Target
) -> list[SlotResidual]:
    """ε_t = π_t − to_price(h(R_t)) for each exact slot of ``data``.

    For the fuel-adjusted target that is π_t − k_t·h(R_t).  A censored
    slot has no exact π_t, so it has no residual.
    See ``docs/formulation.md``, Price curves, Evaluation.
    """
    return [
        SlotResidual(
            settlement_start=o.settlement_start,
            residual_gbp_per_mwh=_price(o)
            - target.to_price(fitted.predict(o.residual_load_gw), o),
        )
        for o in data.observations
        if not o.censored
    ]


def comparison_table(report: EvaluationReport) -> str:
    """The report as Markdown: one row per model and year, then the spreads.

    The spread is, for each target and year, the largest minus the
    smallest fleet-weighted mean slope across families: how much the
    families disagree where batteries operate.  RMSE by hour stays in
    the saved report.
    """
    lines = [
        "## Fit by year",
        "",
        (
            "RMSEs in £/MWh over exact slots; slopes in £/MWh per GW, weighted "
            "by the fleet's battery power; min slope in target units per GW "
            "over the training range of R (⚠ when negative).  Log-lik/slot is "
            "the censored log-likelihood per slot, in target units: compare it "
            "between families of one target only.  Hit rate is the share of "
            "censored slots whose prediction lies within their bounds."
        ),
        "",
        (
            "| Model | Year | Split | RMSE (exact) | DJF | MAM | JJA | SON "
            "| Slope RMSE | Charging slope RMSE | Discharging slope RMSE "
            "| Charging slope | Discharging slope | Min slope "
            "| Censored | Log-lik/slot | Hit rate |"
        ),
        "| --- | ---: | --- |" + " ---: |" * 14,
    ]
    for r in report.results:
        seasons = [
            _cell(r.rmse_by_season_gbp_per_mwh.get(s))
            for s in ("DJF", "MAM", "JJA", "SON")
        ]
        flag = " ⚠" if r.sanity.min_slope < 0.0 else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    r.model_name,
                    str(r.year),
                    r.split,
                    _cell(r.rmse_gbp_per_mwh),
                    *seasons,
                    _cell(r.slope_rmse_gbp_per_mwh),
                    _cell(r.charging.slope_rmse_gbp_per_mwh),
                    _cell(r.discharging.slope_rmse_gbp_per_mwh),
                    _cell(r.charging.mean_slope_gbp_per_mwh_per_gw),
                    _cell(r.discharging.mean_slope_gbp_per_mwh_per_gw),
                    f"{r.sanity.min_slope:.4g}{flag}",
                    str(r.censored_slots),
                    _cell(r.log_likelihood_per_slot),
                    _cell(r.hit_rate),
                ]
            )
            + " |"
        )

    lines += [
        "",
        "## Slope spread between families, where the fleet operates",
        "",
        "Largest minus smallest weighted mean slope across families, £/MWh per GW.",
        "",
        "| Target | Year | Charging spread | Discharging spread |",
        "| --- | ---: | ---: | ---: |",
    ]
    groups: dict[tuple[str, int], list[FitResult]] = defaultdict(list)
    for r in report.results:
        groups[(r.target_name, r.year)].append(r)
    for (target_name, year), results in groups.items():
        charging = _spread(r.charging.mean_slope_gbp_per_mwh_per_gw for r in results)
        discharging = _spread(
            r.discharging.mean_slope_gbp_per_mwh_per_gw for r in results
        )
        lines.append(
            f"| {target_name} | {year} | {_cell(charging)} | {_cell(discharging)} |"
        )
    lines += _bracket_tables(report.brackets)
    return "\n".join(lines) + "\n"


def _bracket_tables(brackets: list[Bracket]) -> list[str]:
    """2021 alone, then the other years: slope at R95 and parameters."""
    if not brackets:
        return []
    lines = [
        "",
        "## Censoring brackets",
        "",
        (
            "Each year fitted alone, three ways: censored slots dropped, set to "
            "their lower bound, or used as bounds.  Slope h′ at the year's 95th "
            "percentile of R, in target units per GW."
        ),
    ]
    for title, rows in (
        ("2021", [b for b in brackets if b.year == 2021]),
        ("Other years", [b for b in brackets if b.year != 2021]),
    ):
        if not rows:
            continue
        lines += [
            "",
            f"### {title}",
            "",
            "| Model | Year | Censored | Method | R95 (GW) | Slope at R95 | Parameters |",
            "| --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
        for b in rows:
            parameters = ", ".join(f"{k}={v:.4g}" for k, v in b.parameters.items())
            lines.append(
                f"| {b.model_name} | {b.year} | {b.censored_slots} | {b.method} "
                f"| {b.r95_gw:.3g} | {b.slope_at_r95:.4g} | {parameters} |"
            )
    return lines


def _price(obs: PriceObservation) -> float:
    return obs.wholesale_price_gbp_per_mwh


def _rmse(errors: Iterable[float]) -> float:
    values = np.fromiter(errors, dtype=np.float64)
    return math.sqrt(float(np.mean(values**2)))


def _weighted(
    fitted: FittedCurve,
    target: Target,
    observations: list[PriceObservation],
    pairs: list[tuple[PriceObservation, float]],
    net: dict[datetime, float],
    *,
    sign: float,
) -> WeightedSlope:
    """Weighted slope RMSE and mean price slope on one side (``sign`` ±1)."""

    def weight(obs: PriceObservation) -> float:
        return max(sign * net.get(obs.settlement_start, 0.0), 0.0)

    weights = [weight(o) for o in observations]
    total = sum(weights)
    pair_weights = [weight(a) for a, _ in pairs]
    pair_total = sum(pair_weights)
    if total == 0.0:
        return WeightedSlope(
            weight_kw=0.0,
            slope_rmse_gbp_per_mwh=None,
            mean_slope_gbp_per_mwh_per_gw=None,
        )
    slopes = [
        target.to_price(fitted.slope(o.residual_load_gw), o) for o in observations
    ]
    mean_slope = sum(w * s for w, s in zip(weights, slopes, strict=True)) / total
    slope_rmse = None
    if pair_total > 0.0:
        weighted_sq = sum(
            w * e**2 for w, (_, e) in zip(pair_weights, pairs, strict=True)
        )
        slope_rmse = math.sqrt(weighted_sq / pair_total)
    return WeightedSlope(
        weight_kw=total,
        slope_rmse_gbp_per_mwh=slope_rmse,
        mean_slope_gbp_per_mwh_per_gw=mean_slope,
    )


def _parameters(fitted: FittedCurve) -> dict[str, float]:
    """The fit's scalar fields; every fit model is a pydantic model."""
    if not isinstance(fitted, BaseModel):
        raise TypeError(f"expected a fit model, got {type(fitted).__name__}")
    return {k: v for k, v in fitted.model_dump().items() if isinstance(v, float)}


def _sanity(fitted: FittedCurve, train_data: PriceDataset) -> SlopeSanity:
    loads = [o.residual_load_gw for o in train_data.observations]
    r_min, r_max = min(loads), max(loads)
    grid = np.linspace(r_min, r_max, _GRID_POINTS)
    return SlopeSanity(
        r_min_gw=r_min,
        r_max_gw=r_max,
        min_slope=min(fitted.slope(float(r)) for r in grid),
        value_at_r_min=fitted.predict(r_min),
        slope_at_r_min=fitted.slope(r_min),
        value_at_r_max=fitted.predict(r_max),
        slope_at_r_max=fitted.slope(r_max),
    )


def _spread(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) - min(present) if present else None


def _cell(value: float | None) -> str:
    return "–" if value is None else f"{value:.4g}"
