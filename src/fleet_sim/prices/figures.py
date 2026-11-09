"""Comparison and diagnostic figures for the price-curve pipeline.

The evaluation figures read a saved ``EvaluationReport`` (see
``load_evaluation``): level error, fleet-weighted slope, censored hit
rate and the censoring brackets.  ``plot_price_vs_residual`` is still a
stub.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from fleet_sim.prices.curves import FAMILIES, FittedCurve
from fleet_sim.prices.dataset import PriceDataset
from fleet_sim.prices.evaluation import (
    Bracket,
    BracketMethod,
    EvaluationReport,
    FitResult,
    WeightedSlope,
)
from fleet_sim.prices.targets import Target
from fleet_sim.stubs import stub
from fleet_sim.viz.style import (
    CHARGING,
    DISCHARGING,
    EVALUATION_FIGURE_INCHES,
    FAMILY_COLOURS,
    GRIDLINE,
    INK,
    LINE_WIDTH,
    PAPER,
    PRICE_CURVE_FIGURE_INCHES,
    apply_style,
    style_axes,
    watermark_stub,
)

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


@stub("placeholder scatter — replace in issue #72")
def plot_price_vs_residual(
    dataset: PriceDataset,
    fitted: FittedCurve,
    target: Target,
    *,
    title: str = "Price vs residual load",
) -> Figure:
    """Scatter of target value against residual load with fitted curve.

    Stub: empty axes with a STUB watermark.
    """
    _ = dataset, fitted, target
    apply_style()
    fig, ax = plt.subplots(figsize=PRICE_CURVE_FIGURE_INCHES)
    style_axes(ax)
    ax.set_xlabel("Residual load (GW)")
    ax.set_ylabel("Price (£/MWh)")
    ax.set_title(title)
    watermark_stub(fig)
    plt.close(fig)
    return fig


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


def _finish(figure: Figure) -> Figure:
    """Lay out the panels, leaving room for a legend along the bottom."""
    figure.tight_layout(rect=(0.0, 0.08, 1.0, 1.0))
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
