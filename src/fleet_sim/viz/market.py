"""Fleet-in-the-loop figures, drawn from a run's saved ``metrics.json``.

Figure 1: national added load over the day, per million batteries, at M = 0
(the herd at historical prices) and at each M.
Figure 2: saving per battery home against M, one line per price model.
Figure 3: share of transformers overloaded against local penetration, one
line per M, one panel per allocation and ρ.

Figures 1 and 2 are at the headline point (the first ρ and the highest local
penetration); figures 1 and 3 use the main price model.
"""

import json
from pathlib import Path

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.models.results import (
    ConfidenceInterval,
    MarketLevelResult,
    MarketSweep,
    MetricEstimate,
)
from fleet_sim.viz.style import (
    BAND_ALPHA,
    FAMILY_COLOURS,
    IMPORT_WITHOUT_BATTERY,
    LINE_WIDTH,
    MARKET_FIGURE_INCHES,
    NATIONAL_FLEET_COLOURMAP,
    OVERLOAD_GRID_FIGURE_INCHES,
    apply_style,
    style_axes,
)

_SAVING = "saving_per_battery_home_p_per_day"
_OVERLOADED = "transformers_overloaded_share"
_HOURS_PER_SLOT = 0.5
_ALLOCATIONS = (
    ("joint", "Solver picks who charges"),
    ("replanned", "Each home plans alone"),
)
_MODEL_LABELS = {
    "fuel_adjusted/exponential": "Main price curve",
    "fuel_adjusted/signed_quadratic": "Steeper evening (quadratic)",
    "fuel_adjusted/cubic": "Steepest evening (cubic)",
}
_SPREAD = {0.0: "batteries spread evenly", 0.8: "batteries clustered"}


def read_market_sweep(path: Path) -> MarketSweep:
    """The ``market`` entry of a market run's ``metrics.json``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "market" not in payload:
        raise ValueError(f"{path} has no market results")
    return MarketSweep.model_validate(payload["market"])


def plot_added_load(sweep: MarketSweep) -> Figure:
    """Net power per battery home over the day, at each M.

    For M > 0 this is the mean b*_t divided by M / 10⁶, the national added
    load per million batteries in GW. At M = 0 it is the same measure for
    the herd at historical prices, so a flatter line at larger M shows
    feedback spreading the herd.
    """
    levels = _headline(sweep, sweep.price_model)
    apply_style()
    figure = Figure(figsize=MARKET_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    colours = _fleet_colours([level.national_batteries for level in levels])
    for level in levels:
        profile = level.net_power_per_battery_home_kw
        hours = [slot * _HOURS_PER_SLOT for slot in range(len(profile))]
        if level.national_batteries == 0:
            ax.plot(
                hours,
                profile,
                color=IMPORT_WITHOUT_BATTERY,
                linewidth=LINE_WIDTH,
                linestyle="--",
                label="Prices ignore batteries (the herd)",
            )
        else:
            ax.plot(
                hours,
                profile,
                color=colours[level.national_batteries],
                linewidth=LINE_WIDTH,
                label=_fleet_label(level.national_batteries),
            )
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Added load per million\nbatteries (GW)")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


def plot_saving_by_model(sweep: MarketSweep) -> Figure:
    """Saving per battery home against M, with intervals, per price model."""
    models = [sweep.price_model, *sweep.robustness_models]
    apply_style()
    figure = Figure(figsize=MARKET_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    for index, model in enumerate(models):
        levels = _headline(sweep, model)
        colour = FAMILY_COLOURS[index % len(FAMILY_COLOURS)]
        xs = [level.national_batteries / 1e6 for level in levels]
        bands = [_interval(level.market, _SAVING) for level in levels]
        ax.fill_between(
            xs,
            [band.low for band in bands],
            [band.high for band in bands],
            color=colour,
            alpha=BAND_ALPHA,
            linewidth=0,
        )
        ax.plot(
            xs,
            [band.mean for band in bands],
            color=colour,
            linewidth=LINE_WIDTH,
            marker="o",
            label=_MODEL_LABELS.get(model, model),
        )
    ax.set_xlabel("Batteries in Britain (millions)")
    ax.set_ylabel("Saving per battery\nhome (p/day)")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


def plot_overload_by_penetration(sweep: MarketSweep) -> Figure:
    """Share of transformers overloaded against local penetration.

    One row per ρ and one column per allocation, one line per M, under the
    main price model.
    """
    levels = [level for level in sweep.levels if level.price_model == sweep.price_model]
    rhos = sorted({level.rho for level in levels})
    fleets = sorted({level.national_batteries for level in levels})
    colours = _fleet_colours(fleets)
    apply_style()
    figure = Figure(figsize=OVERLOAD_GRID_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    axes = figure.subplots(len(rhos), len(_ALLOCATIONS), sharex=True, sharey=True)
    for row, rho in enumerate(rhos):
        for column, (allocation, title) in enumerate(_ALLOCATIONS):
            ax = axes[row][column] if len(rhos) > 1 else axes[column]
            for m in fleets:
                line = sorted(
                    (
                        level
                        for level in levels
                        if level.rho == rho and level.national_batteries == m
                    ),
                    key=lambda level: level.penetration,
                )
                xs = [100.0 * level.penetration for level in line]
                bands = [
                    _interval(_overload(level, allocation), _OVERLOADED)
                    for level in line
                ]
                colour = IMPORT_WITHOUT_BATTERY if m == 0 else colours[m]
                ax.fill_between(
                    xs,
                    [band.low for band in bands],
                    [band.high for band in bands],
                    color=colour,
                    alpha=BAND_ALPHA,
                    linewidth=0,
                )
                ax.plot(
                    xs,
                    [band.mean for band in bands],
                    color=colour,
                    linewidth=LINE_WIDTH,
                    marker="o",
                    label=_fleet_label(m),
                )
            ax.set_title(f"{title}, {_SPREAD.get(rho, f'ρ = {rho:g}')}")
            if row == len(rhos) - 1:
                ax.set_xlabel("Homes with a battery (%)")
            if column == 0:
                ax.set_ylabel("Share of transformers\noverloaded")
            style_axes(ax)
    # One legend under the grid: inside any panel it would cover lines.
    first = axes[0][0] if len(rhos) > 1 else axes[0]
    handles, labels = first.get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=3)
    figure.tight_layout(rect=(0, 0.1, 1, 1))
    return figure


def _headline(sweep: MarketSweep, model: str) -> list[MarketLevelResult]:
    """``model``'s levels at the headline point, in order of M."""
    levels = [
        level
        for level in sweep.levels
        if level.price_model == model
        and level.rho == sweep.headline_rho
        and level.penetration == sweep.headline_penetration
    ]
    if not levels:
        raise ValueError(f"no headline results for {model}")
    return sorted(levels, key=lambda level: level.national_batteries)


def _overload(level: MarketLevelResult, allocation: str) -> list[MetricEstimate]:
    return level.joint_overload if allocation == "joint" else level.replanned_overload


def _interval(estimates: list[MetricEstimate], name: str) -> ConfidenceInterval:
    for estimate in estimates:
        if estimate.metric == name:
            return estimate.interval
    raise ValueError(f"no metric named {name}")


def _fleet_colours(fleets: list[float]) -> dict[float, str]:
    """Steps of one sequential colour map for M > 0, darker for larger M."""
    positive = sorted(m for m in fleets if m > 0)
    colourmap = mpl.colormaps[NATIONAL_FLEET_COLOURMAP]
    count = len(positive)
    return {
        m: mpl.colors.to_hex(colourmap(0.45 + 0.5 * i / max(count - 1, 1)))
        for i, m in enumerate(positive)
    }


def _fleet_label(national_batteries: float) -> str:
    if national_batteries == 0:
        return "Prices ignore batteries"
    return f"{national_batteries / 1e6:g} million batteries in Britain"
