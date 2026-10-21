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
    prices = [10.0] * 48
    prices[0] = -8.0
    return {
        "battery": battery_data(),
        "demand_kw": [1.0] * 48,
        "price_p_per_kwh": prices,
    }


def test_battery_spec_accepts_a_valid_battery() -> None:
    spec = BatterySpec.model_validate(battery_data())

    assert spec.capacity_kwh == 2.0
    assert spec.max_charge_kw == 8.0
    assert spec.max_discharge_kw == 2.0
    assert spec.eta_charge == 0.5
    assert spec.eta_discharge == 0.5
    assert spec.soc_initial == 0.25


def test_battery_spec_accepts_boundary_fractions_and_zero_power() -> None:
    data = battery_data()
    data["eta_charge"] = 1
    data["eta_discharge"] = 1
    data["soc_initial"] = 0
    data["max_charge_kw"] = 0
    data["max_discharge_kw"] = 0

    spec = BatterySpec.model_validate(data)

    assert spec.eta_charge == 1
    assert spec.soc_initial == 0
    assert spec.max_charge_kw == 0

    data["soc_initial"] = 1
    assert BatterySpec.model_validate(data).soc_initial == 1


def test_capacity_must_be_positive() -> None:
    data = battery_data()
    data["capacity_kwh"] = 0

    with pytest.raises(ValidationError, match="capacity_kwh must be greater than 0"):
        BatterySpec.model_validate(data)


@pytest.mark.parametrize("field", ["max_charge_kw", "max_discharge_kw"])
def test_power_limits_must_be_non_negative(field: str) -> None:
    data = battery_data()
    data[field] = -1

    with pytest.raises(
        ValidationError, match=f"{field} must be greater than or equal to 0"
    ):
        BatterySpec.model_validate(data)


@pytest.mark.parametrize("field", ["eta_charge", "eta_discharge"])
def test_efficiency_rejects_zero(field: str) -> None:
    data = battery_data()
    data[field] = 0

    with pytest.raises(ValidationError, match="must be greater than 0 and at most 1"):
        BatterySpec.model_validate(data)


@pytest.mark.parametrize("field", ["eta_charge", "eta_discharge"])
def test_efficiency_rejects_percentage(field: str) -> None:
    data = battery_data()
    data[field] = 90

    with pytest.raises(ValidationError, match="90% is written 0.9"):
        BatterySpec.model_validate(data)


def test_soc_rejects_percentage() -> None:
    data = battery_data()
    data["soc_initial"] = 90

    with pytest.raises(ValidationError, match="90% is written 0.9"):
        BatterySpec.model_validate(data)


def test_soc_rejects_negative() -> None:
    data = battery_data()
    data["soc_initial"] = -0.1

    with pytest.raises(ValidationError, match=r"soc_initial must be in \[0, 1\]"):
        BatterySpec.model_validate(data)


def test_battery_spec_rejects_a_power_named_in_kw_for_capacity() -> None:
    data = battery_data()
    data["capacity_kw"] = 2.0

    with pytest.raises(ValidationError, match="capacity_kw"):
        BatterySpec.model_validate(data)


def test_home_day_accepts_a_valid_day() -> None:
    day = HomeDay.model_validate(home_data())

    assert day.battery.capacity_kwh == 2.0
    assert len(day.demand_kw) == 48
    assert len(day.price_p_per_kwh) == 48
    assert day.price_p_per_kwh[0] == -8.0
    assert day.demand_kw[0] == 1.0


def test_home_day_accepts_zero_demand() -> None:
    data = home_data()
    data["demand_kw"] = [0.0] * 48

    day = HomeDay.model_validate(data)

    assert day.demand_kw[0] == 0.0


def test_demand_must_cover_48_slots() -> None:
    data = home_data()
    data["demand_kw"] = [1.0] * 47

    with pytest.raises(
        ValidationError, match="demand_kw must contain 48 half-hour values"
    ):
        HomeDay.model_validate(data)


def test_prices_must_cover_48_slots() -> None:
    data = home_data()
    data["price_p_per_kwh"] = [10.0] * 49

    with pytest.raises(
        ValidationError, match="price_p_per_kwh must contain 48 half-hour values"
    ):
        HomeDay.model_validate(data)


def test_demand_must_be_non_negative() -> None:
    data = home_data()
    demand = [1.0] * 48
    demand[3] = -0.5
    data["demand_kw"] = demand

    with pytest.raises(ValidationError, match="demand_kw must be at least 0"):
        HomeDay.model_validate(data)


def test_home_day_defaults_identity_and_leaves_the_transformer_unset() -> None:
    day = HomeDay.model_validate(home_data())

    assert day.home_id == "home"
    assert day.region == "C"
    assert day.transformer_id is None


def test_home_day_keeps_an_explicit_identity() -> None:
    data = home_data()
    data["home_id"] = "home-7"
    data["region"] = "a"
    data["transformer_id"] = "tx-1"

    day = HomeDay.model_validate(data)

    assert day.home_id == "home-7"
    assert day.region == "a"
    assert day.transformer_id == "tx-1"


@pytest.mark.parametrize("field", ["home_id", "region"])
def test_home_identity_must_not_be_empty(field: str) -> None:
    data = home_data()
    data[field] = ""

    with pytest.raises(ValidationError, match=f"{field} must not be empty"):
        HomeDay.model_validate(data)


def test_home_day_rejects_demand_named_in_kwh() -> None:
    data = home_data()
    data["demand_kwh"] = data.pop("demand_kw")

    with pytest.raises(ValidationError, match="demand_kwh"):
        HomeDay.model_validate(data)
