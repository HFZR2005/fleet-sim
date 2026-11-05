"""Network figures from a saved fixture. No optimiser, no network API."""

import json
from pathlib import Path

import matplotlib.colors as mcolors
from matplotlib.axes import Axes
from matplotlib.collections import PolyCollection
from matplotlib.patches import StepPatch

from fleet_sim.viz.network import (
    OverloadSeries,
    plot_overload_curve,
    plot_transformer_day,
    plot_utilisation_distribution,
    read_overload_curve,
    read_transformer_day,
    read_utilisation_distribution,
)
from fleet_sim.viz.save import save_figure
from fleet_sim.viz.style import (
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    NETWORK_FIGURE_INCHES,
    OVERLOAD_FILL,
    TRANSFORMER_DAY_FIGURE_INCHES,
    UTILISATION_FIGURE_INCHES,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "milestone4_figures.json"


def _frames_path(tmp_path: Path) -> Path:
    """Write just the frames portion of the fixture to a temp file."""
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frames_path = tmp_path / "frames.json"
    frames_path.write_text(json.dumps(payload["frames"]), encoding="utf-8")
    return frames_path


# ------------------------------------------------------------------
# Figure 1: overloaded share vs penetration
# ------------------------------------------------------------------


def test_overload_curve_reads_fixture(tmp_path: Path) -> None:
    # The fixture has 3 penetrations: 0%, 50%, 100%.
    # overloaded_share means: 0.0, 0.5, 1.0.
    series = read_overload_curve(_FIXTURE)

    assert series.penetrations == [0.0, 0.5, 1.0]
    assert series.bands[0] == (0.0, 0.0, 0.0)
    assert series.bands[1] == (0.5, 0.3, 0.7)
    assert series.bands[2] == (1.0, 1.0, 1.0)

    figure = plot_overload_curve([series])

    assert tuple(figure.get_size_inches()) == NETWORK_FIGURE_INCHES
    ax = figure.axes[0]
    assert ax.get_xlabel() == "Penetration (%)"
    assert ax.get_ylabel() == "Share of transformers overloaded"
    assert _line_colour(ax, "ρ = 0") == IMPORT_WITH_BATTERY
    assert any(isinstance(c, PolyCollection) for c in ax.collections)
    svg_path, png_path = save_figure(figure, tmp_path / "overload_curve")
    assert "Share of transformers overloaded" in svg_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")


def test_overload_curve_two_series(tmp_path: Path) -> None:
    s1 = OverloadSeries("ρ = 0", [0.0, 1.0], [(0.0, 0.0, 0.0), (1.0, 0.9, 1.0)])
    s2 = OverloadSeries("ρ = 0.8", [0.0, 1.0], [(0.0, 0.0, 0.0), (0.8, 0.6, 1.0)])

    figure = plot_overload_curve([s1, s2])
    ax = figure.axes[0]

    assert _line_colour(ax, "ρ = 0") == IMPORT_WITH_BATTERY
    assert _line_colour(ax, "ρ = 0.8") == OVERLOAD_FILL


# ------------------------------------------------------------------
# Figure 2: one transformer's day
# ------------------------------------------------------------------


def test_transformer_day_reads_fixture(tmp_path: Path) -> None:
    # Hand-worked values for the fixture:
    #   T1 is the worst transformer (peak flow 7.0 kW > T2's 3.0 kW).
    #   T1 flow:   [7.0, 6.0, 2.0, 2.0]
    #   T1 demand: [2.0, 2.0, 2.0, 2.0] (h1 + h2 demand in each slot)
    #   T1 limit:  5.0 kW
    #   Overload in slots 0 and 1 (flow > 5).
    frames_path = _frames_path(tmp_path)
    data = read_transformer_day(frames_path)

    assert data.node_id == "T1"
    assert data.flow_kw == [7.0, 6.0, 2.0, 2.0]
    assert data.demand_kw == [2.0, 2.0, 2.0, 2.0]
    assert data.limit_kw == 5.0

    figure = plot_transformer_day(data)

    assert tuple(figure.get_size_inches()) == TRANSFORMER_DAY_FIGURE_INCHES
    ax = figure.axes[0]
    assert ax.get_xlabel() == "Time (h)"
    assert ax.get_ylabel() == "Power (kW)"
    assert "T1" in ax.get_title()
    assert _step_colour(ax, "With batteries") == IMPORT_WITH_BATTERY
    assert _step_colour(ax, "Without batteries") == IMPORT_WITHOUT_BATTERY
    assert _hline_present(ax, 5.0)
    assert any(isinstance(c, PolyCollection) for c in ax.collections)
    svg_path, png_path = save_figure(figure, tmp_path / "transformer_day")
    assert "Power (kW)" in svg_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")


def test_transformer_day_specific_node(tmp_path: Path) -> None:
    # Ask for T2 explicitly.
    # T2 flow:   [3.0, 2.5, 2.5, 3.0]
    # T2 demand: [2.5, 2.5, 2.5, 3.0] (h3 + h4 demand in each slot)
    # T2 limit:  5.0 kW — no overload.
    frames_path = _frames_path(tmp_path)
    data = read_transformer_day(frames_path, node_id="T2")

    assert data.node_id == "T2"
    assert data.flow_kw == [3.0, 2.5, 2.5, 3.0]
    assert data.demand_kw == [2.5, 2.5, 2.5, 3.0]
    assert data.limit_kw == 5.0


# ------------------------------------------------------------------
# Figure 3: peak utilisation distribution
# ------------------------------------------------------------------


def test_utilisation_distribution_reads_fixture(tmp_path: Path) -> None:
    # Hand-worked values:
    #   T1 peak flow = 7.0, limit = 5.0 → utilisation = 1.4
    #   T2 peak flow = 3.0, limit = 5.0 → utilisation = 0.6
    frames_path = _frames_path(tmp_path)
    data = read_utilisation_distribution(frames_path)

    assert len(data.utilisations) == 2
    assert abs(data.utilisations[0] - 1.4) < 1e-9
    assert abs(data.utilisations[1] - 0.6) < 1e-9

    figure = plot_utilisation_distribution(data)

    assert tuple(figure.get_size_inches()) == UTILISATION_FIGURE_INCHES
    ax = figure.axes[0]
    assert ax.get_xlabel() == "Peak utilisation"
    assert ax.get_ylabel() == "Number of transformers"
    assert _vline_present(ax, 1.0)
    svg_path, png_path = save_figure(figure, tmp_path / "utilisation_dist")
    assert "Peak utilisation" in svg_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _line_colour(ax: Axes, label: str) -> str:
    for line in ax.get_lines():
        if line.get_label() == label:
            return mcolors.to_hex(line.get_color()).lower()
    raise AssertionError(f"no line labelled {label!r}")


def _step_colour(ax: Axes, label: str) -> str:
    for patch in ax.patches:
        if isinstance(patch, StepPatch) and patch.get_label() == label:
            return mcolors.to_hex(patch.get_edgecolor()).lower()
    raise AssertionError(f"no step labelled {label!r}")


def _hline_present(ax: Axes, y: float) -> bool:
    for line in ax.get_lines():
        ydata = line.get_ydata()
        if len(ydata) == 2 and all(abs(v - y) < 1e-9 for v in ydata):
            return True
    return False


def _vline_present(ax: Axes, x: float) -> bool:
    for line in ax.get_lines():
        xdata = line.get_xdata()
        if len(xdata) == 2 and all(abs(v - x) < 1e-9 for v in xdata):
            return True
    return False
