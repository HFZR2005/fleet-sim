"""Target transforms that extract the dependent variable from observations.

A ``Target`` turns a ``PriceObservation`` into a scalar ``y`` that a
curve family fits against residual load, and reverses the transform to
recover the price.  No target knows about curve families.

``per_year`` controls whether the fitting loop fits one curve per year
or pools all years together.

See ``docs/architecture.md``, Price curves.
"""

from __future__ import annotations

from typing import Protocol

from fleet_sim.prices.dataset import PriceObservation


class Target(Protocol):
    """Extract and reverse the dependent variable for a curve fit."""

    @property
    def per_year(self) -> bool:
        """True when the model should be fit separately for each year."""
        ...

    def to_target(self, obs: PriceObservation) -> float:
        """Extract the value the curve family will fit."""
        ...

    def to_price(self, y: float, obs: PriceObservation) -> float:
        """Recover the wholesale price from a predicted ``y``."""
        ...


class RawTarget:
    """Identity transform: y = wholesale price."""

    def __init__(self, *, per_year: bool) -> None:
        self._per_year = per_year

    @property
    def per_year(self) -> bool:
        return self._per_year

    def to_target(self, obs: PriceObservation) -> float:
        return obs.wholesale_price_gbp_per_mwh

    def to_price(self, y: float, obs: PriceObservation) -> float:
        _ = obs
        return y


class FuelAdjustedTarget:
    """Fuel-adjusted transform: y = π / k.

    The model is π = k·h(R) + ε, so dividing by the fuel cost k leaves
    the dimensionless curve h(R) to fit.  k must be positive, or y is
    undefined or flips sign.  See ``docs/formulation.md``, Price curves.
    """

    def __init__(self, *, per_year: bool = False) -> None:
        self._per_year = per_year

    @property
    def per_year(self) -> bool:
        return self._per_year

    def to_target(self, obs: PriceObservation) -> float:
        """y = π / k."""
        return obs.wholesale_price_gbp_per_mwh / _positive_fuel_cost(obs)

    def to_price(self, y: float, obs: PriceObservation) -> float:
        """π = k·y."""
        return y * _positive_fuel_cost(obs)


def _positive_fuel_cost(obs: PriceObservation) -> float:
    """Return the fuel cost k, rejecting k <= 0."""
    k = obs.fuel_cost_gbp_per_mwh
    if k <= 0:
        raise ValueError(
            f"fuel cost must be positive to divide by it "
            f"(got {k} at {obs.settlement_start.isoformat()})"
        )
    return k


def raw_pooled() -> RawTarget:
    """Raw wholesale price, all years pooled."""
    return RawTarget(per_year=False)


def raw_per_year() -> RawTarget:
    """Raw wholesale price, fit separately per year."""
    return RawTarget(per_year=True)


def fuel_adjusted() -> FuelAdjustedTarget:
    """Fuel-adjusted price, all years pooled."""
    return FuelAdjustedTarget(per_year=False)


TARGETS: dict[str, Target] = {
    "raw_pooled": raw_pooled(),
    "raw_per_year": raw_per_year(),
    "fuel_adjusted": fuel_adjusted(),
}
