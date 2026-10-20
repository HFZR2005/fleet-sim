"""Inputs for one home over one day.

The domains are the parameter table in ``docs/formulation.md``.
"""

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

SLOTS_PER_DAY = 48


class BatterySpec(BaseModel):
    """A single home battery.

    ``eta_charge`` and ``eta_discharge`` are fractions in (0, 1].
    ``soc_initial`` is a fraction in [0, 1].
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    eta_charge: float
    eta_discharge: float
    soc_initial: float

    @field_validator("capacity_kwh")
    @classmethod
    def capacity_is_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"capacity_kwh must be greater than 0 (got {value})")
        return value

    @field_validator("max_charge_kw", "max_discharge_kw")
    @classmethod
    def power_limit_is_non_negative(cls, value: float, info: ValidationInfo) -> float:
        if value < 0:
            name = _field_name(info)
            raise ValueError(f"{name} must be greater than or equal to 0 (got {value})")
        return value

    @field_validator("eta_charge", "eta_discharge")
    @classmethod
    def efficiency_is_open_fraction(cls, value: float, info: ValidationInfo) -> float:
        name = _field_name(info)
        if value > 1:
            raise ValueError(
                f"{name} must be a fraction in (0, 1]; 90% is written 0.9 (got {value})"
            )
        if value <= 0:
            raise ValueError(
                f"{name} must be greater than 0 and at most 1 (got {value})"
            )
        return value

    @field_validator("soc_initial")
    @classmethod
    def soc_is_closed_fraction(cls, value: float) -> float:
        if value > 1:
            raise ValueError(
                "soc_initial must be a fraction in [0, 1]; "
                f"90% is written 0.9 (got {value})"
            )
        if value < 0:
            raise ValueError(f"soc_initial must be in [0, 1] (got {value})")
        return value


class HomeDay(BaseModel):
    """One battery and one day of half-hourly demand and import prices.

    ``demand_kw`` is average power in kW. Energy in a slot is ``demand_kw * 0.5`` kWh.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    battery: BatterySpec
    demand_kw: list[float]
    price_p_per_kwh: list[float]

    @field_validator("demand_kw")
    @classmethod
    def demand_is_a_day_of_non_negative_power(cls, value: list[float]) -> list[float]:
        _require_day_length("demand_kw", value)
        for item in value:
            if item < 0:
                raise ValueError(
                    f"demand_kw must be at least 0 in every slot (got {item})"
                )
        return value

    @field_validator("price_p_per_kwh")
    @classmethod
    def prices_cover_a_day(cls, value: list[float]) -> list[float]:
        _require_day_length("price_p_per_kwh", value)
        return value


def _field_name(info: ValidationInfo) -> str:
    if info.field_name is None:
        return "value"
    return info.field_name


def _require_day_length(name: str, value: list[float]) -> None:
    if len(value) != SLOTS_PER_DAY:
        raise ValueError(
            f"{name} must contain {SLOTS_PER_DAY} half-hour values (got {len(value)})"
        )
