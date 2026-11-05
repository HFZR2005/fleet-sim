"""Comparison and diagnostic figures for the price-curve pipeline.

All functions here are stubs that return watermarked placeholder
figures.  The real implementations land in issue #72.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from fleet_sim.prices.curves import FittedCurve
from fleet_sim.prices.dataset import PriceDataset
from fleet_sim.prices.evaluation import EvaluationReport
from fleet_sim.prices.targets import Target
from fleet_sim.stubs import stub
from fleet_sim.viz.style import (
    PRICE_CURVE_FIGURE_INCHES,
    apply_style,
    style_axes,
    watermark_stub,
)


@stub("placeholder scatter — replace in issue #72")
def plot_price_vs_residual(
    dataset: PriceDataset,
    fitted: FittedCurve,
    target: Target,
    *,
    title: str = "Price vs residual load",
) -> Figure:
    """Scatter of target value against residual load with fitted curve.

    Stub: empty axes with a STUB watermark.
    """
    _ = dataset, fitted, target
    apply_style()
    fig, ax = plt.subplots(figsize=PRICE_CURVE_FIGURE_INCHES)
    style_axes(ax)
    ax.set_xlabel("Residual load (GW)")
    ax.set_ylabel("Price (£/MWh)")
    ax.set_title(title)
    watermark_stub(fig)
    plt.close(fig)
    return fig


@stub("placeholder comparison — replace in issue #72")
def plot_evaluation_summary(report: EvaluationReport) -> Figure:
    """Bar chart of test RMSE across models.

    Stub: empty axes with a STUB watermark.
    """
    _ = report
    apply_style()
    fig, ax = plt.subplots(figsize=PRICE_CURVE_FIGURE_INCHES)
    style_axes(ax)
    ax.set_xlabel("Model")
    ax.set_ylabel("Test RMSE (£/MWh)")
    ax.set_title("Model comparison")
    watermark_stub(fig)
    plt.close(fig)
    return fig
