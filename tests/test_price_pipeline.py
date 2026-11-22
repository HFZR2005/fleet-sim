"""compare and finalise end to end, on a small synthetic dataset."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.prices.config import CalibrationConfig
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.fleet_weights import FleetCharging
from fleet_sim.prices.parameters import Provenance, load_price_model
from fleet_sim.prices.pipeline import compare, finalise
from fleet_sim.stubs import StubActiveError, begin_stub_run, stub

_TRAINING_YEARS = [2023, 2024]
_FINAL_YEAR = 2025
# The true curve, in π / k: h(R) = α + β·(e^{γR} − 1)/γ.
_ALPHA, _BETA, _GAMMA = 0.3, 0.06, -0.03
# Slots above this load are censored at the price it gives (not in 2024).
_CAP_GW = 32.0


def _h(r_gw: float) -> float:
    return _ALPHA + _BETA * math.expm1(_GAMMA * r_gw) / _GAMMA


@pytest.fixture(scope="module")
def dataset() -> PriceDataset:
    """Twenty January days a year, π = k·(h(R) + ε), ε ~ N(0, 0.05²).

    Each year has its own fuel cost k.  In 2023 and 2025, slots with R
    above ``_CAP_GW`` are censored: π is recorded at the cap, as a lower
    bound.  2024 has none, since its days include 2024-01-17, the
    anchoring example, which must have no censored slots.
    """
    rng = np.random.default_rng(74)
    observations = []
    for year, cost in ((2023, 90.0), (2024, 70.0), (2025, 80.0)):
        for d in range(20):
            for stamp in settlement_periods_utc(date(year, 1, 5) + timedelta(d)):
                load = float(rng.uniform(2.0, 35.0))
                censored = year != 2024 and load > _CAP_GW
                y = _h(_CAP_GW) if censored else _h(load) + float(rng.normal(0, 0.05))
                observations.append(
                    PriceObservation(
                        settlement_start=stamp,
                        wholesale_price_gbp_per_mwh=cost * y,
                        censored=censored,
                        wholesale_upper_gbp_per_mwh=None,
                        residual_load_gw=load,
                        fuel_cost_gbp_per_mwh=cost,
                        year=year,
                    )
                )
    return PriceDataset(observations=observations, drops=[])


@pytest.fixture(scope="module")
def charging(dataset: PriceDataset) -> FleetCharging:
    rng = np.random.default_rng(75)
    stamps = [o.settlement_start for o in dataset.observations]
    return FleetCharging(
        scenario="test",
        start=stamps[0].date(),
        end=stamps[-1].date(),
        slot_start_utc=stamps,
        net_battery_kw=[float(x) for x in rng.normal(0.0, 100.0, len(stamps))],
        skipped_days=[],
    )


def _config(tmp_path: Path) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "data": {
                "start": "2023-01-01",
                "end": "2025-12-31",
                "cache_dir": str(tmp_path / "cache"),
                "agile_regions": ["C"],
            },
            "fuel_cost": {
                "heat_rate": 2.0,
                "gas_carbon_intensity": 0.184,
                "include_carbon_price_support": True,
            },
            "splits": {
                "training_years": _TRAINING_YEARS,
                "final_test_year": _FINAL_YEAR,
            },
            "models": {
                "families": ["exponential", "cubic_offset", "isotonic"],
                "targets": ["raw_pooled", "raw_per_year", "fuel_adjusted"],
            },
            "evaluation": {"weight_by_fleet_schedule": "identical"},
            "chosen": {
                "main": "fuel_adjusted/exponential",
                "robustness": ["raw_per_year/exponential"],
            },
            "output": {
                "results_dir": str(tmp_path / "results"),
                "parameters_file": str(tmp_path / "price_curves.json"),
            },
        }
    )


def _provenance(config: CalibrationConfig) -> Provenance:
    return Provenance(
        data_start=config.data.start,
        data_end=config.data.end,
        agile_regions=config.data.agile_regions,
        splits=config.splits,
        fuel_cost=config.fuel_cost,
        config_sha256="0" * 64,
        git_commit="0" * 40,
        git_dirty=False,
        run_date=date(2026, 1, 1),
    )


def test_compare_writes_its_outputs_and_never_reads_the_final_year(
    tmp_path: Path, dataset: PriceDataset, charging: FleetCharging
) -> None:
    config = _config(tmp_path)
    begin_stub_run()

    result = compare(config, dataset, charging, ["fuel_adjusted/exponential"])

    results_dir = tmp_path / "results"
    for name in [
        "evaluation.json",
        "comparison.md",
        "residuals_fuel_adjusted_exponential.json",
        "fuel_adjustment.png",
        "fits.png",
        "slopes.png",
        "anchoring.png",
        "residuals.png",
    ]:
        assert (results_dir / name).exists(), name
    # Three families × (two pooled targets × two held-out years + one
    # per-year target × two years).
    assert len(result.report.results) == 3 * (2 * 2 + 2)
    assert {r.year for r in result.report.results} == set(_TRAINING_YEARS)
    assert {b.year for b in result.report.brackets} == set(_TRAINING_YEARS)


def test_finalise_writes_parameters_that_recover_the_true_curve(
    tmp_path: Path, dataset: PriceDataset, charging: FleetCharging
) -> None:
    config = _config(tmp_path)
    begin_stub_run()

    parameters = finalise(config, dataset, charging, _provenance(config))

    assert [m.name for m in parameters.models] == [
        "fuel_adjusted/exponential",
        "raw_per_year/exponential",
    ]
    assert [m.final_test.year for m in parameters.models] == [_FINAL_YEAR] * 2
    main = load_price_model(tmp_path / "price_curves.json", "fuel_adjusted/exponential")
    curve = main.curve_for(_FINAL_YEAR)
    # True slope h'(15) = β·e^{15γ} = 0.06·e^{−0.45} ≈ 0.0383 per GW.
    assert curve.slope(15.0) == pytest.approx(_BETA * math.exp(15 * _GAMMA), rel=0.1)
    per_year = load_price_model(
        tmp_path / "price_curves.json", "raw_per_year/exponential"
    )
    for year in [*_TRAINING_YEARS, _FINAL_YEAR]:
        per_year.curve_for(year)


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        ("parameters file exists", FileExistsError),
        ("a stub ran", StubActiveError),
    ],
)
def test_finalise_refuses_without_writing(
    tmp_path: Path,
    dataset: PriceDataset,
    charging: FleetCharging,
    setup: str,
    error: type[Exception],
) -> None:
    config = _config(tmp_path)
    params_path = tmp_path / "price_curves.json"
    begin_stub_run()
    if setup == "parameters file exists":
        params_path.write_text("earlier run\n", encoding="utf-8")
    else:

        @stub("test placeholder")
        def placeholder() -> None:
            pass

        placeholder()

    with pytest.raises(error):
        finalise(config, dataset, charging, _provenance(config))

    if setup == "parameters file exists":
        assert params_path.read_text(encoding="utf-8") == "earlier run\n"
    else:
        assert not params_path.exists()
