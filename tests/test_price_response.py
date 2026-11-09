"""Tests for the anchored price response."""

from __future__ import annotations

from datetime import date

import pytest

from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.prices.curves import (
    CubicFit,
    CubicOffsetFit,
    ExponentialFit,
    FittedCurve,
    IsotonicFit,
    SignedQuadraticFit,
)
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.response import price_response
from fleet_sim.prices.targets import TARGETS

# 15 June 2024 is BST and not a clock change: slot i starts at London
# 00:00 + 30·i minutes, so slot 32 (16:00) is in the 4–7 pm peak.
# Region C: multiplier 2, peak adder 12 p/kWh, cap 95.23 p/kWh exc VAT.
_DAY = date(2024, 6, 15)
_PEAK_SLOT = 32
_VAT = 1.05


def _day(
    loads: list[float],
    prices: list[float],
    *,
    cost: float,
    on: date = _DAY,
    censored: dict[int, tuple[float, float | None]] | None = None,
) -> PriceDataset:
    """One day's slots; ``censored`` maps a slot to its price bounds."""
    bounds = censored or {}
    observations = []
    for i, stamp in enumerate(settlement_periods_utc(on)):
        lower, upper = bounds.get(i, (prices[i], None))
        observations.append(
            PriceObservation(
                settlement_start=stamp,
                wholesale_price_gbp_per_mwh=lower,
                censored=i in bounds,
                wholesale_upper_gbp_per_mwh=upper,
                residual_load_gw=loads[i],
                fuel_cost_gbp_per_mwh=cost,
                year=stamp.year,
            )
        )
    return PriceDataset(observations=observations, drops=[])


def test_hand_worked_cubic_fuel_adjusted() -> None:
    # h(R) = 0.001·R³, k = 50, R = 20, b = 2, π = 150 £/MWh in every slot.
    # h(20) = 8, h(22) = 10.648, so k·Δh = 50 · 2.648 = 132.4 £/MWh.
    # π′ = 150 + 132.4 = 282.4 £/MWh = 28.24 p/kWh.
    # Off-peak: 28.24 · 2 = 56.48 exc VAT (under the cap) → 59.304 inc VAT.
    # Peak:     56.48 + 12 = 68.48 exc VAT                → 71.904 inc VAT.
    day = _day([20.0] * 48, [150.0] * 48, cost=50.0)

    series = price_response(
        day,
        CubicFit(a=0.001, sigma=1.0),
        TARGETS["fuel_adjusted"],
        [2.0] * 48,
        region="C",
    )

    assert series.day == _DAY
    assert series.region == "C"
    assert series.price_p_per_kwh[0] == pytest.approx(59.304)
    assert series.price_p_per_kwh[_PEAK_SLOT] == pytest.approx(71.904)


def test_zero_added_load_returns_historical_prices() -> None:
    # π = 150 off-peak → 15 · 2 · 1.05 = 31.5 p/kWh.
    # π = 150 at peak  → (30 + 12) · 1.05 = 44.1 p/kWh.
    # π = −20 off-peak → −2 · 2 · 1.05 = −4.2 p/kWh.
    # π = 600 off-peak → 120 exc VAT is over the cap → 95.23 · 1.05.
    # The curve is steep at R = 30, so any leak of h into the price would show.
    prices = [150.0] * 48
    prices[1] = -20.0
    prices[2] = 600.0
    day = _day([30.0] * 48, prices, cost=50.0)

    series = price_response(
        day,
        CubicFit(a=0.01, sigma=1.0),
        TARGETS["fuel_adjusted"],
        [0.0] * 48,
        region="C",
    )

    assert series.price_p_per_kwh[0] == pytest.approx(31.5)
    assert series.price_p_per_kwh[_PEAK_SLOT] == pytest.approx(44.1)
    assert series.price_p_per_kwh[1] == pytest.approx(-4.2)
    assert series.price_p_per_kwh[2] == pytest.approx(95.23 * _VAT)


@pytest.mark.parametrize(
    "fitted",
    [
        CubicFit(a=0.001, sigma=1.0),
        SignedQuadraticFit(a=0.01, sigma=1.0),
        CubicOffsetFit(a0=1.0, a1=0.05, a3=0.0005, sigma=1.0),
        ExponentialFit(alpha=1.0, beta=0.05, gamma=0.08, sigma=1.0),
        IsotonicFit(knots_r_gw=(0.0, 10.0, 30.0), values=(0.5, 1.0, 4.0), sigma=1.0),
    ],
    ids=lambda f: type(f).__name__,
)
def test_adding_load_never_lowers_the_price(fitted: FittedCurve) -> None:
    # R runs from −5 to 42 GW across the day and b from 0 to 4.7 GW, so the
    # shifts cross zero load, isotonic knots and (for high π) the cap.
    loads = [-5.0 + i for i in range(48)]
    prices = [20.0 * i - 100.0 for i in range(48)]
    added = [0.1 * i for i in range(48)]
    day = _day(loads, prices, cost=50.0)
    target = TARGETS["fuel_adjusted"]

    before = price_response(day, fitted, target, [0.0] * 48, region="C")
    after = price_response(day, fitted, target, added, region="C")

    for old, new in zip(before.price_p_per_kwh, after.price_p_per_kwh, strict=True):
        assert new >= old


@pytest.mark.parametrize(
    ("lower", "upper", "anchor"),
    [
        (200.0, None, 200.0),  # prediction 160 below the bounds → π⁻
        (100.0, 300.0, 160.0),  # prediction inside the bounds → prediction
        (100.0, 120.0, 120.0),  # prediction above the bounds → π⁺
    ],
)
def test_censored_slot_anchors_on_clipped_prediction(
    lower: float, upper: float | None, anchor: float
) -> None:
    # h(R) = 0.001·R³, k = 20, R = 20, b = 2.
    # Prediction k·h(20) = 20 · 8 = 160 £/MWh.
    # Shift k·[h(22) − h(20)] = 20 · 2.648 = 52.96 £/MWh.
    # Slot 0 is off-peak: rate = (anchor + 52.96) / 10 · 2 · 1.05, e.g.
    # (200 + 52.96) / 10 · 2 · 1.05 = 53.1216 p/kWh.
    day = _day([20.0] * 48, [150.0] * 48, cost=20.0, censored={0: (lower, upper)})

    series = price_response(
        day,
        CubicFit(a=0.001, sigma=1.0),
        TARGETS["fuel_adjusted"],
        [2.0] * 48,
        region="C",
    )

    expected = (anchor + 52.96) / 10 * 2 * _VAT
    assert series.price_p_per_kwh[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("on", "added", "message"),
    [
        (date(2022, 11, 15), 48, "Energy Price Guarantee"),
        (_DAY, 47, "one value per slot"),
    ],
)
def test_rejected_inputs(on: date, added: int, message: str) -> None:
    day = _day([20.0] * 48, [150.0] * 48, cost=50.0, on=on)

    with pytest.raises(ValueError, match=message):
        price_response(
            day,
            CubicFit(a=0.001, sigma=1.0),
            TARGETS["fuel_adjusted"],
            [0.0] * added,
            region="C",
        )
