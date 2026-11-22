"""Fleet-in-the-loop figures from a saved metrics.json. No solver."""

import json
from pathlib import Path

import numpy as np
import pytest

from fleet_sim.models.market import EquilibriumDiagnostics
from fleet_sim.models.results import (
    ConfidenceInterval,
    MarketLevelResult,
    MarketSweep,
    MetricEstimate,
)
from fleet_sim.viz.market import (
    plot_added_load,
    plot_overload_by_penetration,
    plot_saving_by_model,
    read_market_sweep,
)
from fleet_sim.viz.save import save_figure
from fleet_sim.viz.style import MARKET_FIGURE_INCHES, OVERLOAD_GRID_FIGURE_INCHES

_MAIN = "fuel_adjusted/exponential"
_ROBUST = "fuel_adjusted/cubic"


def _estimate(metric: str, mean: float) -> MetricEstimate:
    return MetricEstimate(
        metric=metric,
        interval=ConfidenceInterval(
            level=0.95, mean=mean, low=mean - 1, high=mean + 1, replications=2
        ),
    )


def _level(model: str, rho: float, m: float, penetration: float) -> MarketLevelResult:
    """Saving 50 − 10 M (millions) p/day; overloaded share = penetration."""
    diagnostics = EquilibriumDiagnostics(
        linearisation_error_p_per_kwh=0.0,
        mode_break_slots=0,
        max_replan_saving_p=0.0,
        total_replan_saving_p=0.0,
        exceeds_tolerance=False,
        replanned_load_difference_gw=0.0,
        out_of_range_slots=0,
    )
    overload = [_estimate("transformers_overloaded_share", penetration)]
    return MarketLevelResult(
        price_model=model,
        rho=rho,
        national_batteries=m,
        penetration=penetration,
        market=[_estimate("saving_per_battery_home_p_per_day", 50 - 10 * m / 1e6)],
        joint_overload=overload,
        replanned_overload=overload,
        market_change=[],
        joint_overload_change=[],
        replanned_overload_change=[],
        net_power_per_battery_home_kw=[1.0] * 4 + [-0.1] * 44,
        diagnostics=diagnostics,
    )


def _values(data: object) -> list[float]:
    return [float(value) for value in np.asarray(data)]


@pytest.fixture
def metrics_path(tmp_path: Path) -> Path:
    """Two ρ, two penetrations and M = 0, 1 million; cubic at the headline."""
    levels = [
        _level(_MAIN, rho, m, p)
        for rho in (0.0, 0.8)
        for p in (0.5, 1.0)
        for m in (0.0, 1e6)
    ] + [_level(_ROBUST, 0.0, m, 1.0) for m in (0.0, 1e6)]
    sweep = MarketSweep(
        price_model=_MAIN,
        robustness_models=[_ROBUST],
        headline_rho=0.0,
        headline_penetration=1.0,
        solve_count=20,
        wall_time_s=1.0,
        diagnostics=levels[0].diagnostics,
        levels=levels,
    )
    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps({"stubs": [], "market": sweep.model_dump(mode="json")}),
        encoding="utf-8",
    )
    return path


def test_the_market_figures_draw_the_saved_results(
    metrics_path: Path, tmp_path: Path
) -> None:
    sweep = read_market_sweep(metrics_path)

    added = plot_added_load(sweep)
    saving = plot_saving_by_model(sweep)
    overload = plot_overload_by_penetration(sweep)

    # Added load: M = 0 and M = 1 million at the headline, over 48 slots.
    lines = added.axes[0].get_lines()
    assert [line.get_label() for line in lines] == [
        "M = 0 (herd at historical prices)",
        "M = 1 million",
    ]
    assert _values(lines[0].get_xdata())[-1] == 23.5
    assert tuple(added.get_size_inches()) == MARKET_FIGURE_INCHES
    # Saving: one line per price model, 50 at M = 0 and 40 at 1 million.
    lines = saving.axes[0].get_lines()
    assert [line.get_label() for line in lines] == [_MAIN, _ROBUST]
    assert _values(lines[0].get_xdata()) == [0.0, 1.0]
    assert _values(lines[0].get_ydata()) == [50.0, 40.0]
    # Overloads: a 2 × 2 grid (ρ by allocation), one line per M, the share
    # against penetration in percent.
    assert tuple(overload.get_size_inches()) == OVERLOAD_GRID_FIGURE_INCHES
    assert [ax.get_title() for ax in overload.axes] == [
        "Joint, ρ = 0",
        "Re-planned, ρ = 0",
        "Joint, ρ = 0.8",
        "Re-planned, ρ = 0.8",
    ]
    for ax in overload.axes:
        assert len(ax.get_lines()) == 2
        assert _values(ax.get_lines()[0].get_xdata()) == [50.0, 100.0]
        assert _values(ax.get_lines()[0].get_ydata()) == [0.5, 1.0]

    svg, png = save_figure(overload, tmp_path / "overload")
    assert svg.exists() and png.exists()
