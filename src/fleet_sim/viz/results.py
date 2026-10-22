"""Penetration and diversity figures, drawn from saved results.

Neither figure solves a schedule or reads a price feed. The readers load
the JSON written by ``scripts/run_milestone3.py``.
"""

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.viz.style import (
    BAND_ALPHA,
    DIVERSE,
    DIVERSITY_FIGURE_INCHES,
    FONT_SIZE,
    IDENTICAL,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    INK,
    LINE_WIDTH,
    PENETRATION_FIGURE_INCHES,
    apply_style,
    style_axes,
)

_HOURS_PER_SLOT = 0.5


def read_penetration_curve(
    path: Path,
) -> tuple[
    list[float], list[tuple[float, float, float]], list[tuple[float, float, float]]
]:
    """Penetrations, with-battery peaks, and without-battery peaks."""
    payload = _object(json.loads(path.read_text(encoding="utf-8")), "results")
    levels = _list(_object(payload.get("sweep"), "sweep").get("levels"), "levels")
    penetrations: list[float] = []
    with_battery: list[tuple[float, float, float]] = []
    without_battery: list[tuple[float, float, float]] = []
    for index, level in enumerate(levels):
        row = _object(level, f"levels[{index}]")
        penetrations.append(
            _number(row.get("penetration"), f"levels[{index}].penetration")
        )
        with_battery.append(_metric_band(row, "peak_demand_kw"))
        without_battery.append(
            _band(row.get("peak_without_battery"), "peak_without_battery")
        )
    return penetrations, with_battery, without_battery


def read_diversity_day(
    path: Path,
) -> tuple[list[float], list[float], date, tuple[float, float, float]]:
    """Diverse import, identical import, the day, and the peak-difference interval."""
    payload = _object(json.loads(path.read_text(encoding="utf-8")), "results")
    day_row = _object(payload.get("representative_day"), "representative_day")
    difference = _diversity_peak(payload)
    return (
        _numbers(day_row.get("diverse_import_kw"), "diverse_import_kw"),
        _numbers(day_row.get("identical_import_kw"), "identical_import_kw"),
        date.fromisoformat(_string(day_row.get("day"), "day")),
        difference,
    )


def plot_penetration_curve(
    penetrations: Sequence[float],
    with_battery: Sequence[tuple[float, float, float]],
    without_battery: Sequence[tuple[float, float, float]],
) -> Figure:
    """Peak demand against penetration, with a 95% band on each series.

    Each triple is ``(mean, low, high)`` in kW, one per penetration.
    """
    _require_same_length("penetrations", penetrations, "with_battery", with_battery)
    _require_same_length(
        "penetrations", penetrations, "without_battery", without_battery
    )
    if not penetrations:
        raise ValueError("a figure needs at least one penetration")
    apply_style()
    figure = Figure(figsize=PENETRATION_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    xs = [100.0 * penetration for penetration in penetrations]
    _draw_band(ax, xs, without_battery, IMPORT_WITHOUT_BATTERY, "Without batteries")
    _draw_band(ax, xs, with_battery, IMPORT_WITH_BATTERY, "With batteries")
    ax.set_xlabel("Penetration (%)")
    ax.set_ylabel("Peak demand (kW)")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


def plot_diversity_day(
    diverse_kw: Sequence[float],
    identical_kw: Sequence[float],
    *,
    day: date,
    peak_difference_kw: tuple[float, float, float],
) -> Figure:
    """Identical and diverse fleet import over one day.

    ``peak_difference_kw`` is diverse minus identical, as ``(mean, low, high)``
    from the replications. It is annotated, not computed from these two series.
    """
    if len(diverse_kw) != len(identical_kw):
        raise ValueError(
            "diverse and identical must have one value per slot "
            f"(got {len(diverse_kw)} and {len(identical_kw)})"
        )
    if not diverse_kw:
        raise ValueError("a figure needs at least one slot")
    apply_style()
    figure = Figure(figsize=DIVERSITY_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    edges = [_HOURS_PER_SLOT * slot for slot in range(len(diverse_kw) + 1)]
    ax.stairs(
        list(identical_kw),
        edges,
        baseline=None,
        color=IDENTICAL,
        linewidth=LINE_WIDTH,
        label="Identical",
    )
    ax.stairs(
        list(diverse_kw),
        edges,
        baseline=None,
        color=DIVERSE,
        linewidth=LINE_WIDTH,
        label="Diverse",
    )
    mean, low, high = peak_difference_kw
    ax.annotate(
        f"{day.day} {day.strftime('%B %Y')}\n"
        f"Mean peak difference {mean:.2f} kW\n"
        f"({low:.2f} to {high:.2f})",
        xy=(0.33, 0.98),
        xycoords="axes fraction",
        va="top",
        ha="left",
        color=INK,
        fontsize=FONT_SIZE,
    )
    ax.set_ylabel("Grid import (kW)")
    ax.set_xlabel("Time (h)")
    ax.legend(loc="upper left", bbox_to_anchor=(0.33, 0.70))
    style_axes(ax)
    figure.tight_layout()
    return figure


def _metric_band(level: dict[str, object], metric: str) -> tuple[float, float, float]:
    metrics = _list(level.get("metrics"), "metrics")
    for index, item in enumerate(metrics):
        row = _object(item, f"metrics[{index}]")
        if row.get("metric") == metric:
            return _band(row.get("interval"), metric)
    raise ValueError(f"saved results have no {metric}")


def _diversity_peak(payload: dict[str, object]) -> tuple[float, float, float]:
    rows = _list(
        _object(payload.get("diversity"), "diversity").get("diversity"), "diversity"
    )
    for index, item in enumerate(rows):
        row = _object(item, f"diversity[{index}]")
        if row.get("metric") == "peak_demand_kw":
            return _band(row.get("interval"), "peak_demand_kw")
    raise ValueError("saved results have no diversity peak")


def _band(value: object, name: str) -> tuple[float, float, float]:
    row = _object(value, name)
    return (
        _number(row.get("mean"), f"{name}.mean"),
        _number(row.get("low"), f"{name}.low"),
        _number(row.get("high"), f"{name}.high"),
    )


def _numbers(value: object, name: str) -> list[float]:
    return [_number(item, name) for item in _list(value, name)]


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    out: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{name} has a non-string key")
        out[key] = item
    return out


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return list(value)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number")
    return float(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _draw_band(
    ax: Axes,
    xs: list[float],
    series: Sequence[tuple[float, float, float]],
    colour: str,
    label: str,
) -> None:
    means = [row[0] for row in series]
    lows = [row[1] for row in series]
    highs = [row[2] for row in series]
    ax.fill_between(xs, lows, highs, color=colour, alpha=BAND_ALPHA, linewidth=0)
    ax.plot(xs, means, color=colour, linewidth=LINE_WIDTH, marker="o", label=label)


def _require_same_length(
    left_name: str,
    left: Sequence[float],
    right_name: str,
    right: Sequence[tuple[float, float, float]],
) -> None:
    if len(left) != len(right):
        raise ValueError(
            f"{left_name} and {right_name} must match (got {len(left)} and {len(right)})"
        )
