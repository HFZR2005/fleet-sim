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

import bisect
import itertools
import math
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator
from scipy.optimize import curve_fit, isotonic_regression


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


class ExponentialFit(BaseModel):
    """Fitted exponential h(R) = α + β·e^{γR}.

    Slope: h'(R) = βγ·e^{γR}.  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    alpha: float
    beta: float
    gamma: float

    def predict(self, r_gw: float) -> float:
        """h(R) = α + β·e^{γR}."""
        return self.alpha + self.beta * math.exp(self.gamma * r_gw)

    def slope(self, r_gw: float) -> float:
        """h'(R) = βγ·e^{γR}."""
        return self.beta * self.gamma * math.exp(self.gamma * r_gw)


def _exponential(
    r: NDArray[np.float64], alpha: float, beta: float, gamma: float
) -> NDArray[np.float64]:
    """α + β·e^{γR}, vectorised for ``curve_fit``."""
    return alpha + beta * np.exp(gamma * r)


# Starting γ values, as multiples of 1 / (range of R): 21 log-spaced
# magnitudes from 0.1 to 10, each with both signs.  γ = 0 is left out
# because e^{γR} is then constant and collinear with α.
_GAMMA_GRID_SCALED = np.concatenate(
    [-np.logspace(-1.0, 1.0, 21), np.logspace(-1.0, 1.0, 21)]
)


class Exponential:
    """Family h(R) = α + β·e^{γR}, fit by nonlinear least squares.

    Minimises Σ (yᵢ − α − β·e^{γRᵢ})² with ``scipy.optimize.curve_fit``
    (Levenberg–Marquardt), which is iterative and needs starting values.

    Starting values: for fixed γ the model is linear in (α, β), so they
    are solved exactly by least squares on the columns [1, e^{γR}].  This
    is done for each γ = c / (max R − min R) with c on ±logspace(−1, 1, 21),
    and the (α, β, γ) with the smallest sum of squared errors is the start.
    See ``docs/formulation.md``, Price curves.
    """

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> ExponentialFit:
        """Return the least-squares ``ExponentialFit``."""
        r, y_arr = _as_arrays(r_gw, y)
        if np.unique(r).size < 3:
            raise ValueError(
                "Exponential needs at least 3 distinct r_gw values to be fit"
            )
        start = self._starting_values(r, y_arr)
        try:
            params, _covariance = curve_fit(_exponential, r, y_arr, p0=start)
        except RuntimeError as error:
            raise ValueError(f"Exponential fit did not converge: {error}") from error
        alpha, beta, gamma = (float(p) for p in params)
        return ExponentialFit(alpha=alpha, beta=beta, gamma=gamma)

    @staticmethod
    def _starting_values(
        r: NDArray[np.float64], y: NDArray[np.float64]
    ) -> tuple[float, float, float]:
        """Best (α, β, γ) over the γ grid, with (α, β) solved exactly."""
        span = float(r.max() - r.min())
        best: tuple[float, float, float] | None = None
        best_sse = math.inf
        for gamma in _GAMMA_GRID_SCALED / span:
            design = np.column_stack([np.ones_like(r), np.exp(gamma * r)])
            coefficients, _residuals, _rank, _singular = np.linalg.lstsq(design, y)
            sse = float(np.sum((y - design @ coefficients) ** 2))
            if sse < best_sse:
                best_sse = sse
                best = (float(coefficients[0]), float(coefficients[1]), float(gamma))
        if best is None:
            raise ValueError("Exponential found no finite starting values")
        return best


class IsotonicFit(BaseModel):
    """Fitted non-decreasing curve, linear between knots.

    ``predict`` interpolates linearly between the knots (Rⱼ, vⱼ) and is
    flat beyond the first and last knot.  ``slope`` is the finite
    difference over the segment containing R,
    (vⱼ₊₁ − vⱼ) / (Rⱼ₊₁ − Rⱼ) for Rⱼ ≤ R < Rⱼ₊₁, and 0 outside the
    knots.  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    knots_r_gw: tuple[float, ...]
    values: tuple[float, ...]

    @model_validator(mode="after")
    def _check_knots(self) -> IsotonicFit:
        if len(self.knots_r_gw) != len(self.values):
            raise ValueError(
                "knots_r_gw and values must have the same length "
                f"(got {len(self.knots_r_gw)} and {len(self.values)})"
            )
        if not self.knots_r_gw:
            raise ValueError("an isotonic fit needs at least one knot")
        if any(b <= a for a, b in itertools.pairwise(self.knots_r_gw)):
            raise ValueError("knots_r_gw must be strictly increasing")
        if any(b < a for a, b in itertools.pairwise(self.values)):
            raise ValueError("values must be non-decreasing")
        return self

    def predict(self, r_gw: float) -> float:
        """Linear interpolation between knots, flat outside them."""
        return float(np.interp(r_gw, self.knots_r_gw, self.values))

    def slope(self, r_gw: float) -> float:
        """(vⱼ₊₁ − vⱼ) / (Rⱼ₊₁ − Rⱼ) on the segment containing ``r_gw``."""
        j = bisect.bisect_right(self.knots_r_gw, r_gw) - 1
        if j < 0 or j >= len(self.knots_r_gw) - 1:
            return 0.0
        rise = self.values[j + 1] - self.values[j]
        run = self.knots_r_gw[j + 1] - self.knots_r_gw[j]
        return rise / run


class Isotonic:
    """Best non-decreasing fit, by least squares.

    Minimises Σ (yᵢ − h(Rᵢ))² over all h with h(Rᵢ) ≤ h(Rⱼ) whenever
    Rᵢ ≤ Rⱼ, using ``scipy.optimize.isotonic_regression`` (pool adjacent
    violators).  Tied Rᵢ are first merged into their mean y, weighted by
    count.  The solution is constant on blocks of neighbouring R; each
    block becomes one knot at its count-weighted mean R and its fitted
    value, and ``IsotonicFit`` interpolates between knots.
    See ``docs/formulation.md``, Price curves.
    """

    def fit(self, r_gw: Sequence[float], y: Sequence[float]) -> IsotonicFit:
        """Return the least-squares ``IsotonicFit``."""
        r, y_arr = _as_arrays(r_gw, y)
        r_unique, inverse, counts = np.unique(
            r, return_inverse=True, return_counts=True
        )
        y_mean = np.bincount(inverse, weights=y_arr) / counts
        result = isotonic_regression(y_mean, weights=counts)
        knots: list[float] = []
        values: list[float] = []
        for start, end in itertools.pairwise(result.blocks):
            block_counts = counts[start:end]
            knots.append(float(np.average(r_unique[start:end], weights=block_counts)))
            values.append(float(result.x[start]))
        return IsotonicFit(knots_r_gw=tuple(knots), values=tuple(values))


FAMILIES: dict[str, PriceCurve] = {
    "cubic": Cubic(),
    "signed_quadratic": SignedQuadratic(),
    "cubic_offset": CubicOffset(),
    "exponential": Exponential(),
    "isotonic": Isotonic(),
}
