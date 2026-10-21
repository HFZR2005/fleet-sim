"""One day: price, state of charge, and grid import.

The half-hour spacing on the time axis is (DT) in ``docs/formulation.md``.
The series themselves are drawn as given.
"""

from collections.abc import Sequence

from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.models.schedule import Schedule
from fleet_sim.viz.style import (
    DAY_FIGURE_INCHES,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    LINE_WIDTH,
    PRICE,
    SOC,
    apply_style,
    style_axes,
)

# (DT). Slot t occupies the half hour starting at t * 0.5 hours.
_HOURS_PER_SLOT = 0.5


def plot_day(
    schedule: Schedule,
    *,
    price_p_per_kwh: Sequence[float],
    grid_import_without_battery_kw: Sequence[float],
) -> Figure:
    """Draw one day of prices, state of charge, and grid import.

    ``price_p_per_kwh`` and ``grid_import_without_battery_kw`` are the top
    and the comparison series. They are not derived from ``schedule``.
    """
    n_slots = len(schedule.soc)
    _require_length("price_p_per_kwh", price_p_per_kwh, n_slots)
    _require_length(
        "grid_import_without_battery_kw", grid_import_without_battery_kw, n_slots
    )
    apply_style()
    figure = Figure(figsize=DAY_FIGURE_INCHES, layout="constrained")
    FigureCanvasAgg(figure)
    price_ax, soc_ax, import_ax = _panels(figure)
    edges = _edges_h(n_slots)
    _stairs(price_ax, edges, price_p_per_kwh, PRICE)
    _stairs(soc_ax, edges, schedule.soc, SOC)
    _stairs(
        import_ax,
        edges,
        grid_import_without_battery_kw,
        IMPORT_WITHOUT_BATTERY,
        label="Without battery",
    )
    _stairs(
        import_ax,
        edges,
        schedule.grid_import_kw,
        IMPORT_WITH_BATTERY,
        label="With battery",
    )
    price_ax.set_ylabel("Price (p/kWh)")
    soc_ax.set_ylabel("State of charge (fraction)")
    soc_ax.set_ylim(0.0, 1.0)
    import_ax.set_ylabel("Grid import (kW)")
    import_ax.set_xlabel("Time (h)")
    import_ax.legend()
    price_ax.tick_params(labelbottom=False)
    soc_ax.tick_params(labelbottom=False)
    return figure


def _panels(figure: Figure) -> tuple[Axes, Axes, Axes]:
    price_ax = figure.add_subplot(3, 1, 1)
    soc_ax = figure.add_subplot(3, 1, 2, sharex=price_ax)
    import_ax = figure.add_subplot(3, 1, 3, sharex=price_ax)
    for ax in (price_ax, soc_ax, import_ax):
        style_axes(ax)
    return price_ax, soc_ax, import_ax


def _stairs(
    ax: Axes,
    edges: list[float],
    values: Sequence[float],
    colour: str,
    *,
    label: str | None = None,
) -> None:
    ax.stairs(
        list(values),
        edges,
        baseline=None,
        color=colour,
        linewidth=LINE_WIDTH,
        label=label,
    )


def _edges_h(n_slots: int) -> list[float]:
    return [_HOURS_PER_SLOT * slot for slot in range(n_slots + 1)]


def _require_length(name: str, values: Sequence[float], n_slots: int) -> None:
    if len(values) != n_slots:
        raise ValueError(
            f"{name} must contain one value per schedule slot "
            f"(got {len(values)}, expected {n_slots})"
        )
