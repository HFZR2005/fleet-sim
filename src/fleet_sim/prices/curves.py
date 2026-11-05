"""Curve families that fit price as a function of residual load.

A ``PriceCurve`` fits ``(r_gw, y)`` data and returns a ``FittedCurve``
whose ``predict`` and ``slope`` methods evaluate the relationship at
new residual-load values.  No family knows about targets: the caller
transforms observations into ``y`` before calling ``fit``.

See ``docs/architecture.md``, Price curves.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from fleet_sim.stubs import stub


class FittedCurve(Protocol):
    """A curve that has been fit to data."""

    def predict(self, r_gw: float) -> float:
        """Predicted value at residual load ``r_gw``."""
        ...

    def slope(self, r_gw: float) -> float:
        """Derivative of the predicted value with respect to ``r_gw``."""
        ...


class PriceCurve(Protocol):
    """A curve family that can be fit to ``(r_gw, y)`` data."""

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> FittedCurve:
        """Fit the curve to the data and return the fitted result."""
        ...


class ConstantFit:
    """Fitted curve that predicts the training mean everywhere."""

    def __init__(self, mean_y: float) -> None:
        self._mean_y = mean_y

    def predict(self, r_gw: float) -> float:
        """Return the training mean regardless of ``r_gw``."""
        _ = r_gw
        return self._mean_y

    def slope(self, r_gw: float) -> float:
        """Return zero: a constant has no slope."""
        _ = r_gw
        return 0.0


class ConstantCurve:
    """Curve family that always predicts the training mean."""

    @stub("constant placeholder — replace with polynomial/piecewise families")
    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> ConstantFit:
        """Return a ``ConstantFit`` at the mean of ``y``."""
        if not y:
            raise ValueError("cannot fit with no observations")
        mean = sum(y) / len(y)
        return ConstantFit(mean)


FAMILIES: dict[str, PriceCurve] = {
    "constant": ConstantCurve(),
}
