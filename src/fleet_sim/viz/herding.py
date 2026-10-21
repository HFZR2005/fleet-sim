"""Fleet figures drawn from saved frames.

Neither figure solves a schedule. The import series is the root node's
flow, and the import without batteries is the sum of the homes' demand.
"""

from collections.abc import Sequence
from datetime import date

from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.fleet.network import ROOT_NODE_ID
from fleet_sim.models.frames import Frame
from fleet_sim.viz.style import (
    FONT_SIZE,
    HERDING_FIGURE_INCHES,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    INK,
    LINE_WIDTH,
    PEAKS_FIGURE_INCHES,
    PRICE,
    apply_style,
    style_axes,
)

_HOURS_PER_SLOT = 0.5


def plot_herding(frames: Sequence[Frame]) -> Figure:
    """One day's fleet import, with and without batteries, and the price."""
    if not frames:
        raise ValueError("a figure needs at least one frame")
    apply_style()
    figure = Figure(figsize=HERDING_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    import_ax, price_ax = figure.subplots(2, 1, sharex=True, height_ratios=(2, 1))
    hours = [index * _HOURS_PER_SLOT for index in range(len(frames))]
    with_battery = [_root_flow(frame) for frame in frames]
    without_battery = [_demand(frame) for frame in frames]
    import_ax.stairs(
        with_battery,
        [*hours, hours[-1] + _HOURS_PER_SLOT],
        baseline=None,
        color=IMPORT_WITH_BATTERY,
        linewidth=LINE_WIDTH,
        label="With batteries",
    )
    import_ax.stairs(
        without_battery,
        [*hours, hours[-1] + _HOURS_PER_SLOT],
        baseline=None,
        color=IMPORT_WITHOUT_BATTERY,
        linewidth=LINE_WIDTH,
        label="Without batteries",
    )
    peak_slot = max(range(len(with_battery)), key=with_battery.__getitem__)
    peak_kw = with_battery[peak_slot]
    import_ax.annotate(
        f"{peak_kw:.1f} kW",
        xy=(peak_slot * _HOURS_PER_SLOT + _HOURS_PER_SLOT / 2, peak_kw),
        xytext=(6, 6),
        textcoords="offset points",
        color=INK,
        fontsize=FONT_SIZE,
    )
    import_ax.set_ylabel("Grid import (kW)")
    import_ax.legend()
    style_axes(import_ax)

    price_ax.stairs(
        [frame.price_p_per_kwh for frame in frames],
        [*hours, hours[-1] + _HOURS_PER_SLOT],
        baseline=None,
        color=PRICE,
        linewidth=LINE_WIDTH,
    )
    price_ax.set_ylabel("Price (p/kWh)")
    price_ax.set_xlabel("Time (h)")
    style_axes(price_ax)
    figure.tight_layout()
    return figure


def plot_daily_peaks(days: Sequence[tuple[date, Sequence[Frame]]]) -> Figure:
    """The peak import of each day, with and without batteries."""
    if not days:
        raise ValueError("a figure needs at least one day")
    apply_style()
    figure = Figure(figsize=PEAKS_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    xs = list(range(len(days)))
    with_battery = [max(_root_flow(frame) for frame in frames) for _, frames in days]
    without_battery = [max(_demand(frame) for frame in frames) for _, frames in days]
    _peak_line(ax, xs, with_battery, IMPORT_WITH_BATTERY, "With batteries")
    _peak_line(ax, xs, without_battery, IMPORT_WITHOUT_BATTERY, "Without batteries")
    ax.set_xticks(
        xs, [day.isoformat() for day, _frames in days], rotation=30, ha="right"
    )
    ax.set_ylabel("Peak demand (kW)")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


def _peak_line(
    ax: Axes, xs: list[int], values: list[float], color: str, label: str
) -> None:
    ax.plot(
        xs,
        values,
        color=color,
        linewidth=LINE_WIDTH,
        marker="o",
        label=label,
    )


def _root_flow(frame: Frame) -> float:
    for node in frame.nodes:
        if node.node_id == ROOT_NODE_ID:
            return node.flow_kw
    raise ValueError(f"frame at {frame.slot_start.isoformat()} has no root node")


def _demand(frame: Frame) -> float:
    return sum(home.demand_kw for home in frame.homes)
