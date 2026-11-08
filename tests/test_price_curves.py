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
    exact_only,
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


def _rate(
    stamp: datetime, price: float, *, upper: float | None = None, capped: bool = False
) -> InvertedRate:
    return InvertedRate(
        settlement_start=stamp,
        wholesale_gbp_per_mwh=price,
        wholesale_upper_gbp_per_mwh=upper,
        capped=capped,
        product_code="AGILE-TEST",
        region="C",
    )


def _dataset(
    rows: list[tuple[int, float, float, float]],
    *,
    censored: frozenset[int] = frozenset(),
) -> PriceDataset:
    """A dataset from ``(year, π, R, k)`` rows, one slot apart on 15 June.

    Rows whose index is in ``censored`` are censored, with π a lower bound.
    """
    observations = [
        _observation(
            settlement_periods_utc(date(year, 6, 15))[i],
            price,
            censored=i in censored,
            load=load,
            cost=cost,
        )
        for i, (year, price, load, cost) in enumerate(rows)
    ]
    return PriceDataset(observations=observations, drops=[])


def _observation(
    stamp: datetime,
    price: float,
    *,
    censored: bool = False,
    upper: float | None = None,
    load: float = 30.0,
    cost: float = 25.0,
) -> PriceObservation:
    return PriceObservation(
        settlement_start=stamp,
        wholesale_price_gbp_per_mwh=price,
        censored=censored,
        wholesale_upper_gbp_per_mwh=upper,
        residual_load_gw=load,
        fuel_cost_gbp_per_mwh=cost,
        year=stamp.year,
    )


def test_build_dataset_drops_and_counts_each_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One UK summer day: 48 settlement periods, three of them dropped.

    Slot 0: capped, kept as censored with bounds [50, 80]
    Slot 1: no Agile price
    Slot 2: no residual load
    Slot 3: no fuel cost
    Slot 4: capped and no fuel cost, dropped as missing fuel cost
    Kept: 48 - 4 = 44, one of them censored.
    """
    stamps = settlement_periods_utc(date(2024, 6, 15))
    rates = [
        _rate(s, 50.0 + i, upper=80.0 if i == 0 else None, capped=i in (0, 4))
        for i, s in enumerate(stamps)
        if i != 1
    ]
    loads = [(s, 25.0 + i) for i, s in enumerate(stamps) if i != 2]
    costs = [(s, 60.0) for i, s in enumerate(stamps) if i not in (3, 4)]
    monkeypatch.setattr("fleet_sim.prices.dataset.invert_rates", lambda **_: rates)
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.load_residual_load", lambda **_: loads
    )
    monkeypatch.setattr("fleet_sim.prices.dataset.compute_fuel_cost", lambda **_: costs)

    dataset = build_dataset(_config(tmp_path))

    [drops] = dataset.drops
    assert drops.year == 2024
    assert drops.expected_slots == 48
    assert (drops.missing_price, drops.missing_residual_load) == (1, 1)
    assert drops.missing_fuel_cost == 2
    assert drops.kept == len(dataset.observations) == 44
    assert drops.censored == 1
    censored, exact = dataset.observations[:2]
    assert censored.settlement_start == stamps[0]
    assert censored.censored
    assert censored.wholesale_price_gbp_per_mwh == 50.0
    assert censored.wholesale_upper_gbp_per_mwh == 80.0
    assert exact.settlement_start == stamps[5]
    assert not exact.censored
    assert exact.wholesale_price_gbp_per_mwh == 55.0
    assert exact.residual_load_gw == 30.0
    assert exact.fuel_cost_gbp_per_mwh == 60.0


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

    2023: exact π = 10, 30 → mean 20 (the censored 500 is left out);
          R = 20, 26, 23 → mean 23; k = 5, 7, 6 → mean 6.
    2024: one row, so mean = min = max.
    """
    dataset = _dataset(
        [
            (2023, 10.0, 20.0, 5.0),
            (2023, 30.0, 26.0, 7.0),
            (2023, 500.0, 23.0, 6.0),
            (2024, -5.0, 15.0, 40.0),
        ],
        censored=frozenset({2}),
    )

    first, second = summarise(dataset)

    assert first.year == 2023
    assert (first.rows, first.censored_rows) == (3, 1)
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
    assert (second.rows, second.censored_rows) == (1, 0)
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
            censored=False,
            wholesale_upper_gbp_per_mwh=None,
            residual_load_gw=30.0,
            fuel_cost_gbp_per_mwh=25.0,
            year=2023,
        )


@pytest.mark.parametrize(
    ("censored", "upper", "message"),
    [
        (False, 80.0, "exact slot can't have an upper bound"),
        (True, 50.0, "must exceed lower bound"),
    ],
)
def test_price_observation_rejects_invalid_upper_bound(
    censored: bool, upper: float, message: str
) -> None:
    """Lower bound is 50 in every row."""
    with pytest.raises(ValueError, match=message):
        _observation(
            datetime(2024, 6, 15, tzinfo=UTC), 50.0, censored=censored, upper=upper
        )


def test_exact_only_removes_censored_observations() -> None:
    dataset = _dataset(
        [(2024, 10.0, 20.0, 5.0), (2024, 500.0, 26.0, 7.0), (2024, 30.0, 22.0, 6.0)],
        censored=frozenset({1}),
    )

    exact = exact_only(dataset)

    assert [obs.wholesale_price_gbp_per_mwh for obs in exact.observations] == [
        10.0,
        30.0,
    ]


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
    obs = _observation(datetime(2024, 6, 15, tzinfo=UTC), 50.0)
    assert target.to_target(obs) == pytest.approx(50.0)
    assert target.to_price(50.0, obs) == pytest.approx(50.0)


def test_fuel_adjusted_target_subtracts_cost() -> None:
    """FuelAdjustedTarget subtracts fuel cost and reverses it.

    Hand-worked: price = 50, fuel = 25, so y = 25.
    to_price(25, obs) = 25 + 25 = 50.
    """
    target = TARGETS["fuel_adjusted"]
    obs = _observation(datetime(2024, 6, 15, tzinfo=UTC), 50.0)
    assert target.to_target(obs) == pytest.approx(25.0)
    assert target.to_price(25.0, obs) == pytest.approx(50.0)
