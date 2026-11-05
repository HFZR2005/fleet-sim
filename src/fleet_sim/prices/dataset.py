"""Price observations aligned from multiple sources, and train/test splits.

A ``PriceObservation`` is one half-hour slot with wholesale price,
residual load, and fuel cost.  ``PriceDataset`` collects those
observations.  ``SplitSpec`` says which years go into training and
which into testing.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from fleet_sim.data.fuel_cost import compute_fuel_cost
from fleet_sim.data.residual_load import load_residual_load
from fleet_sim.data.wholesale import load_wholesale_prices
from fleet_sim.prices.config import CalibrationConfig
from fleet_sim.stubs import stub


class PriceObservation(BaseModel):
    """One half-hour settlement period with aligned price, load, and cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_start: datetime
    wholesale_price_gbp_per_mwh: float
    residual_load_gw: float
    fuel_cost_gbp_per_mwh: float
    year: int

    @field_validator("year")
    @classmethod
    def year_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"year must be positive (got {value})")
        return value

    @model_validator(mode="after")
    def year_matches_timestamp(self) -> PriceObservation:
        if self.settlement_start.year != self.year:
            raise ValueError(
                f"year ({self.year}) does not match "
                f"settlement_start ({self.settlement_start.year})"
            )
        return self


class PriceDataset(BaseModel):
    """A collection of aligned price observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observations: list[PriceObservation]

    @field_validator("observations")
    @classmethod
    def not_empty(cls, value: list[PriceObservation]) -> list[PriceObservation]:
        if not value:
            raise ValueError("observations must not be empty")
        return value

    @property
    def years(self) -> list[int]:
        """Sorted unique years present in the dataset."""
        return sorted({obs.year for obs in self.observations})


class SplitSpec(BaseModel):
    """Which years go into training, testing, and final testing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    train_years: list[int]
    test_years: list[int]
    final_test_year: int

    @model_validator(mode="after")
    def no_overlap(self) -> SplitSpec:
        train = set(self.train_years)
        test = set(self.test_years)
        final = {self.final_test_year}
        if train & test:
            raise ValueError(f"train and test years overlap: {train & test}")
        if train & final:
            raise ValueError(f"train and final-test years overlap: {train & final}")
        if test & final:
            raise ValueError(f"test and final-test years overlap: {test & final}")
        return self


def split_dataset(
    dataset: PriceDataset,
    spec: SplitSpec,
) -> tuple[PriceDataset, PriceDataset]:
    """Split into ``(train, test)`` by year.  Never includes ``final_test_year``."""
    train_set = set(spec.train_years)
    test_set = set(spec.test_years)
    train = [obs for obs in dataset.observations if obs.year in train_set]
    test = [obs for obs in dataset.observations if obs.year in test_set]
    if not train:
        raise ValueError("no observations fall in the training years")
    if not test:
        raise ValueError("no observations fall in the test years")
    return PriceDataset(observations=train), PriceDataset(observations=test)


@stub("synthetic aligned data — replace when real loaders land")
def load_and_align(config: CalibrationConfig) -> PriceDataset:
    """Load wholesale, residual-load, and fuel-cost sources and align them.

    Stub: calls the three stub loaders and joins on timestamp.
    """
    start_year = config.data.start.year
    end_year = config.data.end.year

    prices = dict(load_wholesale_prices(start_year=start_year, end_year=end_year))
    loads = dict(load_residual_load(start_year=start_year, end_year=end_year))
    costs = dict(
        compute_fuel_cost(
            start_year=start_year,
            end_year=end_year,
            heat_rate=config.fuel_cost.heat_rate,
            gas_carbon_intensity=config.fuel_cost.gas_carbon_intensity,
            include_carbon_price_support=config.fuel_cost.include_carbon_price_support,
        )
    )

    timestamps = sorted(set(prices) & set(loads) & set(costs))
    observations = [
        PriceObservation(
            settlement_start=ts,
            wholesale_price_gbp_per_mwh=prices[ts],
            residual_load_gw=loads[ts],
            fuel_cost_gbp_per_mwh=costs[ts],
            year=ts.year,
        )
        for ts in timestamps
    ]
    return PriceDataset(observations=observations)
