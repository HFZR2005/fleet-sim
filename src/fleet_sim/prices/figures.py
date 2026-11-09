"""Figures for the price-curve pipeline.

The evaluation figures read a saved ``EvaluationReport`` (see
``load_evaluation``): level error, fleet-weighted slope, censored hit
rate and the censoring brackets.  The others take the dataset and the
fitted curves: why adjust for fuel cost, the fits, their slopes where
the fleet operates, residuals, and what anchoring does to one day.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib as mpl
import numpy as np
import numpy.typing as npt
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from fleet_sim.prices.curves import FAMILIES, FittedCurve
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.evaluation import (
    Bracket,
    BracketMethod,
    EvaluationReport,
    FitResult,
    SlotResidual,
    WeightedSlope,
)
from fleet_sim.prices.fleet_weights import FleetCharging
from fleet_sim.prices.response import price_response
from fleet_sim.prices.targets import TARGETS, Target
from fleet_sim.viz.style import (
    BAND_ALPHA,
    CHARGING,
    DISCHARGING,
    EVALUATION_FIGURE_INCHES,
    FAMILY_COLOURS,
    GRIDLINE,
    INK,
    LIMIT_LINE,
    LINE_WIDTH,
    PAPER,
    PRICE_CURVE_FIGURE_INCHES,
    YEAR_COLOURMAP,
    apply_style,
    style_axes,
)

_Array = npt.NDArray[np.float64]
_LONDON = ZoneInfo("Europe/London")
_BIN_WIDTH = 1.0
_MIN_BIN_POINTS = 30
_GRID_POINTS = 200
_SLOPE_CLIP_PERCENTILE = 98
# The pooled targets, whose single curve over all years can be drawn.
_CURVE_TARGETS = ("raw_pooled", "fuel_adjusted")
_Y_LABELS = {"raw_pooled": "π (£/MWh)", "fuel_adjusted": "π / k"}
_SLOPE_UNITS = {"raw_pooled": "£/MWh per GW", "fuel_adjusted": "per GW"}
_GAS_CRISIS_YEAR = 2022
_GROUP_WIDTH = 0.8
_METHOD_MARKERS: dict[BracketMethod, tuple[str, str]] = {
    # method: (marker, face colour; "none" is hollow)
    "dropped": ("o", "none"),
    "lower_bound": ("v", "fill"),
    "censored": ("o", "fill"),
}


def load_evaluation(path: Path) -> EvaluationReport:
    """The report saved by ``scripts/fit_price_curves.py compare``."""
    return EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))


def plot_fuel_adjustment(dataset: PriceDataset) -> Figure:
    """π against R by year, next to π / k against R by year.

    Each year is the median of its exact slots in 1 GW bins of R, with
    the interquartile band.  Dividing by the fuel cost k should collapse
    the years' bands onto one curve.
    """
    years = dataset.years
    figure, axes = _panels(2, sharey=False)
    for year, colour in zip(years, _year_colours(len(years)), strict=True):
        rows = [o for o in _exact(dataset) if o.year == year]
        for ax, target_name in zip(axes, _CURVE_TARGETS, strict=True):
            r, y = _target_values(rows, target_name)
            _band(ax, _binned(r, y), colour, label=str(year))
    for ax, target_name in zip(axes, _CURVE_TARGETS, strict=True):
        ax.set_xlabel("Residual load R (GW)")
        ax.set_ylabel(_Y_LABELS[target_name])
    handles, _ = axes[0].get_legend_handles_labels()
    figure.legend(handles=handles, loc="lower center", ncols=len(handles))
    return _finish(figure)


def plot_fits(dataset: PriceDataset, fits: dict[str, dict[str, FittedCurve]]) -> Figure:
    """Each family's curve h(R) over binned medians, one panel per target.

    ``fits`` maps target name to family to the curve fitted on
    ``dataset``.  Medians are over exact slots in 1 GW bins, so they sit
    low where many slots are censored, at high R.
    """
    figure, axes = _panels(len(fits), sharey=False)
    for ax, (target_name, curves) in zip(axes, fits.items(), strict=True):
        r, y = _target_values(_exact(dataset), target_name)
        centres, _, medians, _ = _binned(r, y)
        ax.plot(centres, medians, "o", color=LIMIT_LINE, label="Binned median")
        grid = _grid(dataset)
        for family, fitted in curves.items():
            ax.plot(
                grid,
                [fitted.predict(x) for x in grid],
                color=_family_colour(family),
                linewidth=LINE_WIDTH,
                label=family,
            )
        ax.set_title(target_name)
        ax.set_xlabel("Residual load R (GW)")
        ax.set_ylabel(_Y_LABELS[target_name])
    handles, _ = axes[0].get_legend_handles_labels()
    figure.legend(handles=handles, loc="lower center", ncols=len(handles))
    return _finish(figure)


def plot_slopes(
    dataset: PriceDataset,
    fits: dict[str, dict[str, FittedCurve]],
    charging: FleetCharging,
) -> Figure:
    """h′(R) for each family, over where the fleet charges and discharges.

    Shaded behind the curves is the distribution of R over ``dataset``'s
    slots weighted by the fleet's net battery power |nₜ|, charging
    (nₜ > 0) and discharging (nₜ < 0) separately, as in the evaluation.
    It is scaled to the panel's height: it shows where, not how much.
    The y-axis stops at the 98th percentile of the plotted slopes, so the
    isotonic curve's spikes are cut off rather than flattening the rest.
    """
    net = charging.by_slot()
    loads = np.array([o.residual_load_gw for o in dataset.observations])
    power = np.array([net.get(o.settlement_start, 0.0) for o in dataset.observations])
    edges = _edges(loads)
    figure, axes = _panels(len(fits), sharey=False)
    for ax, (target_name, curves) in zip(axes, fits.items(), strict=True):
        grid = _grid(dataset)
        slopes = {f: [c.slope(x) for x in grid] for f, c in curves.items()}
        for family, values in slopes.items():
            ax.plot(
                grid,
                values,
                color=_family_colour(family),
                linewidth=LINE_WIDTH,
                label=family,
            )
        every = np.concatenate(list(slopes.values()))
        bottom = min(0.0, float(every.min()))
        top = 1.05 * float(np.percentile(every, _SLOPE_CLIP_PERCENTILE))
        histograms = [
            np.histogram(loads, edges, weights=np.clip(sign * power, 0.0, None))[0]
            for sign in (1.0, -1.0)
        ]
        scale = top / max(h.max() for h in histograms)
        for counts, colour, label in zip(
            histograms, (CHARGING, DISCHARGING), ("Fleet charging", "Fleet discharging")
        ):
            ax.stairs(
                counts * scale,
                edges,
                baseline=0.0,
                fill=True,
                color=colour,
                alpha=BAND_ALPHA,
                zorder=0,
                label=label,
            )
        ax.set_ylim(bottom, top)
        ax.set_title(target_name)
        ax.set_xlabel("Residual load R (GW)")
        ax.set_ylabel(f"h′(R) ({_SLOPE_UNITS[target_name]})")
    handles, _ = axes[0].get_legend_handles_labels()
    figure.legend(handles=handles, loc="lower center", ncols=4)
    return _finish(figure, legend_rows=2)


def plot_residuals(
    dataset: PriceDataset, residuals: dict[str, list[SlotResidual]]
) -> Figure:
    """εₜ against R and against hour of day (UK), for each model.

    ``residuals`` maps model name to its slots' residuals, from
    ``evaluation.residuals``.  Each line is the median in 1 GW or 1 hour
    bins, with the interquartile band.
    """
    load = {o.settlement_start: o.residual_load_gw for o in dataset.observations}
    figure, axes = _panels(2, sharey=True)
    for colour, (model_name, slots) in zip(FAMILY_COLOURS, residuals.items()):
        eps = np.array([s.residual_gbp_per_mwh for s in slots])
        r = np.array([load[s.settlement_start] for s in slots])
        hour = np.array(
            [s.settlement_start.astimezone(_LONDON).hour for s in slots], dtype=float
        )
        _band(axes[0], _binned(r, eps), colour, label=model_name)
        _band(axes[1], _binned(hour, eps), colour, label=model_name)
    for ax in axes:
        ax.axhline(0.0, color=INK, linewidth=0.8)
    axes[0].set_xlabel("Residual load R (GW)")
    axes[1].set_xlabel("Hour of day (UK)")
    axes[1].set_xticks(range(0, 25, 6))
    axes[0].set_ylabel("Residual ε (£/MWh)")
    handles, _ = axes[0].get_legend_handles_labels()
    figure.legend(handles=handles, loc="lower center", ncols=len(handles))
    return _finish(figure)


def plot_anchoring(
    day: PriceDataset,
    curves: dict[str, FittedCurve],
    target: Target,
    added_load_gw: list[float],
    *,
    region: str,
) -> Figure:
    """One day's historical Agile rate against its rate with added load.

    For each family, ``price_response`` moves each slot's price along
    that family's curve by ``added_load_gw``, keeping its residual.  The
    historical rate is ``price_response`` with no added load, which is
    the same for every family when no slot is censored.
    """
    if any(o.censored for o in day.observations):
        raise ValueError("the example day must have no censored slots")
    hours = [
        o.settlement_start.astimezone(_LONDON).hour
        + o.settlement_start.astimezone(_LONDON).minute / 60
        for o in day.observations
    ]
    apply_style()
    figure = Figure(figsize=PRICE_CURVE_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    style_axes(ax)
    for hour, added in zip(hours, added_load_gw, strict=True):
        if added:
            ax.axvspan(hour, hour + 0.5, color=GRIDLINE, linewidth=0, zorder=0)
    first = next(iter(curves.values()))
    zero = [0.0] * len(hours)
    historical = price_response(day, first, target, zero, region=region)
    ax.step(
        hours,
        historical.price_p_per_kwh,
        where="post",
        color=INK,
        linewidth=LINE_WIDTH,
        label="Historical",
    )
    for family, fitted in curves.items():
        moved = price_response(day, fitted, target, added_load_gw, region=region)
        ax.step(
            hours,
            moved.price_p_per_kwh,
            where="post",
            color=_family_colour(family),
            label=family,
        )
    ax.set_xticks(range(0, 25, 6))
    ax.set_xlabel("Hour of day (UK)")
    ax.set_ylabel("Agile import rate (p/kWh)")
    ax.set_title(f"{historical.day}, +{max(added_load_gw):g} GW in the shaded slots")
    ax.legend()
    figure.tight_layout()
    return figure


def plot_level_error(report: EvaluationReport) -> Figure:
    """RMSE over exact slots by year, one panel per target, bars by family.

    In-sample rows (a per-year target scored on the year it was fitted
    to) are drawn hollow and hatched: they are not out-of-sample errors.
    The gas-crisis year is shaded.
    """
    targets = _unique(r.target_name for r in report.results)
    years = sorted(_unique(r.year for r in report.results))
    figure, axes = _panels(len(targets), sharey=True)
    for ax, target_name in zip(axes, targets, strict=True):
        rows = [r for r in report.results if r.target_name == target_name]
        in_sample = _in_sample(rows)
        _shade_gas_crisis(ax, years)
        _grouped_bars(
            ax,
            years,
            {(r.curve_family, r.year): r.rmse_gbp_per_mwh for r in rows},
            hollow=in_sample,
        )
        _year_ticks(ax, years)
        ax.set_title(_split_title(target_name, in_sample))
    axes[0].set_ylabel("RMSE (£/MWh)")
    _family_legend(figure, report)
    return _finish(figure)


def plot_fleet_slopes(report: EvaluationReport) -> Figure:
    """Fleet-weighted mean price slope by family, charging vs discharging.

    Each year's mean slope s_y is weighted by its total fleet weight w_y
    (``weight_kw``), so the bar is Σ w_y·s_y / Σ w_y over the years: the
    same as one weighted mean over every slot.  See ``docs/formulation.md``,
    Price curves, Evaluation.
    """
    targets = _unique(r.target_name for r in report.results)
    families = _unique(r.curve_family for r in report.results)
    figure, axes = _panels(len(targets), sharey=True)
    width = _GROUP_WIDTH / 2
    for ax, target_name in zip(axes, targets, strict=True):
        rows = [r for r in report.results if r.target_name == target_name]
        charging: list[float | None] = []
        discharging: list[float | None] = []
        for family in families:
            years = [r for r in rows if r.curve_family == family]
            charging.append(_pooled_slope([r.charging for r in years]))
            discharging.append(_pooled_slope([r.discharging for r in years]))
        for offset, means, label, colour in (
            (-width / 2, charging, "Charging", CHARGING),
            (width / 2, discharging, "Discharging", DISCHARGING),
        ):
            points = [(i + offset, m) for i, m in enumerate(means) if m is not None]
            ax.bar(
                [x for x, _ in points],
                [m for _, m in points],
                width * 0.9,
                color=colour,
                label=label,
            )
        ax.set_xticks(range(len(families)), families, rotation=30, ha="right")
        ax.set_title(target_name)
    axes[0].set_ylabel("Mean slope (£/MWh per GW)")
    handles, _ = axes[0].get_legend_handles_labels()
    figure.legend(handles=handles, loc="lower center", ncols=len(handles))
    return _finish(figure)


def plot_hit_rate(report: EvaluationReport) -> Figure:
    """Share of censored slots predicted within their bounds, by year.

    Each year's tick shows its censored-slot count: a year with few
    censored slots has a hit rate that means little.  In-sample rows are
    drawn hollow, as in ``plot_level_error``.
    """
    targets = _unique(r.target_name for r in report.results)
    years = sorted(_unique(r.year for r in report.results))
    counts = {r.year: r.censored_slots for r in report.results}
    figure, axes = _panels(len(targets), sharey=True)
    for ax, target_name in zip(axes, targets, strict=True):
        rows = [r for r in report.results if r.target_name == target_name]
        _grouped_bars(
            ax,
            years,
            {(r.curve_family, r.year): r.hit_rate for r in rows},
            hollow=_in_sample(rows),
        )
        _year_ticks(ax, years, counts)
        ax.set_ylim(0.0, 1.0)
        ax.set_title(_split_title(target_name, _in_sample(rows)))
    axes[0].set_ylabel("Hit rate")
    _family_legend(figure, report)
    return _finish(figure)


def plot_r95_brackets(report: EvaluationReport) -> Figure:
    """Slope at R95 for each treatment of censored slots, by year and family.

    A vertical line joins a family's three fits in one year, so its length
    is how much the treatment of censored slots moves the slope.  Slopes
    are in target units per GW, so each target has its own axis.
    """
    if not report.brackets:
        raise ValueError("the report has no censoring brackets")
    targets = _unique(b.target_name for b in report.brackets)
    years = sorted(_unique(b.year for b in report.brackets))
    families = _unique(b.curve_family for b in report.brackets)
    counts = {b.year: b.censored_slots for b in report.brackets}
    figure, axes = _panels(len(targets), sharey=False)
    step = _GROUP_WIDTH / len(families)
    for ax, target_name in zip(axes, targets, strict=True):
        for j, family in enumerate(families):
            colour = _family_colour(family)
            for i, year in enumerate(years):
                fits = _bracket_fits(report.brackets, target_name, family, year)
                if not fits:
                    continue
                x = i - _GROUP_WIDTH / 2 + step * (j + 0.5)
                slopes = list(fits.values())
                ax.vlines(
                    x, min(slopes), max(slopes), color=colour, linewidth=LINE_WIDTH
                )
                for method, slope in fits.items():
                    marker, face = _METHOD_MARKERS[method]
                    ax.plot(
                        x,
                        slope,
                        marker=marker,
                        markerfacecolor=PAPER if face == "none" else colour,
                        markeredgecolor=colour,
                        linestyle="none",
                    )
        _year_ticks(ax, years, counts)
        ax.set_title(target_name)
        ax.set_ylabel("Slope at R95 (target units per GW)")
    axes[0].legend(
        handles=[
            Line2D(
                [],
                [],
                marker=marker,
                markerfacecolor=PAPER if face == "none" else INK,
                markeredgecolor=INK,
                linestyle="none",
                label=method,
            )
            for method, (marker, face) in _METHOD_MARKERS.items()
        ],
        loc="upper right",
    )
    _family_legend(figure, report)
    return _finish(figure)


EVALUATION_FIGURES: dict[str, Callable[[EvaluationReport], Figure]] = {
    "level_error": plot_level_error,
    "fleet_slopes": plot_fleet_slopes,
    "hit_rate": plot_hit_rate,
    "r95_brackets": plot_r95_brackets,
}


def _panels(count: int, *, sharey: bool) -> tuple[Figure, list[Axes]]:
    apply_style()
    figure = Figure(figsize=EVALUATION_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    axes = figure.subplots(1, count, sharey=sharey, squeeze=False)[0]
    for ax in axes:
        style_axes(ax)
    return figure, list(axes)


def _grouped_bars(
    ax: Axes,
    years: list[int],
    values: dict[tuple[str, int], float | None],
    *,
    hollow: bool,
) -> None:
    """One bar per family in each year; missing or None values are skipped."""
    families = _unique(family for family, _ in values)
    step = _GROUP_WIDTH / len(families)
    for j, family in enumerate(families):
        colour = _family_colour(family)
        points = [
            (i - _GROUP_WIDTH / 2 + step * (j + 0.5), value)
            for i, year in enumerate(years)
            if (value := values.get((family, year))) is not None
        ]
        ax.bar(
            [x for x, _ in points],
            [v for _, v in points],
            step * 0.9,
            color=PAPER if hollow else colour,
            edgecolor=colour,
            hatch="///" if hollow else None,
        )


def _year_ticks(
    ax: Axes, years: list[int], counts: dict[int, int] | None = None
) -> None:
    labels = [str(y) if counts is None else f"{y}\nn={counts[y]:,}" for y in years]
    ax.set_xticks(range(len(years)), labels, fontsize="small")


def _shade_gas_crisis(ax: Axes, years: list[int]) -> None:
    if _GAS_CRISIS_YEAR not in years:
        return
    i = years.index(_GAS_CRISIS_YEAR)
    ax.axvspan(i - 0.5, i + 0.5, color=GRIDLINE, zorder=0)
    ax.text(
        i, 0.98, "gas crisis", transform=ax.get_xaxis_transform(),
        ha="center", va="top", fontsize="small",
    )  # fmt: skip


def _in_sample(rows: list[FitResult]) -> bool:
    return all(r.split == "in-sample" for r in rows)


def _split_title(target_name: str, in_sample: bool) -> str:
    return f"{target_name}, {'in-sample' if in_sample else 'held-out'}"


def _family_legend(figure: Figure, report: EvaluationReport) -> None:
    families = _unique(r.curve_family for r in report.results)
    figure.legend(
        handles=[
            Line2D([], [], color=_family_colour(f), linewidth=6, label=f)
            for f in families
        ],
        loc="lower center",
        ncols=len(families),
    )


def _finish(figure: Figure, *, legend_rows: int = 1) -> Figure:
    """Lay out the panels, leaving room for a legend along the bottom."""
    figure.tight_layout(rect=(0.0, 0.08 * legend_rows, 1.0, 1.0))
    return figure


def _pooled_slope(sides: list[WeightedSlope]) -> float | None:
    """Σ w_y·s_y / Σ w_y over years with a slope; None with no weight."""
    present = [
        (s.weight_kw, s.mean_slope_gbp_per_mwh_per_gw)
        for s in sides
        if s.mean_slope_gbp_per_mwh_per_gw is not None
    ]
    total = sum(w for w, _ in present)
    if total == 0.0:
        return None
    return sum(w * s for w, s in present) / total


def _bracket_fits(
    brackets: list[Bracket], target_name: str, family: str, year: int
) -> dict[BracketMethod, float]:
    return {
        b.method: b.slope_at_r95
        for b in brackets
        if b.target_name == target_name and b.curve_family == family and b.year == year
    }


def _family_colour(family: str) -> str:
    return FAMILY_COLOURS[list(FAMILIES).index(family)]


def _unique[T](values: Iterable[T]) -> list[T]:
    """Values in order of first appearance."""
    return list(dict.fromkeys(values))


def _exact(dataset: PriceDataset) -> list[PriceObservation]:
    return [o for o in dataset.observations if not o.censored]


def _target_values(
    rows: Sequence[PriceObservation], target_name: str
) -> tuple[_Array, _Array]:
    """R and the target value y for each of ``rows``."""
    target = TARGETS[target_name]
    return (
        np.array([o.residual_load_gw for o in rows]),
        np.array([target.to_target(o) for o in rows]),
    )


def _edges(x: _Array) -> _Array:
    return np.arange(np.floor(x.min()), np.ceil(x.max()) + _BIN_WIDTH, _BIN_WIDTH)


def _binned(x: _Array, y: _Array) -> _Array:
    """Rows of (bin centre, q25, median, q75) of y in unit-wide bins of x.

    Bins with fewer than ``_MIN_BIN_POINTS`` points are left out.
    """
    edges = _edges(x)
    index = np.digitize(x, edges) - 1
    rows = [
        [(edges[b] + edges[b + 1]) / 2, *np.percentile(y[index == b], [25, 50, 75])]
        for b in range(len(edges) - 1)
        if np.count_nonzero(index == b) >= _MIN_BIN_POINTS
    ]
    return np.array(rows, dtype=np.float64).reshape(-1, 4).T


def _band(ax: Axes, binned: _Array, colour: str, *, label: str) -> None:
    centres, low, median, high = binned
    ax.fill_between(centres, low, high, color=colour, alpha=BAND_ALPHA, linewidth=0)
    ax.plot(centres, median, color=colour, linewidth=LINE_WIDTH, label=label)


def _grid(dataset: PriceDataset) -> _Array:
    loads = [o.residual_load_gw for o in dataset.observations]
    return np.linspace(min(loads), max(loads), _GRID_POINTS)


def _year_colours(count: int) -> list[str]:
    """Light to dark steps of one hue, so later years are darker."""
    cmap = mpl.colormaps[YEAR_COLOURMAP]
    return [to_hex(cmap(x)) for x in np.linspace(0.4, 1.0, count)]
