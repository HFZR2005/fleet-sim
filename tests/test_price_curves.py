"""Tests for the price-curve pipeline: dataset, splits, targets and stubs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fleet_sim.data.agile_formula import InvertedRate
from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.prices.config import CalibrationConfig, SplitSpec
from fleet_sim.prices.curves import FAMILIES
from fleet_sim.prices.dataset import (
    PriceDataset,
    PriceObservation,
    build_dataset,
    final_test_split,
    selection_data,
    selection_folds,
    summarise,
)
from fleet_sim.prices.targets import TARGETS
from fleet_sim.stubs import StubActiveError, begin_stub_run, require_no_stubs


def _config(tmp_path: Path) -> CalibrationConfig:
    """A config whose data range is the single day 2024-06-15."""
    return CalibrationConfig.model_validate(
        {
            "data": {
                "start": "2024-06-15",
                "end": "2024-06-15",
                "cache_dir": str(tmp_path / "cache"),
                "agile_regions": ["C"],
            },
            "fuel_cost": {
                "heat_rate": 7.0,
                "gas_carbon_intensity": 0.184,
                "include_carbon_price_support": True,
            },
            "splits": {
                "training_years": [2022, 2023],
                "final_test_year": 2024,
            },
            "models": {
                "families": ["constant"],
                "targets": ["raw_pooled"],
            },
            "evaluation": {
                "weight_by_fleet_schedule": "identical",
            },
            "chosen": {
                "main": "",
                "robustness": "",
            },
            "output": {
                "results_dir": str(tmp_path / "results"),
                "parameters_file": str(tmp_path / "params.json"),
            },
        }
    )


def _rate(stamp: datetime, price: float, *, capped: bool = False) -> InvertedRate:
    return InvertedRate(
        settlement_start=stamp,
        wholesale_gbp_per_mwh=price,
        capped=capped,
        product_code="AGILE-TEST",
        region="C",
    )


def _dataset(rows: list[tuple[int, float, float, float]]) -> PriceDataset:
    """A dataset from ``(year, π, R, k)`` rows, one slot apart on 15 June."""
    observations = [
        PriceObservation(
            settlement_start=settlement_periods_utc(date(year, 6, 15))[i],
            wholesale_price_gbp_per_mwh=price,
            residual_load_gw=load,
            fuel_cost_gbp_per_mwh=cost,
            year=year,
        )
        for i, (year, price, load, cost) in enumerate(rows)
    ]
    return PriceDataset(observations=observations, drops=[])


def test_build_dataset_drops_and_counts_each_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One UK summer day: 48 settlement periods, four of them dropped.

    Slot 0: capped (also missing k, but counted once, under the first rule)
    Slot 1: no Agile price
    Slot 2: no residual load
    Slot 3: no fuel cost
    Kept: 48 - 4 = 44, starting at slot 4.
    """
    stamps = settlement_periods_utc(date(2024, 6, 15))
    rates = [_rate(s, 50.0 + i, capped=i == 0) for i, s in enumerate(stamps) if i != 1]
    loads = [(s, 25.0 + i) for i, s in enumerate(stamps) if i != 2]
    costs = [(s, 60.0) for i, s in enumerate(stamps) if i not in (0, 3)]
    monkeypatch.setattr("fleet_sim.prices.dataset.invert_rates", lambda **_: rates)
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.load_residual_load", lambda **_: loads
    )
    monkeypatch.setattr("fleet_sim.prices.dataset.compute_fuel_cost", lambda **_: costs)

    dataset = build_dataset(_config(tmp_path))

    [drops] = dataset.drops
    assert drops.year == 2024
    assert drops.expected_slots == 48
    assert (drops.capped, drops.missing_price) == (1, 1)
    assert (drops.missing_residual_load, drops.missing_fuel_cost) == (1, 1)
    assert drops.kept == len(dataset.observations) == 44
    first = dataset.observations[0]
    assert first.settlement_start == stamps[4]
    assert first.wholesale_price_gbp_per_mwh == 54.0
    assert first.residual_load_gw == 29.0
    assert first.fuel_cost_gbp_per_mwh == 60.0


def test_folds_hold_out_each_training_year_and_never_the_final_year() -> None:
    dataset = _dataset([(y, 50.0, 30.0, 25.0) for y in (2021, 2022, 2023, 2024)])
    spec = SplitSpec(training_years=[2021, 2022, 2023], final_test_year=2024)

    folds = selection_folds(dataset, spec)

    assert [f.held_out_year for f in folds] == [2021, 2022, 2023]
    for fold in folds:
        assert fold.test.years == [fold.held_out_year]
        assert fold.train.years == [
            y for y in spec.training_years if y != fold.held_out_year
        ]
    assert selection_data(dataset, spec).years == [2021, 2022, 2023]
    train, test = final_test_split(dataset, spec)
    assert train.years == [2021, 2022, 2023]
    assert test.years == [2024]


@pytest.mark.parametrize(
    ("training_years", "final_test_year", "message"),
    [
        ([2023], 2024, "at least 2 training years"),
        ([2022, 2022], 2024, "duplicates"),
        ([2022, 2023], 2023, "also a training year"),
        ([2022, 2024], 2023, "after every training year"),
    ],
)
def test_split_spec_rejects(
    training_years: list[int], final_test_year: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SplitSpec(training_years=training_years, final_test_year=final_test_year)


def test_summarise_per_year() -> None:
    """Hand-worked.

    2023: π = 10, 30 → mean 20; R = 20, 26 → mean 23; k = 5, 7 → mean 6.
    2024: one row, so mean = min = max.
    """
    dataset = _dataset(
        [(2023, 10.0, 20.0, 5.0), (2023, 30.0, 26.0, 7.0), (2024, -5.0, 15.0, 40.0)]
    )

    first, second = summarise(dataset)

    assert first.year == 2023
    assert first.rows == 2
    assert first.price_mean_gbp_per_mwh == pytest.approx(20.0)
    assert (first.price_min_gbp_per_mwh, first.price_max_gbp_per_mwh) == (10.0, 30.0)
    assert first.residual_load_mean_gw == pytest.approx(23.0)
    assert (first.residual_load_min_gw, first.residual_load_max_gw) == (20.0, 26.0)
    assert first.fuel_cost_mean_gbp_per_mwh == pytest.approx(6.0)
    assert (first.fuel_cost_min_gbp_per_mwh, first.fuel_cost_max_gbp_per_mwh) == (
        5.0,
        7.0,
    )
    assert second.year == 2024
    assert second.rows == 1
    assert second.price_mean_gbp_per_mwh == second.price_min_gbp_per_mwh == -5.0


def test_require_no_stubs_raises_after_a_stub_ran() -> None:
    """Finalise must not write parameters once any stub has run."""
    begin_stub_run()
    FAMILIES["constant"].fit([1.0], [1.0])

    with pytest.raises(StubActiveError):
        require_no_stubs()


def test_price_observation_year_must_match_timestamp() -> None:
    """PriceObservation rejects a year that doesn't match the timestamp."""
    with pytest.raises(Exception, match="does not match"):
        PriceObservation(
            settlement_start=datetime(2024, 6, 15, tzinfo=UTC),
            wholesale_price_gbp_per_mwh=50.0,
            residual_load_gw=30.0,
            fuel_cost_gbp_per_mwh=25.0,
            year=2023,
        )


def test_constant_curve_predicts_mean() -> None:
    """The constant stub family predicts the training mean.

    Hand-worked: y = [10, 20, 30], mean = 20.
    predict(anything) = 20, slope(anything) = 0.
    """
    begin_stub_run()
    family = FAMILIES["constant"]
    fitted = family.fit([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert fitted.predict(99.0) == pytest.approx(20.0)
    assert fitted.slope(99.0) == pytest.approx(0.0)


def test_raw_target_is_identity() -> None:
    """RawTarget returns the wholesale price unchanged."""
    target = TARGETS["raw_pooled"]
    obs = PriceObservation(
        settlement_start=datetime(2024, 6, 15, tzinfo=UTC),
        wholesale_price_gbp_per_mwh=50.0,
        residual_load_gw=30.0,
        fuel_cost_gbp_per_mwh=25.0,
        year=2024,
    )
    assert target.to_target(obs) == pytest.approx(50.0)
    assert target.to_price(50.0, obs) == pytest.approx(50.0)


def test_fuel_adjusted_target_subtracts_cost() -> None:
    """FuelAdjustedTarget subtracts fuel cost and reverses it.

    Hand-worked: price = 50, fuel = 25, so y = 25.
    to_price(25, obs) = 25 + 25 = 50.
    """
    target = TARGETS["fuel_adjusted"]
    obs = PriceObservation(
        settlement_start=datetime(2024, 6, 15, tzinfo=UTC),
        wholesale_price_gbp_per_mwh=50.0,
        residual_load_gw=30.0,
        fuel_cost_gbp_per_mwh=25.0,
        year=2024,
    )
    assert target.to_target(obs) == pytest.approx(25.0)
    assert target.to_price(25.0, obs) == pytest.approx(50.0)
