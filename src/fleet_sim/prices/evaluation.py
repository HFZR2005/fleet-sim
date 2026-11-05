"""Evaluate a fitted curve against held-out data.

See ``docs/architecture.md``, Price curves.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fleet_sim.prices.curves import FittedCurve
from fleet_sim.prices.dataset import PriceDataset
from fleet_sim.prices.targets import Target
from fleet_sim.stubs import stub


class FitResult(BaseModel):
    """Metrics for one (curve family, target) model on one split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str
    curve_family: str
    target_name: str
    train_rmse: float
    test_rmse: float
    train_r2: float
    test_r2: float


class EvaluationReport(BaseModel):
    """Comparison of all fitted models."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[FitResult]


@stub("zero-valued metrics — replace in issue #71")
def evaluate(
    fitted: FittedCurve,
    train_data: PriceDataset,
    test_data: PriceDataset,
    target: Target,
    *,
    model_name: str,
    curve_family: str,
    target_name: str,
) -> FitResult:
    """Score ``fitted`` on the train and test sets.

    Stub: returns zeros for all metrics.
    """
    _ = fitted, train_data, test_data, target
    return FitResult(
        model_name=model_name,
        curve_family=curve_family,
        target_name=target_name,
        train_rmse=0.0,
        test_rmse=0.0,
        train_r2=0.0,
        test_r2=0.0,
    )
