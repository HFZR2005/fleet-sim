"""The day figure builds from a saved schedule. No optimiser, no network."""

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.colors as mcolors
from matplotlib.axes import Axes
from matplotlib.patches import StepPatch

from fleet_sim.models import Schedule
from fleet_sim.viz import plot_day, save_figure
from fleet_sim.viz.style import (
    DAY_FIGURE_INCHES,
    FONT_FAMILY,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    PRICE,
    SOC,
)

FIXTURE = Path(__file__).parent / "fixtures" / "schedule_worked_example.json"


def test_day_figure_builds_from_the_fixture_schedule(tmp_path: Path) -> None:
    # Formulation worked example: prices [2, 10], imports [5, 0] with the
    # battery and [1, 1] without it, soc [0.75, 0.25].
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    schedule = Schedule.model_validate(payload["schedule"])

    figure = plot_day(
        schedule,
        price_p_per_kwh=payload["price_p_per_kwh"],
        grid_import_without_battery_kw=payload["grid_import_without_battery_kw"],
    )

    assert tuple(figure.get_size_inches()) == DAY_FIGURE_INCHES
    price_ax, soc_ax, import_ax = figure.axes
    assert price_ax.get_ylabel() == "Price (p/kWh)"
    assert soc_ax.get_ylabel() == "State of charge (fraction)"
    assert import_ax.get_ylabel() == "Grid import (kW)"
    assert import_ax.get_xlabel() == "Time (h)"
    assert price_ax.get_xlabel() == ""
    assert soc_ax.get_xlabel() == ""
    assert import_ax.get_shared_x_axes().joined(import_ax, price_ax)
    assert import_ax.get_shared_x_axes().joined(import_ax, soc_ax)
    assert _step_colour(price_ax) == PRICE
    assert _step_colour(soc_ax) == SOC
    assert _step_colour(import_ax, "Without battery") == IMPORT_WITHOUT_BATTERY
    assert _step_colour(import_ax, "With battery") == IMPORT_WITH_BATTERY
    assert mpl.rcParams["font.sans-serif"] == [FONT_FAMILY]
    assert price_ax.yaxis.label.get_fontsize() == mpl.rcParams["font.size"]

    svg_path, png_path = save_figure(figure, tmp_path / "day")
    assert svg_path.suffix == ".svg"
    assert png_path.suffix == ".png"
    svg = svg_path.read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<?xml")
    assert "Price (p/kWh)" in svg
    assert "State of charge (fraction)" in svg
    assert "Grid import (kW)" in svg
    assert "Time (h)" in svg
    assert png_path.read_bytes().startswith(b"\x89PNG")
    assert png_path.stat().st_size > 0


def _step_colour(ax: Axes, label: str | None = None) -> str:
    for patch in ax.patches:
        if not isinstance(patch, StepPatch):
            continue
        if label is not None and patch.get_label() != label:
            continue
        colour = mcolors.to_hex(patch.get_edgecolor())
        return colour.lower()
    raise AssertionError(f"no step on {ax.get_ylabel()}")
