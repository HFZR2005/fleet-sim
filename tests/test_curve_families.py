"""Tests for the price-curve families."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest
from numpy.typing import NDArray
from scipy.optimize import curve_fit

from fleet_sim.prices.curves import (
    Cubic,
    CubicFit,
    CubicOffset,
    CubicOffsetFit,
    Exponential,
    ExponentialFit,
    Isotonic,
    IsotonicFit,
    SignedQuadratic,
    SignedQuadraticFit,
    censored_log_likelihood,
)

_Family = Cubic | SignedQuadratic | CubicOffset | Exponential
_Fit = CubicFit | SignedQuadraticFit | CubicOffsetFit | ExponentialFit
_Array = NDArray[np.float64]

_SIGMA = 2.0
"""Noise scale of the synthetic data, except the cubic's."""

# The cubic's noise is large next to its range (0.5 to 256), so censoring
# the top of y selects on noise as well as on R.
_CUBIC = (Cubic(), CubicFit(a=0.004, sigma=20.0), (5.0, 40.0))

# Each case: a family, the fit holding the true parameters, and the
# residual-load range (GW) to draw synthetic data from.
_CASES: list[tuple[_Family, _Fit, tuple[float, float]]] = [
    _CUBIC,
    (SignedQuadratic(), SignedQuadraticFit(a=0.12, sigma=_SIGMA), (-10.0, 40.0)),
    (
        CubicOffset(),
        CubicOffsetFit(a0=30.0, a1=1.5, a3=0.003, sigma=_SIGMA),
        (-10.0, 40.0),
    ),
    (
        Exponential(),
        # 25 + 0.4·(e^{0.08R} − 1)/0.08 = 20 + 5·e^{0.08R}
        ExponentialFit(alpha=25.0, beta=0.4, gamma=0.08, sigma=_SIGMA),
        (-10.0, 40.0),
    ),
]

# A non-decreasing piecewise-linear curve, used as truth for Isotonic.
_ISOTONIC_TRUTH = IsotonicFit(
    knots_r_gw=(-10.0, 10.0, 25.0, 40.0), values=(0.0, 20.0, 30.0, 120.0)
)


def _synthetic(
    truth: _Fit | IsotonicFit, r_range: tuple[float, float], sigma: float
) -> tuple[_Array, _Array]:
    """10 000 seeded points from ``truth`` with N(0, σ²) noise."""
    rng = np.random.default_rng(seed=70)
    r = rng.uniform(*r_range, size=10_000)
    y = np.array([truth.predict(float(x)) for x in r]) + rng.normal(0.0, sigma, r.size)
    return r, y


def _censor_top_quarter(y: _Array) -> tuple[_Array, _Array]:
    """Right-censor y above its 75th percentile c: bounds become [c, ∞)."""
    c = float(np.quantile(y, 0.75))
    lower = np.minimum(y, c)
    upper = np.where(y > c, math.inf, y)
    return lower, upper


def _parameters(fit: _Fit) -> dict[str, float]:
    """The curve's parameters, without σ."""
    return {k: v for k, v in fit.model_dump().items() if k != "sigma"}


def test_censored_log_likelihood_hand_worked() -> None:
    """One slot of each kind, h = 0 and σ = 2, by hand.

    Exact y = 0:       log φ(0) − log 2 = −½·log 2π − log 2 = −1.61209
    y ≥ 0:             log P(Z ≥ 0) = log 0.5             = −0.69315
    −2 ≤ y ≤ 2:        log P(−1 ≤ Z ≤ 1) = log 0.682689   = −0.38172
    Total                                                 = −2.68695
    """
    total = censored_log_likelihood(
        [0.0, 0.0, 0.0], [0.0, 0.0, -2.0], [0.0, math.inf, 2.0], sigma=2.0
    )
    assert total == pytest.approx(-2.68695, abs=1e-5)


def test_censored_log_likelihood_is_finite_far_in_the_tail() -> None:
    """y ∈ [40, 41] with h = 0, σ = 1: Φ(41) − Φ(40) rounds to 0 in floats.

    log P = log S(40) + log(1 − S(41)/S(40)) ≈ log S(40) = −804.608.
    """
    total = censored_log_likelihood([0.0], [40.0], [41.0], sigma=1.0)
    assert total == pytest.approx(-804.608, abs=1e-3)


def test_cubic_hand_worked() -> None:
    """Cubic fit on two exact points, by hand.

    R = [1, 2], y = [2, 16].
    â = Σ yR³ / Σ R⁶ = (2·1 + 16·8) / (1 + 64) = 130 / 65 = 2.
    The fit is exact, so σ̂ = √(SSE / n) = 0.
    predict(3) = 2·27 = 54.  slope(3) = 3·2·9 = 54.
    """
    fitted = Cubic().fit([1.0, 2.0], [2.0, 16.0], [2.0, 16.0])
    assert fitted.a == pytest.approx(2.0)
    assert fitted.sigma == pytest.approx(0.0)
    assert fitted.predict(3.0) == pytest.approx(54.0)
    assert fitted.slope(3.0) == pytest.approx(54.0)


def test_exponential_at_zero_gamma_is_a_line() -> None:
    """γ = 0 is the limit of α + β·(e^{γR} − 1)/γ: the line α + βR.

    α = 1, β = 2: predict(3) = 1 + 2·3 = 7, slope(3) = β·e⁰ = 2.
    Just off zero, γ = 1e-9, gives the same to 1e-6.
    """
    line = ExponentialFit(alpha=1.0, beta=2.0, gamma=0.0, sigma=0.0)
    near = ExponentialFit(alpha=1.0, beta=2.0, gamma=1e-9, sigma=0.0)
    assert line.predict(3.0) == pytest.approx(7.0)
    assert line.slope(3.0) == pytest.approx(2.0)
    assert near.predict(3.0) == pytest.approx(7.0, abs=1e-6)


def test_isotonic_hand_worked() -> None:
    """Isotonic fit on four points, by hand.

    R = [1, 2, 3, 4], y = [1, 3, 2, 4].  3 > 2 violates order, so PAVA
    pools them to (3 + 2) / 2 = 2.5.  Blocks: {1}, {2, 3}, {4}.
    Knots at block mean R: (1, 1), (2.5, 2.5), (4, 4).
    predict(2) = 1 + (2 − 1)·(2.5 − 1)/(2.5 − 1) = 2, slope(2) = 1.
    Beyond the last knot: predict(10) = 4, slope(10) = 0.
    """
    y = [1.0, 3.0, 2.0, 4.0]
    fitted = Isotonic().fit([1.0, 2.0, 3.0, 4.0], y, y)
    assert fitted.knots_r_gw == pytest.approx((1.0, 2.5, 4.0))
    assert fitted.values == pytest.approx((1.0, 2.5, 4.0))
    assert fitted.predict(2.0) == pytest.approx(2.0)
    assert fitted.slope(2.0) == pytest.approx(1.0)
    assert fitted.predict(10.0) == pytest.approx(4.0)
    assert fitted.slope(10.0) == 0.0


def _linear_least_squares(
    *features: Callable[[_Array], _Array],
) -> Callable[[_Array, _Array], tuple[_Array, _Array]]:
    """Reference LS: (θ̂, fitted values) from ``numpy.linalg.lstsq``."""

    def solve(r: _Array, y: _Array) -> tuple[_Array, _Array]:
        design = np.column_stack([f(r) for f in features])
        theta = np.linalg.lstsq(design, y)[0]
        return theta, design @ theta

    return solve


def _exponential_least_squares(r: _Array, y: _Array) -> tuple[_Array, _Array]:
    """Reference LS for α + β·(e^{γR} − 1)/γ, by ``curve_fit`` from the truth."""

    def h(x: _Array, alpha: float, beta: float, gamma: float) -> _Array:
        return alpha + beta * np.expm1(gamma * x) / gamma

    theta = curve_fit(h, r, y, p0=(25.0, 0.4, 0.08))[0]
    return theta, h(r, *theta)


_LEAST_SQUARES = [
    _linear_least_squares(lambda r: r**3),
    _linear_least_squares(lambda r: r * np.abs(r)),
    _linear_least_squares(np.ones_like, lambda r: r, lambda r: r**3),
    _exponential_least_squares,
]


@pytest.mark.parametrize(
    ("family", "truth", "r_range", "least_squares"),
    [(*case, ls) for case, ls in zip(_CASES, _LEAST_SQUARES, strict=True)],
)
def test_no_censored_slots_gives_least_squares(
    family: _Family,
    truth: _Fit,
    r_range: tuple[float, float],
    least_squares: Callable[[_Array, _Array], tuple[_Array, _Array]],
) -> None:
    """With every slot exact, ML is least squares and σ̂² = SSE / n."""
    r, y = _synthetic(truth, r_range, truth.sigma)
    theta, fitted_y = least_squares(r, y)

    fitted = family.fit(r.tolist(), y.tolist(), y.tolist())

    assert list(_parameters(fitted).values()) == pytest.approx(theta.tolist())
    assert fitted.sigma == pytest.approx(math.sqrt(np.mean((y - fitted_y) ** 2)))


@pytest.mark.parametrize(("family", "truth", "r_range"), _CASES[1:])
def test_censored_fit_recovers_known_parameters(
    family: _Family, truth: _Fit, r_range: tuple[float, float]
) -> None:
    """With the top quarter of y censored, the fit still recovers the truth."""
    r, y = _synthetic(truth, r_range, truth.sigma)
    lower, upper = _censor_top_quarter(y)

    fitted = family.fit(r.tolist(), lower.tolist(), upper.tolist())

    expected = truth.model_dump()
    actual = fitted.model_dump()
    assert actual.keys() == expected.keys()
    for name, value in expected.items():
        assert actual[name] == pytest.approx(value, rel=0.05), name


def test_cubic_censored_fit_recovers_what_dropping_censored_slots_biases_low() -> None:
    """Censoring the top quarter of y from a known cubic.

    The censored fit recovers a and σ within 5%.  Fitting the exact slots
    alone leaves out the highest y, so â falls below the truth and
    outside the same tolerance.
    """
    family, truth, r_range = _CUBIC
    r, y = _synthetic(truth, r_range, truth.sigma)
    lower, upper = _censor_top_quarter(y)
    exact = lower == upper

    censored = family.fit(r.tolist(), lower.tolist(), upper.tolist())
    dropped = family.fit(
        r[exact].tolist(), lower[exact].tolist(), upper[exact].tolist()
    )

    assert censored.a == pytest.approx(truth.a, rel=0.05)
    assert censored.sigma == pytest.approx(truth.sigma, rel=0.05)
    assert dropped.a < truth.a
    assert dropped.a != pytest.approx(truth.a, rel=0.05)


def test_isotonic_recovers_known_curve() -> None:
    """Isotonic fit of noisy data from a non-decreasing curve.

    Its parameters are knots chosen from the data, so compare predictions
    on an interior grid instead, and check the fit never decreases.
    """
    r, y = _synthetic(_ISOTONIC_TRUTH, (-10.0, 40.0), _SIGMA)

    fitted = Isotonic().fit(r.tolist(), y.tolist(), y.tolist())

    assert np.all(np.diff(fitted.values) >= 0.0)
    for r_gw in np.linspace(-5.0, 35.0, 9):
        expected = _ISOTONIC_TRUTH.predict(float(r_gw))
        assert fitted.predict(float(r_gw)) == pytest.approx(expected, abs=2.0)


@pytest.mark.parametrize(
    "fitted", [truth for _, truth, _ in _CASES] + [_ISOTONIC_TRUTH]
)
@pytest.mark.parametrize("r_gw", [-7.5, 0.5, 22.0])
def test_slope_matches_finite_difference(
    fitted: _Fit | IsotonicFit, r_gw: float
) -> None:
    """Slope agrees with a central difference of predict (off any knot)."""
    h = 1e-4
    numeric = (fitted.predict(r_gw + h) - fitted.predict(r_gw - h)) / (2 * h)
    assert fitted.slope(r_gw) == pytest.approx(numeric, rel=1e-6)


@pytest.mark.parametrize(
    ("family", "r_gw", "lower", "upper", "message"),
    [
        (Cubic(), [], [], [], "no observations"),
        (Cubic(), [1.0, 2.0], [1.0], [1.0], "same length"),
        (Cubic(), [1.0, 2.0], [1.0, 2.0], [1.0], "same length"),
        (Cubic(), [1.0], [math.nan], [math.nan], "must be finite"),
        (Cubic(), [1.0], [math.inf], [math.inf], "must be finite"),
        (Cubic(), [1.0], [1.0], [math.nan], "must not be NaN"),
        (Cubic(), [1.0], [2.0], [1.0], "must not exceed"),
        (Cubic(), [0.0, 0.0], [1.0, 2.0], [1.0, 2.0], "every r_gw is zero"),
        (SignedQuadratic(), [0.0], [1.0], [1.0], "every r_gw is zero"),
        (
            CubicOffset(),
            [1.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0],
            "3 distinct",
        ),
        (
            Exponential(),
            [1.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0],
            "3 distinct",
        ),
    ],
)
def test_fit_rejects_invalid_data(
    family: _Family,
    r_gw: list[float],
    lower: list[float],
    upper: list[float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        family.fit(r_gw, lower, upper)


@pytest.mark.parametrize(
    ("knots", "values", "message"),
    [
        ((1.0, 2.0), (1.0,), "same length"),
        ((), (), "at least one knot"),
        ((1.0, 1.0), (1.0, 2.0), "strictly increasing"),
        ((1.0, 2.0), (2.0, 1.0), "non-decreasing"),
    ],
)
def test_isotonic_fit_rejects_invalid_knots(
    knots: tuple[float, ...], values: tuple[float, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        IsotonicFit(knots_r_gw=knots, values=values)
