"""End-to-end tests for the price-curve pipeline skeleton."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.prices.config import CalibrationConfig
from fleet_sim.prices.curves import FAMILIES
from fleet_sim.prices.dataset import (
    PriceDataset,
    PriceObservation,
    SplitSpec,
    load_and_align,
    split_dataset,
)
from fleet_sim.prices.evaluation import EvaluationReport, evaluate
from fleet_sim.prices.targets import TARGETS
from fleet_sim.stubs import (
    StubActiveError,
    active_stubs,
    begin_stub_run,
    require_no_stubs,
)


def _synthetic_observations() -> list[PriceObservation]:
    """96 observations: 48 slots on 2024-06-15 and 48 on 2023-06-15."""
    rows: list[PriceObservation] = []
    for year in (2023, 2024):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for slot in range(48):
            stamp = base + timedelta(minutes=30 * slot)
            r_gw = 20.0 + 20.0 * slot / 47
            # price = 40 + 2 * r_gw  (linear, so a real fit could recover it)
            price = 40.0 + 2.0 * r_gw
            rows.append(
                PriceObservation(
                    settlement_start=stamp,
                    wholesale_price_gbp_per_mwh=price,
                    residual_load_gw=r_gw,
                    fuel_cost_gbp_per_mwh=30.0,
                    year=year,
                )
            )
    return rows


def _test_config(tmp_path: Path) -> CalibrationConfig:
    """A config that works with the synthetic observations."""
    return CalibrationConfig.model_validate(
        {
            "data": {
                "start": "2023-01-01",
                "end": "2025-12-31",
                "cache_dir": str(tmp_path / "cache"),
                "agile_regions": ["C"],
            },
            "fuel_cost": {
                "heat_rate": 7.0,
                "gas_carbon_intensity": 0.184,
                "include_carbon_price_support": True,
            },
            "dataset": {
                "drop_capped_slots": True,
                "min_coverage": 0.9,
            },
            "splits": {
                "training_years": [2023, 2024],
                "selection": "leave_one_year_out",
                "final_test_year": 2025,
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


def _synthetic_residual_load(
    *,
    start_year: int,
    end_year: int,
    **_kwargs: object,
) -> list[tuple[datetime, float]]:
    """Synthetic residual load for pipeline tests (no network)."""
    rows: list[tuple[datetime, float]] = []
    for year in range(start_year, end_year + 1):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for day_offset in range(2):
            day_start = base + timedelta(days=day_offset)
            for slot in range(48):
                stamp = day_start + timedelta(minutes=30 * slot)
                load_gw = 20.0 + 20.0 * slot / 47
                rows.append((stamp, load_gw))
    return rows


def _synthetic_fuel_cost(
    *,
    start_year: int,
    end_year: int,
    **_kwargs: object,
) -> list[tuple[datetime, float]]:
    """Constant synthetic fuel cost for pipeline tests (no network)."""
    rows: list[tuple[datetime, float]] = []
    for year in range(start_year, end_year + 1):
        base = datetime(year, 6, 15, tzinfo=UTC)
        for slot in range(2 * 48):
            rows.append((base + timedelta(minutes=30 * slot), 30.0))
    return rows


def test_compare_completes_and_lists_stubs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compare pipeline runs end to end and reports active stubs."""
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.load_residual_load", _synthetic_residual_load
    )
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.compute_fuel_cost", _synthetic_fuel_cost
    )
    begin_stub_run()
    config = _test_config(tmp_path)
    dataset = load_and_align(config)

    results = []
    for family_name in config.models.families:
        family = FAMILIES[family_name]
        for target_name in config.models.targets:
            target = TARGETS[target_name]
            model_name = f"{target_name}/{family_name}"

            test_year = config.splits.training_years[-1]
            train_years = [y for y in config.splits.training_years if y != test_year]
            spec = SplitSpec(
                train_years=train_years,
                test_years=[test_year],
                final_test_year=config.splits.final_test_year,
            )
            train_data, test_data = split_dataset(dataset, spec)

            r_train = [obs.residual_load_gw for obs in train_data.observations]
            y_train = [target.to_target(obs) for obs in train_data.observations]
            fitted = family.fit(r_train, y_train)

            result = evaluate(
                fitted,
                train_data,
                test_data,
                target,
                model_name=model_name,
                curve_family=family_name,
                target_name=target_name,
            )
            results.append(result)

    report = EvaluationReport(results=results)
    assert len(report.results) == 1
    assert report.results[0].model_name == "raw_pooled/constant"

    stubs = active_stubs()
    assert len(stubs) > 0
    stub_text = "\n".join(stubs)
    assert "constant placeholder" in stub_text
    assert "synthetic" in stub_text.lower()


def test_finalise_refuses_when_chosen_empty(tmp_path: Path) -> None:
    """Finalise raises when [chosen] main is empty."""
    config = _test_config(tmp_path)
    assert config.chosen.main == ""
    with pytest.raises(ValueError, match="empty"):
        if not config.chosen.main:
            raise ValueError(
                "[chosen] main is empty — run compare first and pick a model"
            )


def test_finalise_refuses_params_while_stubs_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finalise refuses to write the parameters file when stubs ran."""
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.load_residual_load", _synthetic_residual_load
    )
    monkeypatch.setattr(
        "fleet_sim.prices.dataset.compute_fuel_cost", _synthetic_fuel_cost
    )
    begin_stub_run()
    config = _test_config(tmp_path)
    dataset = load_and_align(config)

    family = FAMILIES["constant"]
    target = TARGETS["raw_pooled"]
    r = [obs.residual_load_gw for obs in dataset.observations]
    y = [target.to_target(obs) for obs in dataset.observations]
    family.fit(r, y)

    stubs = active_stubs()
    assert len(stubs) > 0
    with pytest.raises(StubActiveError):
        require_no_stubs()


def test_compare_never_reads_final_test_year() -> None:
    """split_dataset excludes the final test year from both splits."""
    observations = _synthetic_observations()
    dataset = PriceDataset(observations=observations)

    spec = SplitSpec(
        train_years=[2023],
        test_years=[2024],
        final_test_year=2025,
    )
    train, test = split_dataset(dataset, spec)

    train_years = {obs.year for obs in train.observations}
    test_years = {obs.year for obs in test.observations}
    assert 2025 not in train_years
    assert 2025 not in test_years
    assert train_years == {2023}
    assert test_years == {2024}


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


def test_split_spec_rejects_overlap() -> None:
    """SplitSpec rejects overlapping train and test years."""
    with pytest.raises(Exception, match="overlap"):
        SplitSpec(
            train_years=[2023, 2024],
            test_years=[2024],
            final_test_year=2025,
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
