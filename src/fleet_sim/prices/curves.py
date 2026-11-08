"""Curve families that fit price as a function of residual load.

A ``PriceCurve`` fits ``(r_gw, y)`` data and returns a ``FittedCurve``
whose ``predict`` and ``slope`` methods evaluate the relationship at
new residual-load values.  No family knows about targets: the caller
transforms observations into ``y`` before calling ``fit``.

Each family is split in two.  The fitted model (``CubicFit`` and so on)
holds the parameters as its fields and evaluates the formula from them.
The family's ``fit`` estimates those parameters by least squares.  The
estimator can change without touching the formula.

Parameter names carry no units because ``y`` depends on the target:
£/MWh for the raw target, dimensionless for the fuel-adjusted one.
Residual load is in GW.

See ``docs/formulation.md``, Price curves, and ``docs/architecture.md``,
Price curves.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

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


def _as_arrays(
    r_gw: Sequence[float], y: Sequence[float]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Check the data and return it as float arrays."""
    if len(r_gw) != len(y):
        raise ValueError(
            f"r_gw and y must have the same length (got {len(r_gw)} and {len(y)})"
        )
    if not y:
        raise ValueError("cannot fit with no observations")
    return np.asarray(r_gw, dtype=np.float64), np.asarray(y, dtype=np.float64)


def _ratio(numerator: float, denominator: float, family: str) -> float:
    """Return a one-parameter estimate, rejecting a zero denominator."""
    if denominator == 0.0:
        raise ValueError(f"{family} cannot be fit when every r_gw is zero")
    return numerator / denominator


class CubicFit(BaseModel):
    """Fitted cubic h(R) = a·R³.

    Slope: h'(R) = 3a·R².  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a: float

    def predict(self, r_gw: float) -> float:
        """h(R) = a·R³."""
        return self.a * r_gw**3

    def slope(self, r_gw: float) -> float:
        """h'(R) = 3a·R²."""
        return 3.0 * self.a * r_gw**2


class Cubic:
    """Family h(R) = a·R³, fit by least squares.

    Minimising Σ (yᵢ − a·Rᵢ³)² over a gives the closed form
    â = Σ yᵢRᵢ³ / Σ Rᵢ⁶.  See ``docs/formulation.md``, Price curves.
    """

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> CubicFit:
        """Return the least-squares ``CubicFit``."""
        r, y_arr = _as_arrays(r_gw, y)
        a = _ratio(float(np.sum(y_arr * r**3)), float(np.sum(r**6)), "Cubic")
        return CubicFit(a=a)


class SignedQuadraticFit(BaseModel):
    """Fitted signed quadratic h(R) = a·sgn(R)·R², equal to a·R·|R|.

    Slope: h'(R) = 2a·|R|.  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a: float

    def predict(self, r_gw: float) -> float:
        """h(R) = a·R·|R|."""
        return self.a * r_gw * abs(r_gw)

    def slope(self, r_gw: float) -> float:
        """h'(R) = 2a·|R|."""
        return 2.0 * self.a * abs(r_gw)


class SignedQuadratic:
    """Family h(R) = a·sgn(R)·R², fit by least squares.

    Minimising Σ (yᵢ − a·Rᵢ|Rᵢ|)² over a gives the closed form
    â = Σ yᵢRᵢ|Rᵢ| / Σ Rᵢ⁴.  See ``docs/formulation.md``, Price curves.
    """

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> SignedQuadraticFit:
        """Return the least-squares ``SignedQuadraticFit``."""
        r, y_arr = _as_arrays(r_gw, y)
        a = _ratio(
            float(np.sum(y_arr * r * np.abs(r))),
            float(np.sum(r**4)),
            "SignedQuadratic",
        )
        return SignedQuadraticFit(a=a)


class CubicOffsetFit(BaseModel):
    """Fitted cubic with offset and linear term h(R) = a₀ + a₁R + a₃R³.

    Slope: h'(R) = a₁ + 3a₃R².  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a0: float
    a1: float
    a3: float

    def predict(self, r_gw: float) -> float:
        """h(R) = a₀ + a₁R + a₃R³."""
        return self.a0 + self.a1 * r_gw + self.a3 * r_gw**3

    def slope(self, r_gw: float) -> float:
        """h'(R) = a₁ + 3a₃R²."""
        return self.a1 + 3.0 * self.a3 * r_gw**2


class CubicOffset:
    """Family h(R) = a₀ + a₁R + a₃R³, fit by ordinary least squares.

    With design matrix X = [1, R, R³], the estimate solves the normal
    equations XᵀX â = Xᵀy.  ``numpy.linalg.lstsq`` solves them by SVD.
    See ``docs/formulation.md``, Price curves.
    """

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> CubicOffsetFit:
        """Return the least-squares ``CubicOffsetFit``."""
        r, y_arr = _as_arrays(r_gw, y)
        design = np.column_stack([np.ones_like(r), r, r**3])
        coefficients, _residuals, rank, _singular = np.linalg.lstsq(design, y_arr)
        if rank < design.shape[1]:
            raise ValueError(
                "CubicOffset needs at least 3 distinct r_gw values to be fit"
            )
        a0, a1, a3 = (float(c) for c in coefficients)
        return CubicOffsetFit(a0=a0, a1=a1, a3=a3)


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
    "cubic": Cubic(),
    "signed_quadratic": SignedQuadratic(),
    "cubic_offset": CubicOffset(),
}
