"""Penetration and diversity figures from a saved fixture. No optimiser."""

from datetime import date
from pathlib import Path

import matplotlib.colors as mcolors
from matplotlib.axes import Axes
from matplotlib.collections import PolyCollection
from matplotlib.patches import StepPatch

from fleet_sim.viz import plot_diversity_day, plot_penetration_curve, save_figure
from fleet_sim.viz.results import read_diversity_day, read_penetration_curve
from fleet_sim.viz.style import (
    DIVERSE,
    DIVERSITY_FIGURE_INCHES,
    IDENTICAL,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    PENETRATION_FIGURE_INCHES,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "milestone3_figures.json"


def test_penetration_curve_reads_the_fixture(tmp_path: Path) -> None:
    penetrations, with_battery, without_battery = read_penetration_curve(_FIXTURE)

    figure = plot_penetration_curve(penetrations, with_battery, without_battery)

    assert tuple(figure.get_size_inches()) == PENETRATION_FIGURE_INCHES
    ax = figure.axes[0]
    assert ax.get_xlabel() == "Penetration (%)"
    assert ax.get_ylabel() == "Peak demand (kW)"
    assert _line_colour(ax, "Without batteries") == IMPORT_WITHOUT_BATTERY
    assert _line_colour(ax, "With batteries") == IMPORT_WITH_BATTERY
    assert any(isinstance(item, PolyCollection) for item in ax.collections)
    svg_path, png_path = save_figure(figure, tmp_path / "penetration")
    assert "Peak demand (kW)" in svg_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")


def test_diversity_day_reads_the_fixture_and_annotates_the_interval(
    tmp_path: Path,
) -> None:
    diverse, identical, day, difference = read_diversity_day(_FIXTURE)

    figure = plot_diversity_day(
        diverse, identical, day=day, peak_difference_kw=difference
    )

    assert day == date(2026, 1, 8)
    assert tuple(figure.get_size_inches()) == DIVERSITY_FIGURE_INCHES
    ax = figure.axes[0]
    assert ax.get_ylabel() == "Grid import (kW)"
    assert ax.get_xlabel() == "Time (h)"
    assert _step_colour(ax, "Diverse") == DIVERSE
    assert _step_colour(ax, "Identical") == IDENTICAL
    note = ax.texts[0].get_text()
    assert "8 January 2026" in note
    assert "Mean peak difference -1.50 kW" in note
    assert "(-2.00 to -1.00)" in note
    svg_path, png_path = save_figure(figure, tmp_path / "diversity")
    assert "Grid import (kW)" in svg_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")


def _line_colour(ax: Axes, label: str) -> str:
    for line in ax.get_lines():
        if line.get_label() == label:
            return mcolors.to_hex(line.get_color()).lower()
    raise AssertionError(f"no line labelled {label}")


def _step_colour(ax: Axes, label: str) -> str:
    for patch in ax.patches:
        if isinstance(patch, StepPatch) and patch.get_label() == label:
            return mcolors.to_hex(patch.get_edgecolor()).lower()
    raise AssertionError(f"no step labelled {label}")
