"""Tests for the price-curve parameters file and ``load_price_model``."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from fleet_sim.prices.curves import IsotonicFit
from fleet_sim.prices.parameters import (
    PriceParameters,
    SavedModel,
    load_price_model,
    saved_curve,
)

FIXTURE = Path(__file__).parent / "fixtures" / "price_parameters.json"


def test_pooled_model_is_the_saved_curve_for_any_year() -> None:
    # Fixture: fuel_adjusted/exponential with α = 0.1, β = 0.05,
    # γ = ln 2 / 10, so e^{γR} = 2 at R = 10 GW.
    #   h(10)  = α + β·(e^{γR} − 1)/γ = 0.1 + 0.05·1 / (ln 2 / 10)
    #          = 0.1 + 0.5 / ln 2 = 0.1 + 0.72135 = 0.82135
    #   h′(10) = β·e^{γR} = 0.05·2 = 0.1
    model = load_price_model(FIXTURE, "fuel_adjusted/exponential")

    for year in (2021, 2030):
        curve = model.curve_for(year)
        assert curve.predict(10.0) == pytest.approx(0.1 + 0.5 / math.log(2))
        assert curve.slope(10.0) == pytest.approx(0.1)
        assert curve.sigma == 0.2
    assert not model.target.per_year


def test_per_year_model_uses_that_years_curve() -> None:
    # Fixture: raw_per_year/exponential with γ = 0, so h(R) = α + βR.
    #   2021: α = 50,  β = 2 → h(20) = 50 + 2·20 = 90
    #   2022: α = 100, β = 4 → h(20) = 100 + 4·20 = 180
    model = load_price_model(FIXTURE, "raw_per_year/exponential")

    assert model.curve_for(2021).predict(20.0) == pytest.approx(90.0)
    assert model.curve_for(2022).predict(20.0) == pytest.approx(180.0)
    with pytest.raises(KeyError, match=r"no curve for 2023 \(years: \[2021, 2022\]\)"):
        model.curve_for(2023)


def test_unknown_model_name_lists_the_saved_models() -> None:
    with pytest.raises(KeyError, match="raw_pooled/cubic.*fuel_adjusted/exponential"):
        load_price_model(FIXTURE, "raw_pooled/cubic")


def test_a_saved_curve_loads_back_unchanged(tmp_path: Path) -> None:
    fitted = IsotonicFit(knots_r_gw=(0.0, 10.0), values=(1.0, 3.0), sigma=0.5)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pooled = payload["models"][0]
    payload["models"] = [
        {
            **pooled,
            "name": "fuel_adjusted/isotonic",
            "family": "isotonic",
            "curve": saved_curve(fitted),
        }
    ]
    path = tmp_path / "price_curves.json"
    path.write_text(
        PriceParameters.model_validate(payload).model_dump_json(), encoding="utf-8"
    )

    assert load_price_model(path, "fuel_adjusted/isotonic").curve_for(2025) == fitted


def _model(**changes: Any) -> dict[str, Any]:
    """The fixture's pooled model with ``changes`` applied."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {**payload["models"][0], **changes}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "fuel_adjusted/cubic"}, "must be 'fuel_adjusted/exponential'"),
        (
            {"name": "fuel_adjusted/spline", "family": "spline"},
            "unknown family 'spline'",
        ),
        (
            {"curve": None, "curves_by_year": {2024: {"a": 1.0, "sigma": 0.1}}},
            "is pooled: set curve, not curves_by_year",
        ),
        (
            {
                "name": "raw_per_year/exponential",
                "target": "raw_per_year",
                "curves_by_year": None,
            },
            "is per-year: set curves_by_year, not curve",
        ),
        ({"curve": {"a": 1.0, "sigma": 0.1}}, "alpha"),
    ],
)
def test_saved_model_rejects_inconsistent_entries(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SavedModel.model_validate(_model(**changes))


def test_model_names_must_be_distinct() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["models"] = [payload["models"][0]] * 2

    with pytest.raises(ValueError, match="model names must be distinct"):
        PriceParameters.model_validate(payload)
