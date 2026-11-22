"""The price-curve parameters file, and loading a model back from it.

``scripts/fit_price_curves.py finalise`` writes one ``PriceParameters``
to ``calibration/price_curves.json``: each chosen model's target, family
and fitted parameters, its result on the final-test year, and where the
numbers came from.  Later milestones read a model back with
``load_price_model`` instead of refitting.

A pooled target has one curve.  A per-year target has one curve for each
year it was fitted to, so a run over a given year uses that year's curve.

See ``docs/architecture.md``, Price curves.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

from fleet_sim.prices.config import FuelCostConfig, SplitSpec
from fleet_sim.prices.curves import (
    FAMILIES,
    CubicFit,
    CubicOffsetFit,
    ExponentialFit,
    FittedCurve,
    IsotonicFit,
    SignedQuadraticFit,
)
from fleet_sim.prices.evaluation import FitResult
from fleet_sim.prices.targets import TARGETS, Target

CurveParameters = dict[str, JsonValue]
"""A fitted curve's fields, σ included, as saved in the file."""

_PARSERS: dict[str, Callable[[CurveParameters], FittedCurve]] = {
    "cubic": CubicFit.model_validate,
    "signed_quadratic": SignedQuadraticFit.model_validate,
    "cubic_offset": CubicOffsetFit.model_validate,
    "exponential": ExponentialFit.model_validate,
    "isotonic": IsotonicFit.model_validate,
}


class Provenance(BaseModel):
    """Where the parameters came from.

    ``git_dirty`` is True when tracked files differed from ``git_commit``
    at the time of the run.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_start: date
    data_end: date
    agile_regions: list[str]
    splits: SplitSpec
    fuel_cost: FuelCostConfig
    config_sha256: str
    git_commit: str
    git_dirty: bool
    run_date: date


class SavedModel(BaseModel):
    """One chosen model: its curves and its final-test result.

    ``curve`` is set for a pooled target and ``curves_by_year`` for a
    per-year target; the other is None.  The curves' fields must match
    the family's fitted model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    target: str
    family: str
    curve: CurveParameters | None
    curves_by_year: dict[int, CurveParameters] | None
    final_test: FitResult

    @model_validator(mode="after")
    def _consistent(self) -> SavedModel:
        if self.name != f"{self.target}/{self.family}":
            raise ValueError(
                f"name {self.name!r} must be '{self.target}/{self.family}'"
            )
        if self.target not in TARGETS:
            raise ValueError(f"unknown target {self.target!r}")
        if self.family not in FAMILIES:
            raise ValueError(f"unknown family {self.family!r}")
        if TARGETS[self.target].per_year:
            if self.curve is not None or not self.curves_by_year:
                raise ValueError(
                    f"{self.name} is per-year: set curves_by_year, not curve"
                )
            curves = list(self.curves_by_year.values())
        else:
            if self.curve is None or self.curves_by_year is not None:
                raise ValueError(
                    f"{self.name} is pooled: set curve, not curves_by_year"
                )
            curves = [self.curve]
        for parameters in curves:
            _PARSERS[self.family](parameters)
        return self


class PriceParameters(BaseModel):
    """The contents of the parameters file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provenance: Provenance
    models: list[SavedModel]

    @model_validator(mode="after")
    def _distinct_names(self) -> PriceParameters:
        names = [m.name for m in self.models]
        if len(set(names)) != len(names):
            raise ValueError(f"model names must be distinct (got {names})")
        return self


class PriceModel:
    """A fitted price-curve model read from the parameters file.

    ``curves`` is one curve for a pooled model, or a curve per year.
    """

    def __init__(
        self, name: str, target: Target, curves: FittedCurve | dict[int, FittedCurve]
    ) -> None:
        self.name = name
        self.target = target
        self._curves = curves

    def curve_for(self, year: int) -> FittedCurve:
        """The curve to use for ``year``.

        A pooled model has one curve for every year.  A per-year model
        has a curve only for the years it was fitted to.
        """
        if not isinstance(self._curves, dict):
            return self._curves
        if year not in self._curves:
            raise KeyError(
                f"{self.name} has no curve for {year} (years: {sorted(self._curves)})"
            )
        return self._curves[year]


def saved_curve(fitted: FittedCurve) -> CurveParameters:
    """A fitted curve's fields, for ``SavedModel``."""
    if not isinstance(fitted, BaseModel):
        raise TypeError(f"cannot save a {type(fitted).__name__}: not a model")
    return fitted.model_dump(mode="json")


def load_price_model(path: Path, name: str) -> PriceModel:
    """Read the model called ``name`` (``target/family``) from ``path``."""
    if not path.is_file():
        raise FileNotFoundError(f"parameters file not found: {path}")
    try:
        parameters = PriceParameters.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except ValidationError as exc:
        raise ValueError(f"parameters file {path} is invalid\n{exc}") from exc
    for saved in parameters.models:
        if saved.name == name:
            parse = _PARSERS[saved.family]
            curves = (
                parse(saved.curve)
                if saved.curve is not None
                else {y: parse(c) for y, c in (saved.curves_by_year or {}).items()}
            )
            return PriceModel(saved.name, TARGETS[saved.target], curves)
    names = [m.name for m in parameters.models]
    raise KeyError(f"no model {name!r} in {path} (models: {names})")
