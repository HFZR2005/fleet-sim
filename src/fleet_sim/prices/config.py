"""Calibration configuration for the price-curve pipeline.

Validates ``calibration/price_curves.toml``.  Loading follows the same
pattern as ``fleet_sim.scenario``.
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class DataConfig(BaseModel):
    """``[data]`` section: date range, cache, and Agile regions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date
    end: date
    cache_dir: str
    agile_regions: list[str]

    @field_validator("agile_regions")
    @classmethod
    def at_least_one_region(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("agile_regions must not be empty")
        return value


class FuelCostConfig(BaseModel):
    """``[fuel_cost]`` section: gas-plant parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    heat_rate: float
    gas_carbon_intensity: float
    include_carbon_price_support: bool


class DatasetConfig(BaseModel):
    """``[dataset]`` section: filters applied when building observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    drop_capped_slots: bool
    min_coverage: float

    @field_validator("min_coverage")
    @classmethod
    def coverage_is_fraction(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"min_coverage must be in [0, 1] (got {value})")
        return value


class SplitsConfig(BaseModel):
    """``[splits]`` section: which years train, validate, and test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training_years: list[int]
    selection: str
    final_test_year: int

    @field_validator("training_years")
    @classmethod
    def at_least_one_training_year(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("training_years must not be empty")
        return value


class ModelsConfig(BaseModel):
    """``[models]`` section: which families and targets to compare."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    families: list[str]
    targets: list[str]

    @field_validator("families")
    @classmethod
    def at_least_one_family(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("families must not be empty")
        return value

    @field_validator("targets")
    @classmethod
    def at_least_one_target(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("targets must not be empty")
        return value


class EvaluationConfig(BaseModel):
    """``[evaluation]`` section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weight_by_fleet_schedule: str


class ChosenConfig(BaseModel):
    """``[chosen]`` section: filled after the compare run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    main: str
    robustness: str


class OutputConfig(BaseModel):
    """``[output]`` section: where results go."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results_dir: str
    parameters_file: str


class CalibrationConfig(BaseModel):
    """Top-level configuration for ``calibration/price_curves.toml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: DataConfig
    fuel_cost: FuelCostConfig
    dataset: DatasetConfig
    splits: SplitsConfig
    models: ModelsConfig
    evaluation: EvaluationConfig
    chosen: ChosenConfig
    output: OutputConfig


def load_config(path: Path) -> CalibrationConfig:
    """Read and validate ``path`` as a ``CalibrationConfig``."""
    if not path.is_file():
        raise FileNotFoundError(f"config not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML in {path}: {exc}") from exc
    try:
        return CalibrationConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"config validation failed for {path}: {exc}") from exc
