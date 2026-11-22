"""Fleet-in-the-loop figures. A watermarked placeholder until the real ones exist."""

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.models.results import MarketLevelResult
from fleet_sim.stubs import stub
from fleet_sim.viz.style import (
    IMPORT_WITH_BATTERY,
    LINE_WIDTH,
    NETWORK_FIGURE_INCHES,
    apply_style,
    style_axes,
    watermark_stub,
)

_SAVING = "saving_per_battery_home_p_per_day"


@stub("the market figure is a watermarked placeholder")
def plot_market_placeholder(levels: list[MarketLevelResult]) -> Figure:
    """Saving per battery home against M, as given, with a STUB watermark."""
    if len(levels) == 0:
        raise ValueError("a figure needs at least one level")
    apply_style()
    figure = Figure(figsize=NETWORK_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    xs = [level.national_batteries for level in levels]
    ys = [
        next(m.interval.mean for m in level.market if m.metric == _SAVING)
        for level in levels
    ]
    ax.plot(xs, ys, color=IMPORT_WITH_BATTERY, linewidth=LINE_WIDTH, marker="o")
    ax.set_xlabel("National batteries M")
    ax.set_ylabel("Saving per battery home (p/day)")
    style_axes(ax)
    watermark_stub(figure)
    figure.tight_layout()
    return figure
