import pytest
from pydantic import ValidationError

from fleet_sim.models import BatterySpec, HomeDay


def battery_data() -> dict[str, object]:
    return {
        "capacity_kwh": 2.0,
        "max_charge_kw": 8.0,
        "max_discharge_kw": 2.0,
        "eta_charge": 0.5,
        "eta_discharge": 0.5,
        "soc_initial": 0.25,
    }


def home_data() -> dict[str, object]:
    return {
        "battery": battery_data(),
        "demand_kw": [1.0] * 48,
        "price_p_per_kwh": [10.0] * 48,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"eta_charge": 1, "eta_discharge": 1, "soc_initial": 0},
        {"soc_initial": 1, "max_charge_kw": 0, "max_discharge_kw": 0},
    ],
)
def test_battery_spec_accepts_the_edges_of_each_range(
    overrides: dict[str, object],
) -> None:
    BatterySpec.model_validate(battery_data() | overrides)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capacity_kwh", 0, "capacity_kwh must be greater than 0"),
        ("max_charge_kw", -1, "max_charge_kw must be greater than or equal to 0"),
        ("max_discharge_kw", -1, "max_discharge_kw must be greater than or equal"),
        ("eta_charge", 0, "must be greater than 0 and at most 1"),
        ("eta_discharge", 0, "must be greater than 0 and at most 1"),
        ("eta_charge", 90, "90% is written 0.9"),
        ("eta_discharge", 90, "90% is written 0.9"),
        ("soc_initial", 90, "90% is written 0.9"),
        ("soc_initial", -0.1, r"soc_initial must be in \[0, 1\]"),
    ],
)
def test_battery_spec_rejects(field: str, value: float, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        BatterySpec.model_validate(battery_data() | {field: value})


def test_home_day_accepts_zero_demand() -> None:
    HomeDay.model_validate(home_data() | {"demand_kw": [0.0] * 48})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("demand_kw", [1.0] * 47, "demand_kw must contain 48 half-hour values"),
        (
            "price_p_per_kwh",
            [10.0] * 49,
            "price_p_per_kwh must contain 48 half-hour values",
        ),
        ("demand_kw", [1.0] * 3 + [-0.5] + [1.0] * 44, "demand_kw must be at least 0"),
        ("home_id", "", "home_id must not be empty"),
        ("region", "", "region must not be empty"),
    ],
)
def test_home_day_rejects(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        HomeDay.model_validate(home_data() | {field: value})
