"""Price observations aligned from three sources, and splits by whole year.

A ``PriceObservation`` is one half-hour settlement period with wholesale
price π, residual load R and fuel cost k.  ``build_dataset`` joins the
three sources on settlement period and records, per year, how many slots
each drop rule removed.

Splits are by whole year, never by random half-hour: neighbouring slots
are near-duplicates, so a random split would overstate accuracy.  Model
selection is leave-one-year-out over the training years; the final-test
year is only ever returned by ``final_test_split``.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from fleet_sim.data.fuel_cost import compute_fuel_cost
from fleet_sim.data.residual_load import load_residual_load
from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.data.wholesale import invert_rates
from fleet_sim.prices.config import CalibrationConfig, SplitSpec


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


class YearDrops(BaseModel):
    """How many of one year's settlement periods each rule dropped.

    Each slot is counted under the first rule that drops it, in the order
    capped, missing price, missing residual load, missing fuel cost, so
    the counts plus ``kept`` add up to ``expected_slots``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int
    expected_slots: int
    capped: int
    missing_price: int
    missing_residual_load: int
    missing_fuel_cost: int
    kept: int

    @model_validator(mode="after")
    def counts_add_up(self) -> YearDrops:
        total = (
            self.capped
            + self.missing_price
            + self.missing_residual_load
            + self.missing_fuel_cost
            + self.kept
        )
        if total != self.expected_slots:
            raise ValueError(
                f"{self.year}: drops plus kept ({total}) do not equal "
                f"expected slots ({self.expected_slots})"
            )
        return self


class PriceDataset(BaseModel):
    """Aligned observations, with the per-year drop counts that produced them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observations: list[PriceObservation]
    drops: list[YearDrops]

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


class Fold(BaseModel):
    """One leave-one-year-out split: fit on ``train``, score on ``test``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    held_out_year: int
    train: PriceDataset
    test: PriceDataset


class YearSummary(BaseModel):
    """Row count and the mean and range of π, R and k for one year."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int
    rows: int
    price_mean_gbp_per_mwh: float
    price_min_gbp_per_mwh: float
    price_max_gbp_per_mwh: float
    residual_load_mean_gw: float
    residual_load_min_gw: float
    residual_load_max_gw: float
    fuel_cost_mean_gbp_per_mwh: float
    fuel_cost_min_gbp_per_mwh: float
    fuel_cost_max_gbp_per_mwh: float


def build_dataset(config: CalibrationConfig) -> PriceDataset:
    """Join π, R and k on settlement period over the configured date range.

    The expected slots are every settlement period of every UK day from
    ``data.start`` to ``data.end`` inclusive.  A slot is dropped when its
    Agile price is capped (the wholesale price can't be recovered) or when
    any of the three inputs is missing.  The wholesale price uses the
    first configured Agile region.
    """
    data = config.data
    cache_dir = Path(data.cache_dir)
    start_year = data.start.year
    end_year = data.end.year

    rates = invert_rates(
        region=data.agile_regions[0].upper(),
        period_from=datetime(start_year, 1, 1, tzinfo=UTC),
        period_to=datetime(end_year + 1, 1, 1, tzinfo=UTC),
        cache_dir=cache_dir,
    )
    prices = {r.settlement_start: r for r in rates}
    loads = dict(
        load_residual_load(
            start_year=start_year, end_year=end_year, cache_dir=cache_dir
        )
    )
    costs = dict(
        compute_fuel_cost(
            start_year=start_year,
            end_year=end_year,
            heat_rate=config.fuel_cost.heat_rate,
            gas_carbon_intensity=config.fuel_cost.gas_carbon_intensity,
            include_carbon_price_support=config.fuel_cost.include_carbon_price_support,
            cache_dir=cache_dir,
        )
    )

    counts: dict[int, Counter[str]] = {}
    observations: list[PriceObservation] = []
    day = data.start
    while day <= data.end:
        for stamp in settlement_periods_utc(day):
            year_counts = counts.setdefault(stamp.year, Counter())
            year_counts["expected"] += 1
            rate = prices.get(stamp)
            if rate is None:
                year_counts["missing_price"] += 1
            elif rate.capped:
                year_counts["capped"] += 1
            elif stamp not in loads:
                year_counts["missing_residual_load"] += 1
            elif stamp not in costs:
                year_counts["missing_fuel_cost"] += 1
            else:
                year_counts["kept"] += 1
                observations.append(
                    PriceObservation(
                        settlement_start=stamp,
                        wholesale_price_gbp_per_mwh=rate.wholesale_gbp_per_mwh,
                        residual_load_gw=loads[stamp],
                        fuel_cost_gbp_per_mwh=costs[stamp],
                        year=stamp.year,
                    )
                )
        day += timedelta(days=1)

    if not observations:
        raise ValueError(
            f"no settlement period from {data.start} to {data.end} has all three inputs"
        )
    drops = [
        YearDrops(
            year=year,
            expected_slots=c["expected"],
            capped=c["capped"],
            missing_price=c["missing_price"],
            missing_residual_load=c["missing_residual_load"],
            missing_fuel_cost=c["missing_fuel_cost"],
            kept=c["kept"],
        )
        for year, c in sorted(counts.items())
    ]
    return PriceDataset(observations=observations, drops=drops)


def selection_data(dataset: PriceDataset, spec: SplitSpec) -> PriceDataset:
    """The training years only; the final-test year is left out."""
    return _years(dataset, spec.training_years)


def selection_folds(dataset: PriceDataset, spec: SplitSpec) -> list[Fold]:
    """Leave-one-year-out folds across the training years.

    Fold ``i`` tests on training year ``i`` and fits on the others.  The
    final-test year appears in no fold.
    """
    selection = selection_data(dataset, spec)
    return [
        Fold(
            held_out_year=year,
            train=_years(selection, [y for y in spec.training_years if y != year]),
            test=_years(selection, [year]),
        )
        for year in spec.training_years
    ]


def final_test_split(
    dataset: PriceDataset, spec: SplitSpec
) -> tuple[PriceDataset, PriceDataset]:
    """``(train, test)``: all training years, and the final-test year.

    The only function that returns final-test rows.  Call it once, after
    the model has been chosen.
    """
    return (
        _years(dataset, spec.training_years),
        _years(dataset, [spec.final_test_year]),
    )


def summarise(dataset: PriceDataset) -> list[YearSummary]:
    """Rows and the mean, min and max of π, R and k, one entry per year."""
    summaries: list[YearSummary] = []
    for year in dataset.years:
        rows = [obs for obs in dataset.observations if obs.year == year]
        price = [obs.wholesale_price_gbp_per_mwh for obs in rows]
        load = [obs.residual_load_gw for obs in rows]
        cost = [obs.fuel_cost_gbp_per_mwh for obs in rows]
        summaries.append(
            YearSummary(
                year=year,
                rows=len(rows),
                price_mean_gbp_per_mwh=fmean(price),
                price_min_gbp_per_mwh=min(price),
                price_max_gbp_per_mwh=max(price),
                residual_load_mean_gw=fmean(load),
                residual_load_min_gw=min(load),
                residual_load_max_gw=max(load),
                fuel_cost_mean_gbp_per_mwh=fmean(cost),
                fuel_cost_min_gbp_per_mwh=min(cost),
                fuel_cost_max_gbp_per_mwh=max(cost),
            )
        )
    return summaries


def _years(dataset: PriceDataset, years: list[int]) -> PriceDataset:
    """The observations and drop counts for ``years``; raises if one is empty."""
    present = set(dataset.years)
    missing = sorted(set(years) - present)
    if missing:
        raise ValueError(f"no observations in year(s) {missing}")
    wanted = set(years)
    return PriceDataset(
        observations=[obs for obs in dataset.observations if obs.year in wanted],
        drops=[d for d in dataset.drops if d.year in wanted],
    )
