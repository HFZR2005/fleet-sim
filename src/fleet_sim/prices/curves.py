"""Curve families that fit price as a function of residual load.

A ``PriceCurve`` fits per-slot bounds ``(r_gw, y_lower, y_upper)`` and
returns a ``FittedCurve`` whose ``predict`` and ``slope`` methods
evaluate the relationship at new residual-load values.  An exact slot
has ``y_lower == y_upper``; a censored slot has ``y_lower < y_upper``,
with ``y_upper = inf`` when only a lower bound is known.  No family
knows about targets: the caller turns observations into bounds on ``y``
before calling ``fit``.

Each family is split in two.  The fitted model (``CubicFit`` and so on)
holds the parameters and the noise scale σ as its fields and evaluates
the formula from them.  The family's ``fit`` estimates them by censored
maximum likelihood under constant-σ normal noise (ADR-0003).  The
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
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import curve_fit, isotonic_regression, minimize
from scipy.stats import norm

_Array = NDArray[np.float64]

_Curve = Callable[[_Array, _Array], _Array]
"""A family's formula h(R) as a function of its parameters θ and R."""


class FittedCurve(Protocol):
    """A curve that has been fit to data, with its noise scale σ."""

    @property
    def sigma(self) -> float:
        """Standard deviation of y about the curve (ADR-0003)."""
        ...

    def predict(self, r_gw: float) -> float:
        """Predicted value at residual load ``r_gw``."""
        ...

    def slope(self, r_gw: float) -> float:
        """Derivative of the predicted value with respect to ``r_gw``."""
        ...


class PriceCurve(Protocol):
    """A curve family that can be fit to per-slot bounds on ``y``."""

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> FittedCurve:
        """Fit the curve to the bounds and return the fitted result."""
        ...


def _as_arrays(
    r_gw: Sequence[float], y_lower: Sequence[float], y_upper: Sequence[float]
) -> tuple[_Array, _Array, _Array]:
    """Check the data and return it as float arrays."""
    if not len(r_gw) == len(y_lower) == len(y_upper):
        raise ValueError(
            "r_gw, y_lower and y_upper must have the same length "
            f"(got {len(r_gw)}, {len(y_lower)} and {len(y_upper)})"
        )
    if not r_gw:
        raise ValueError("cannot fit with no observations")
    r = np.asarray(r_gw, dtype=np.float64)
    lower = np.asarray(y_lower, dtype=np.float64)
    upper = np.asarray(y_upper, dtype=np.float64)
    if not (np.all(np.isfinite(r)) and np.all(np.isfinite(lower))):
        raise ValueError("r_gw and y_lower must be finite")
    if np.any(np.isnan(upper)):
        raise ValueError("y_upper must not be NaN")
    if np.any(lower > upper):
        raise ValueError("y_lower must not exceed y_upper")
    return r, lower, upper


def _ratio(numerator: float, denominator: float, family: str) -> float:
    """Return a one-parameter estimate, rejecting a zero denominator."""
    if denominator == 0.0:
        raise ValueError(f"{family} cannot be fit when every r_gw is zero")
    return numerator / denominator


def censored_log_likelihood(
    predicted: Sequence[float],
    y_lower: Sequence[float],
    y_upper: Sequence[float],
    sigma: float,
) -> float:
    """Censored normal log-likelihood of bounds on y given predictions h.

    ℓ = Σ_exact [log φ((yᵢ − hᵢ)/σ) − log σ]
        + Σ_censored log[Φ((uᵢ − hᵢ)/σ) − Φ((lᵢ − hᵢ)/σ)],

    where φ and Φ are the standard normal density and CDF, an exact slot
    has lᵢ = uᵢ = yᵢ, and Φ(∞) = 1 for a slot with no upper bound.  See
    ``docs/formulation.md``, Price curves, Fitting objective.
    """
    if not sigma > 0.0:
        raise ValueError(f"sigma must be positive (got {sigma})")
    h, lower, upper = _as_arrays(predicted, y_lower, y_upper)
    return _log_likelihood(h, lower, upper, sigma)


def _log_likelihood(
    predicted: _Array, lower: _Array, upper: _Array, sigma: float
) -> float:
    """``censored_log_likelihood`` on checked arrays."""
    exact = lower == upper
    z = (lower[exact] - predicted[exact]) / sigma
    total = float(np.sum(norm.logpdf(z))) - int(np.sum(exact)) * math.log(sigma)
    censored = ~exact
    a = (lower[censored] - predicted[censored]) / sigma
    b = (upper[censored] - predicted[censored]) / sigma
    return total + float(np.sum(_log_interval_probability(a, b)))


def _log_interval_probability(a: _Array, b: _Array) -> _Array:
    """log(Φ(b) − Φ(a)) for a < b, accurate in both tails.

    Where a > 0 both ends are in the upper tail, so use survival
    functions S = 1 − Φ: log(S(a) − S(b)) = log S(a) + log(1 − S(b)/S(a)).
    Otherwise use log Φ(b) + log(1 − Φ(a)/Φ(b)).  Each ratio is formed
    as the exponential of a log-difference, so neither CDF is subtracted
    after rounding to 1.  b = ∞ gives log S(b) = −∞ and the ratio 0.
    """
    out = np.empty_like(a)
    upper_tail = a > 0.0
    log_sa, log_sb = norm.logsf(a[upper_tail]), norm.logsf(b[upper_tail])
    out[upper_tail] = log_sa + np.log1p(-np.exp(log_sb - log_sa))
    log_fa, log_fb = norm.logcdf(a[~upper_tail]), norm.logcdf(b[~upper_tail])
    out[~upper_tail] = log_fb + np.log1p(-np.exp(log_fa - log_fb))
    return out


def _maximum_likelihood(
    curve: _Curve,
    theta_start: tuple[float, ...],
    r: _Array,
    lower: _Array,
    upper: _Array,
) -> tuple[tuple[float, ...], float]:
    """(θ, σ) maximising the censored log-likelihood of ``curve``.

    ``theta_start`` is the family's least-squares estimate on ``lower``.
    With no censored slot that is already the maximum: the log-likelihood
    is −SSE/(2σ²) − n·log σ + const, maximised over θ by least squares
    and then over σ by σ̂² = SSE/n.  So it is returned with that σ̂.

    Otherwise the mean negative log-likelihood is minimised with
    ``scipy.optimize.minimize`` (BFGS), starting from θ_start and σ₀, the
    RMS residual of θ_start against ``lower``.  The search runs over
    θⱼ / |θ_start,j| (or θⱼ where the start is 0) and log σ, so every
    coordinate starts near 1 whatever the units, and σ stays positive.
    See ``docs/formulation.md``, Price curves, Fitting objective.
    """
    start = np.asarray(theta_start, dtype=np.float64)
    sigma_start = math.sqrt(float(np.mean((lower - curve(start, r)) ** 2)))
    if np.all(lower == upper):
        return theta_start, sigma_start
    if sigma_start == 0.0:
        raise ValueError(
            "cannot start the noise scale: the least-squares start fits "
            "every lower bound exactly"
        )
    scale = np.where(start != 0.0, np.abs(start), 1.0)

    def objective(x: _Array) -> float:
        theta = x[:-1] * scale
        sigma = math.exp(float(x[-1]))
        return -_log_likelihood(curve(theta, r), lower, upper, sigma) / r.size

    result = minimize(objective, np.append(start / scale, math.log(sigma_start)))
    if not result.success:
        raise ValueError(f"censored likelihood did not converge: {result.message}")
    theta = tuple(float(t) for t in result.x[:-1] * scale)
    return theta, math.exp(float(result.x[-1]))


def _cubic(theta: _Array, r: _Array) -> _Array:
    """a·R³."""
    return float(theta[0]) * r**3


class CubicFit(BaseModel):
    """Fitted cubic h(R) = a·R³ with noise scale σ.

    Slope: h'(R) = 3a·R².  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a: float
    sigma: float = Field(ge=0.0)

    def predict(self, r_gw: float) -> float:
        """h(R) = a·R³."""
        return self.a * r_gw**3

    def slope(self, r_gw: float) -> float:
        """h'(R) = 3a·R²."""
        return 3.0 * self.a * r_gw**2


class Cubic:
    """Family h(R) = a·R³, fit by censored maximum likelihood.

    The start is least squares on the lower bounds: minimising
    Σ (lᵢ − a·Rᵢ³)² over a gives â = Σ lᵢRᵢ³ / Σ Rᵢ⁶.  With no censored
    slot this is the answer.  See ``docs/formulation.md``, Price curves.
    """

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> CubicFit:
        """Return the maximum-likelihood ``CubicFit``."""
        r, lower, upper = _as_arrays(r_gw, y_lower, y_upper)
        start = _ratio(float(np.sum(lower * r**3)), float(np.sum(r**6)), "Cubic")
        (a,), sigma = _maximum_likelihood(_cubic, (start,), r, lower, upper)
        return CubicFit(a=a, sigma=sigma)


def _signed_quadratic(theta: _Array, r: _Array) -> _Array:
    """a·R·|R|."""
    return float(theta[0]) * r * np.abs(r)


class SignedQuadraticFit(BaseModel):
    """Fitted signed quadratic h(R) = a·sgn(R)·R², equal to a·R·|R|.

    Slope: h'(R) = 2a·|R|.  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a: float
    sigma: float = Field(ge=0.0)

    def predict(self, r_gw: float) -> float:
        """h(R) = a·R·|R|."""
        return self.a * r_gw * abs(r_gw)

    def slope(self, r_gw: float) -> float:
        """h'(R) = 2a·|R|."""
        return 2.0 * self.a * abs(r_gw)


class SignedQuadratic:
    """Family h(R) = a·sgn(R)·R², fit by censored maximum likelihood.

    The start is least squares on the lower bounds: minimising
    Σ (lᵢ − a·Rᵢ|Rᵢ|)² over a gives â = Σ lᵢRᵢ|Rᵢ| / Σ Rᵢ⁴.  With no
    censored slot this is the answer.  See ``docs/formulation.md``,
    Price curves.
    """

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> SignedQuadraticFit:
        """Return the maximum-likelihood ``SignedQuadraticFit``."""
        r, lower, upper = _as_arrays(r_gw, y_lower, y_upper)
        start = _ratio(
            float(np.sum(lower * r * np.abs(r))),
            float(np.sum(r**4)),
            "SignedQuadratic",
        )
        (a,), sigma = _maximum_likelihood(_signed_quadratic, (start,), r, lower, upper)
        return SignedQuadraticFit(a=a, sigma=sigma)


def _cubic_offset(theta: _Array, r: _Array) -> _Array:
    """a₀ + a₁R + a₃R³."""
    a0, a1, a3 = (float(t) for t in theta)
    return a0 + a1 * r + a3 * r**3


class CubicOffsetFit(BaseModel):
    """Fitted cubic with offset and linear term h(R) = a₀ + a₁R + a₃R³.

    Slope: h'(R) = a₁ + 3a₃R².  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    a0: float
    a1: float
    a3: float
    sigma: float = Field(ge=0.0)

    def predict(self, r_gw: float) -> float:
        """h(R) = a₀ + a₁R + a₃R³."""
        return self.a0 + self.a1 * r_gw + self.a3 * r_gw**3

    def slope(self, r_gw: float) -> float:
        """h'(R) = a₁ + 3a₃R²."""
        return self.a1 + 3.0 * self.a3 * r_gw**2


class CubicOffset:
    """Family h(R) = a₀ + a₁R + a₃R³, fit by censored maximum likelihood.

    The start is ordinary least squares on the lower bounds: with design
    matrix X = [1, R, R³], it solves the normal equations XᵀX â = Xᵀl,
    via ``numpy.linalg.lstsq`` (SVD).  With no censored slot this is the
    answer.  See ``docs/formulation.md``, Price curves.
    """

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> CubicOffsetFit:
        """Return the maximum-likelihood ``CubicOffsetFit``."""
        r, lower, upper = _as_arrays(r_gw, y_lower, y_upper)
        design = np.column_stack([np.ones_like(r), r, r**3])
        coefficients, _residuals, rank, _singular = np.linalg.lstsq(design, lower)
        if rank < design.shape[1]:
            raise ValueError(
                "CubicOffset needs at least 3 distinct r_gw values to be fit"
            )
        start = tuple(float(c) for c in coefficients)
        (a0, a1, a3), sigma = _maximum_likelihood(_cubic_offset, start, r, lower, upper)
        return CubicOffsetFit(a0=a0, a1=a1, a3=a3, sigma=sigma)


class ExponentialFit(BaseModel):
    """Fitted exponential h(R) = α + β·(e^{γR} − 1)/γ, and α + βR at γ = 0.

    Slope: h'(R) = β·e^{γR}, so β is the slope at R = 0 and h(0) = α.
    See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    alpha: float
    beta: float
    gamma: float
    sigma: float = Field(ge=0.0)

    def predict(self, r_gw: float) -> float:
        """h(R) = α + β·(e^{γR} − 1)/γ, or α + βR at γ = 0."""
        if self.gamma == 0.0:
            return self.alpha + self.beta * r_gw
        return self.alpha + self.beta * math.expm1(self.gamma * r_gw) / self.gamma

    def slope(self, r_gw: float) -> float:
        """h'(R) = β·e^{γR}."""
        return self.beta * math.exp(self.gamma * r_gw)


def _growth(r: _Array, gamma: float) -> _Array:
    """(e^{γR} − 1)/γ, or R at γ = 0.

    ``expm1`` keeps it accurate for small γR, where e^{γR} − 1 would
    cancel, so it tends smoothly to R as γ → 0.
    """
    if gamma == 0.0:
        return r
    return np.expm1(gamma * r) / gamma


def _exponential(r: _Array, alpha: float, beta: float, gamma: float) -> _Array:
    """α + β·(e^{γR} − 1)/γ, vectorised for ``curve_fit``."""
    return alpha + beta * _growth(r, gamma)


def _exponential_theta(theta: _Array, r: _Array) -> _Array:
    """α + β·(e^{γR} − 1)/γ with θ = (α, β, γ)."""
    alpha, beta, gamma = (float(t) for t in theta)
    return _exponential(r, alpha, beta, gamma)


# Starting γ values, as multiples of 1 / (range of R): 21 log-spaced
# magnitudes from 0.1 to 10, each with both signs.  The straight line,
# γ = 0, is left out so that every start has a scale for γ; the fit
# can still reach it.
_GAMMA_GRID_SCALED = np.concatenate(
    [-np.logspace(-1.0, 1.0, 21), np.logspace(-1.0, 1.0, 21)]
)


class Exponential:
    """Family h(R) = α + β·(e^{γR} − 1)/γ, fit by censored maximum likelihood.

    Written this way, rather than α′ + β′·e^{γR}, the family contains its
    limit γ → 0, the straight line α + βR, and passes smoothly from
    concave (γ < 0) to convex (γ > 0).  With α′ + β′·e^{γR} that limit
    needs β′ → ±∞, and censored fits to the raw price head there.

    The start is nonlinear least squares on the lower bounds: it
    minimises Σ (lᵢ − h(Rᵢ))² with ``scipy.optimize.curve_fit``
    (Levenberg–Marquardt).  With no censored slot this is the answer.

    Levenberg–Marquardt itself needs starting values: for fixed γ the
    model is linear in (α, β), so they are solved exactly by least
    squares on the columns [1, (e^{γR} − 1)/γ].  This is done for each
    γ = c / (max R − min R) with c on ±logspace(−1, 1, 21), and the
    (α, β, γ) with the smallest sum of squared errors is used.
    See ``docs/formulation.md``, Price curves.
    """

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> ExponentialFit:
        """Return the maximum-likelihood ``ExponentialFit``."""
        r, lower, upper = _as_arrays(r_gw, y_lower, y_upper)
        if np.unique(r).size < 3:
            raise ValueError(
                "Exponential needs at least 3 distinct r_gw values to be fit"
            )
        grid_start = self._grid_start(r, lower)
        try:
            params, _covariance = curve_fit(_exponential, r, lower, p0=grid_start)
        except RuntimeError as error:
            raise ValueError(f"Exponential fit did not converge: {error}") from error
        start = tuple(float(p) for p in params)
        (alpha, beta, gamma), sigma = _maximum_likelihood(
            _exponential_theta, start, r, lower, upper
        )
        return ExponentialFit(alpha=alpha, beta=beta, gamma=gamma, sigma=sigma)

    @staticmethod
    def _grid_start(r: _Array, y: _Array) -> tuple[float, float, float]:
        """Best (α, β, γ) over the γ grid, with (α, β) solved exactly."""
        span = float(r.max() - r.min())
        best: tuple[float, float, float] | None = None
        best_sse = math.inf
        for gamma in _GAMMA_GRID_SCALED / span:
            design = np.column_stack([np.ones_like(r), _growth(r, float(gamma))])
            coefficients, _residuals, _rank, _singular = np.linalg.lstsq(design, y)
            sse = float(np.sum((y - design @ coefficients) ** 2))
            if sse < best_sse:
                best_sse = sse
                best = (float(coefficients[0]), float(coefficients[1]), float(gamma))
        if best is None:
            raise ValueError("Exponential found no finite starting values")
        return best


class IsotonicFit(BaseModel):
    """Fitted non-decreasing curve, linear between knots, with noise scale σ.

    ``predict`` interpolates linearly between the knots (Rⱼ, vⱼ) and is
    flat beyond the first and last knot.  ``slope`` is the finite
    difference over the segment containing R,
    (vⱼ₊₁ − vⱼ) / (Rⱼ₊₁ − Rⱼ) for Rⱼ ≤ R < Rⱼ₊₁, and 0 outside the
    knots.  See ``docs/formulation.md``, Price curves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    knots_r_gw: tuple[float, ...]
    values: tuple[float, ...]
    sigma: float = Field(ge=0.0)

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


# EM for Isotonic stops once a round raises the mean log-likelihood per
# slot by less than this, and gives up after _EM_MAX_ROUNDS rounds.
_EM_TOLERANCE = 1e-10
_EM_MAX_ROUNDS = 10_000


class Isotonic:
    """Best non-decreasing fit, by censored maximum likelihood using EM.

    The curve is h(Rᵢ) at each distinct residual load, constrained so
    h(Rᵢ) ≤ h(Rⱼ) whenever Rᵢ ≤ Rⱼ, and σ is fitted with it.

    Slots above the highest R with a finite upper bound are left out.
    If the top slots are all censored [lᵢ, ∞), raising h there makes
    every one of them more likely, so the likelihood has no maximum.
    The fitted curve is flat beyond its last knot, so it understates
    h there.

    EM (expectation–maximisation) alternates two steps from the start:
    least squares on the lower bounds, with σ the RMS residual.

    - E-step: each censored slot gets the mean mᵢ and variance vᵢ of
      y ~ N(h(Rᵢ), σ²) truncated to [lᵢ, uᵢ].  An exact slot has
      mᵢ = yᵢ, vᵢ = 0.
    - M-step: h ← the least-squares non-decreasing fit to the mᵢ, and
      σ² ← (1/n) Σ [vᵢ + (mᵢ − h(Rᵢ))²].

    Each round never lowers the censored log-likelihood ℓ.  It stops
    when a round raises ℓ/n by less than ``_EM_TOLERANCE`` (1e-10), and
    raises ``ValueError`` after ``_EM_MAX_ROUNDS`` (10 000) rounds.  With
    no censored slot the start is already the answer.

    The least-squares fit uses ``scipy.optimize.isotonic_regression``
    (pool adjacent violators), after merging tied Rᵢ into their mean,
    weighted by count.  The solution is constant on blocks of
    neighbouring R; each block becomes one knot at its count-weighted
    mean R and its fitted value, and ``IsotonicFit`` interpolates
    between knots.  See ``docs/formulation.md``, Price curves, Isotonic.
    """

    def fit(
        self,
        r_gw: Sequence[float],
        y_lower: Sequence[float],
        y_upper: Sequence[float],
    ) -> IsotonicFit:
        """Return the maximum-likelihood ``IsotonicFit``."""
        r, lower, upper = _as_arrays(r_gw, y_lower, y_upper)
        bounded = np.isfinite(upper)
        if not np.any(bounded):
            raise ValueError(
                "Isotonic needs at least one slot with a finite upper bound"
            )
        keep = r <= np.max(r[bounded])
        r, lower, upper = r[keep], lower[keep], upper[keep]
        r_unique, inverse, counts = np.unique(
            r, return_inverse=True, return_counts=True
        )
        values, blocks, sigma = _isotonic_maximum_likelihood(
            lower, upper, inverse, counts
        )
        knots: list[float] = []
        knot_values: list[float] = []
        for start, end in itertools.pairwise(blocks):
            block_counts = counts[start:end]
            knots.append(float(np.average(r_unique[start:end], weights=block_counts)))
            knot_values.append(float(values[start]))
        return IsotonicFit(
            knots_r_gw=tuple(knots), values=tuple(knot_values), sigma=sigma
        )


def _isotonic_least_squares(
    y: _Array, inverse: NDArray[np.intp], counts: NDArray[np.intp]
) -> tuple[_Array, NDArray[np.intp]]:
    """Non-decreasing least-squares fit of y over the distinct R.

    ``inverse`` maps each slot to its distinct R and ``counts`` says how
    many slots share it.  Returns the fitted value at each distinct R and
    the start of each constant block (with the end appended).
    """
    y_mean = np.bincount(inverse, weights=y) / counts
    result = isotonic_regression(y_mean, weights=counts)
    return result.x, result.blocks


def _isotonic_maximum_likelihood(
    lower: _Array,
    upper: _Array,
    inverse: NDArray[np.intp],
    counts: NDArray[np.intp],
) -> tuple[_Array, NDArray[np.intp], float]:
    """EM for ``Isotonic``: (values at each distinct R, blocks, σ)."""
    values, blocks = _isotonic_least_squares(lower, inverse, counts)
    sigma = math.sqrt(float(np.mean((lower - values[inverse]) ** 2)))
    censored = lower < upper
    if not np.any(censored):
        return values, blocks, sigma
    if sigma == 0.0:
        raise ValueError(
            "cannot start the noise scale: the least-squares start fits "
            "every lower bound exactly"
        )
    n = lower.size
    log_likelihood = _log_likelihood(values[inverse], lower, upper, sigma) / n
    for _ in range(_EM_MAX_ROUNDS):
        mean = lower.copy()
        mean[censored], variance = _truncated_normal_moments(
            values[inverse][censored], sigma, lower[censored], upper[censored]
        )
        values, blocks = _isotonic_least_squares(mean, inverse, counts)
        h = values[inverse]
        sigma = math.sqrt(
            (float(np.sum(variance)) + float(np.sum((mean - h) ** 2))) / n
        )
        previous = log_likelihood
        log_likelihood = _log_likelihood(h, lower, upper, sigma) / n
        if log_likelihood - previous < _EM_TOLERANCE:
            return values, blocks, sigma
    raise ValueError(f"Isotonic EM did not converge in {_EM_MAX_ROUNDS} rounds")


def _truncated_normal_moments(
    mu: _Array, sigma: float, lower: _Array, upper: _Array
) -> tuple[_Array, _Array]:
    """Mean and variance of N(μ, σ²) truncated to [l, u], for l < u.

    With a = (l − μ)/σ, b = (u − μ)/σ and Z = Φ(b) − Φ(a):

        mean     = μ + σ·(φ(a) − φ(b))/Z
        variance = σ²·[1 + (a·φ(a) − b·φ(b))/Z − ((φ(a) − φ(b))/Z)²],

    with b·φ(b) = 0 at b = ∞.  Each φ/Z is the exponential of a
    log-difference, so it stays finite far in the tails.  This is what
    ``scipy.stats.truncnorm.stats`` returns, but over 100 times faster
    on real data, which matters because EM calls it every round.
    """
    a = (lower - mu) / sigma
    b = (upper - mu) / sigma
    log_z = _log_interval_probability(a, b)
    ratio_a = np.exp(norm.logpdf(a) - log_z)
    ratio_b = np.exp(norm.logpdf(b) - log_z)
    shift = ratio_a - ratio_b
    b_ratio_b = np.zeros_like(b)
    finite = np.isfinite(b)
    b_ratio_b[finite] = b[finite] * ratio_b[finite]
    spread = 1.0 + a * ratio_a - b_ratio_b - shift**2
    return mu + sigma * shift, sigma**2 * np.maximum(spread, 0.0)


FAMILIES: dict[str, PriceCurve] = {
    "cubic": Cubic(),
    "signed_quadratic": SignedQuadratic(),
    "cubic_offset": CubicOffset(),
    "exponential": Exponential(),
    "isotonic": Isotonic(),
}
