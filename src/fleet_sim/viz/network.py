"""Network figures drawn from saved results and frames.

Figure 1: share of transformers overloaded against penetration.
Figure 2: one transformer's day — flow vs demand vs limit.
Figure 3: distribution of peak utilisation across transformers.
"""

import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from fleet_sim.fleet.frames import read_frames
from fleet_sim.viz.style import (
    BAND_ALPHA,
    IMPORT_WITH_BATTERY,
    IMPORT_WITHOUT_BATTERY,
    INK,
    LIMIT_LINE,
    LINE_WIDTH,
    NETWORK_FIGURE_INCHES,
    OVERLOAD_FILL,
    TRANSFORMER_DAY_FIGURE_INCHES,
    UTILISATION_FIGURE_INCHES,
    apply_style,
    style_axes,
)

_HOURS_PER_SLOT = 0.5


# ---------------------------------------------------------------------------
# Figure 1: overloaded share vs penetration
# ---------------------------------------------------------------------------


class OverloadSeries:
    """One labelled series for the overload-vs-penetration curve."""

    def __init__(
        self,
        label: str,
        penetrations: list[float],
        bands: list[tuple[float, float, float]],
    ) -> None:
        if len(penetrations) != len(bands):
            raise ValueError(
                f"penetrations and bands must match "
                f"(got {len(penetrations)} and {len(bands)})"
            )
        if not penetrations:
            raise ValueError("a series needs at least one penetration")
        self.label = label
        self.penetrations = penetrations
        self.bands = bands


def read_overload_curve(path: Path) -> OverloadSeries:
    """Read ``transformers_overloaded_share`` from a milestone-4 JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("saved results must be an object")
    levels = payload.get("network_levels")
    if not isinstance(levels, list):
        raise TypeError("network_levels must be a list")
    penetrations: list[float] = []
    bands: list[tuple[float, float, float]] = []
    for level in levels:
        if not isinstance(level, dict):
            raise TypeError("each level must be an object")
        penetrations.append(float(level["penetration"]))
        for metric in level["metrics"]:
            if metric["metric"] == "transformers_overloaded_share":
                iv = metric["interval"]
                bands.append((float(iv["mean"]), float(iv["low"]), float(iv["high"])))
                break
        else:
            raise ValueError("level has no transformers_overloaded_share")
    return OverloadSeries(label="ρ = 0", penetrations=penetrations, bands=bands)


def plot_overload_curve(series: Sequence[OverloadSeries]) -> Figure:
    """Share of transformers overloaded against penetration, one line per series."""
    if not series:
        raise ValueError("a figure needs at least one series")
    apply_style()
    colours = [IMPORT_WITH_BATTERY, OVERLOAD_FILL, INK, LIMIT_LINE]
    figure = Figure(figsize=NETWORK_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    for index, s in enumerate(series):
        colour = colours[index % len(colours)]
        xs = [100.0 * p for p in s.penetrations]
        means = [b[0] for b in s.bands]
        lows = [b[1] for b in s.bands]
        highs = [b[2] for b in s.bands]
        ax.fill_between(xs, lows, highs, color=colour, alpha=BAND_ALPHA, linewidth=0)
        ax.plot(
            xs, means, color=colour, linewidth=LINE_WIDTH, marker="o", label=s.label
        )
    ax.set_xlabel("Penetration (%)")
    ax.set_ylabel("Share of transformers overloaded")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


# ---------------------------------------------------------------------------
# Figure 2: one transformer's day
# ---------------------------------------------------------------------------


class TransformerDay:
    """Flow, demand, and limit for one transformer over a day."""

    def __init__(
        self,
        node_id: str,
        flow_kw: list[float],
        demand_kw: list[float],
        limit_kw: float,
    ) -> None:
        if len(flow_kw) != len(demand_kw):
            raise ValueError(
                f"flow and demand must match (got {len(flow_kw)} and {len(demand_kw)})"
            )
        if not flow_kw:
            raise ValueError("a transformer day needs at least one slot")
        self.node_id = node_id
        self.flow_kw = flow_kw
        self.demand_kw = demand_kw
        self.limit_kw = limit_kw


def read_transformer_day(path: Path, node_id: str | None = None) -> TransformerDay:
    """Read one transformer's day from saved frames.

    When ``node_id`` is ``None``, picks the transformer with the highest
    peak flow.
    """
    log = read_frames(path)
    frames = log.frames
    if not frames:
        raise ValueError("frames file is empty")

    node_ids: set[str] = set()
    node_limits: dict[str, float] = {}
    for frame in frames:
        for node in frame.nodes:
            if node.limit_kw is not None:
                node_ids.add(node.node_id)
                node_limits[node.node_id] = node.limit_kw
    if not node_ids:
        raise ValueError("no constrained nodes in the frames")

    if node_id is None:
        peak_flow: dict[str, float] = defaultdict(float)
        for frame in frames:
            for node in frame.nodes:
                if node.node_id in node_ids:
                    peak_flow[node.node_id] = max(peak_flow[node.node_id], node.flow_kw)
        node_id = max(peak_flow, key=peak_flow.__getitem__)

    if node_id not in node_ids:
        raise ValueError(f"node {node_id} not found among constrained nodes")

    home_transformers: dict[str, str] = {}
    for frame in frames:
        for home in frame.homes:
            if home.transformer_id is not None:
                home_transformers[home.home_id] = home.transformer_id

    flow_kw: list[float] = []
    demand_kw: list[float] = []
    for frame in frames:
        node_flow = 0.0
        for node in frame.nodes:
            if node.node_id == node_id:
                node_flow = node.flow_kw
                break
        flow_kw.append(node_flow)
        slot_demand = sum(
            home.demand_kw
            for home in frame.homes
            if home_transformers.get(home.home_id) == node_id
        )
        demand_kw.append(slot_demand)

    return TransformerDay(
        node_id=node_id,
        flow_kw=flow_kw,
        demand_kw=demand_kw,
        limit_kw=node_limits[node_id],
    )


def plot_transformer_day(data: TransformerDay) -> Figure:
    """One transformer's flow and demand over a day, with the limit and overload shaded."""
    apply_style()
    figure = Figure(figsize=TRANSFORMER_DAY_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    n_slots = len(data.flow_kw)
    edges = [_HOURS_PER_SLOT * i for i in range(n_slots + 1)]

    ax.stairs(
        data.demand_kw,
        edges,
        baseline=None,
        color=IMPORT_WITHOUT_BATTERY,
        linewidth=LINE_WIDTH,
        label="Without batteries",
    )
    ax.stairs(
        data.flow_kw,
        edges,
        baseline=None,
        color=IMPORT_WITH_BATTERY,
        linewidth=LINE_WIDTH,
        label="With batteries",
    )
    ax.axhline(
        data.limit_kw,
        color=LIMIT_LINE,
        linewidth=LINE_WIDTH,
        linestyle="--",
        label="Transformer limit",
    )

    _shade_overload(ax, data.flow_kw, data.limit_kw, edges)

    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Power (kW)")
    ax.set_title(f"Transformer {data.node_id}")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure


def _shade_overload(
    ax: Axes,
    flow_kw: list[float],
    limit_kw: float,
    edges: list[float],
) -> None:
    """Fill the area where flow exceeds the limit."""
    centres = [0.5 * (edges[i] + edges[i + 1]) for i in range(len(flow_kw))]
    flow_arr = np.array(flow_kw)
    limit_arr = np.full_like(flow_arr, limit_kw)
    ax.fill_between(
        centres,
        limit_arr,
        flow_arr,
        where=flow_arr > limit_kw,
        color=OVERLOAD_FILL,
        alpha=0.3,
        interpolate=True,
        label="Overload",
    )


# ---------------------------------------------------------------------------
# Figure 3: peak utilisation distribution
# ---------------------------------------------------------------------------


class UtilisationData:
    """Peak utilisation per transformer from one set of frames."""

    def __init__(self, utilisations: list[float]) -> None:
        if not utilisations:
            raise ValueError("utilisation data needs at least one transformer")
        self.utilisations = utilisations


def read_utilisation_distribution(path: Path) -> UtilisationData:
    """Peak utilisation per transformer from saved frames."""
    log = read_frames(path)
    frames = log.frames
    if not frames:
        raise ValueError("frames file is empty")

    node_limits: dict[str, float] = {}
    node_peak: dict[str, float] = defaultdict(float)
    for frame in frames:
        for node in frame.nodes:
            if node.limit_kw is not None:
                node_limits[node.node_id] = node.limit_kw
                node_peak[node.node_id] = max(node_peak[node.node_id], node.flow_kw)

    if not node_limits:
        raise ValueError("no constrained nodes in the frames")

    utilisations = [node_peak[nid] / node_limits[nid] for nid in sorted(node_limits)]
    return UtilisationData(utilisations=utilisations)


def plot_utilisation_distribution(data: UtilisationData) -> Figure:
    """Histogram of peak utilisation across transformers."""
    apply_style()
    figure = Figure(figsize=UTILISATION_FIGURE_INCHES)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    ax.hist(
        data.utilisations,
        bins="auto",
        color=IMPORT_WITH_BATTERY,
        edgecolor=INK,
        linewidth=0.6,
    )
    ax.axvline(
        1.0,
        color=OVERLOAD_FILL,
        linewidth=LINE_WIDTH,
        linestyle="--",
        label="Limit (utilisation = 1)",
    )
    ax.set_xlabel("Peak utilisation")
    ax.set_ylabel("Number of transformers")
    ax.legend()
    style_axes(ax)
    figure.tight_layout()
    return figure
