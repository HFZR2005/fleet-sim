"""The network figure. It is a watermarked placeholder until the real charts exist."""

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.models.results import MetricEstimate
from fleet_sim.stubs import stub
from fleet_sim.viz.style import (
    FONT_SIZE,
    IMPORT_WITH_BATTERY,
    INK,
    LINE_WIDTH,
    NETWORK_FIGURE_INCHES,
    apply_style,
    style_axes,
)


@stub("the network figure is a watermarked placeholder")
def plot_network_overload(metrics: list[MetricEstimate]) -> Figure:
    """Draw the overload intervals, with a STUB watermark.

    The series are drawn as given. They are not computed here.
    """
    if len(metrics) == 0:
        raise ValueError("a figure needs at least one metric")
    apply_style()
    figure = Figure(figsize=NETWORK_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    xs = list(range(len(metrics)))
    means = [item.interval.mean for item in metrics]
    lows = [item.interval.mean - item.interval.low for item in metrics]
    highs = [item.interval.high - item.interval.mean for item in metrics]
    ax.bar(
        xs,
        means,
        color=IMPORT_WITH_BATTERY,
        width=0.6,
        yerr=[lows, highs],
        capsize=3,
        error_kw={"ecolor": INK, "linewidth": LINE_WIDTH},
    )
    ax.set_xticks(xs, [item.metric for item in metrics], rotation=20, ha="right")
    ax.set_ylabel("Value")
    ax.text(
        0.5,
        0.5,
        "STUB",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=FONT_SIZE * 3,
        color=INK,
        alpha=0.25,
    )
    style_axes(ax)
    figure.tight_layout()
    return figure
