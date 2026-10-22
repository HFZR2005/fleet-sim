"""One home: the battery, the day the solver receives, and the schedule it returns.

The domains are the parameter table in ``docs/formulation.md``.
"""

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
    ``home_id`` and ``region`` identify the home. ``transformer_id`` is the
    network node above it, and nothing reads that field yet.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str = "home"
    region: str = "C"
    transformer_id: str | None = None
    battery: BatterySpec
    demand_kw: list[float]
    price_p_per_kwh: list[float]

    @field_validator("home_id", "region")
    @classmethod
    def identity_is_present(cls, value: str, info: ValidationInfo) -> str:
        if value == "":
            raise ValueError(f"{_field_name(info)} must not be empty")
        return value

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


class Schedule(BaseModel):
    """Charge, discharge, import, and state of charge for each slot.

    ``cost_pence`` is the tariff bill, ``price_p_per_kwh[t] *
    grid_import_kw[t] * 0.5``, summed over the horizon. It equals (COST) in
    ``docs/formulation.md`` when every price adjustment is zero.
    ``charge_mode[t]`` is 1 when the slot may charge
    and 0 when it may discharge. An idle slot may use either mode.
    ``solver`` is ``lp`` when the schedule came from the linear program and
    ``milp`` when a same-slot cycle made the solver add (MODE). A schedule
    that did not come from the optimiser leaves it unset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    charge_kw: list[float]
    discharge_kw: list[float]
    grid_import_kw: list[float]
    soc: list[float]
    charge_mode: list[int]
    cost_pence: float
    solver: Literal["lp", "milp"] | None = None

    @field_validator("charge_kw", "discharge_kw", "grid_import_kw")
    @classmethod
    def power_is_non_negative(
        cls, value: list[float], info: ValidationInfo
    ) -> list[float]:
        name = _field_name(info)
        _require_slots(name, len(value))
        for item in value:
            if item < 0:
                raise ValueError(
                    f"{name} must be at least 0 in every slot (got {item})"
                )
        return value

    @field_validator("soc")
    @classmethod
    def soc_is_a_fraction(cls, value: list[float]) -> list[float]:
        _require_slots("soc", len(value))
        for item in value:
            if item < 0 or item > 1:
                raise ValueError(f"soc must be in [0, 1] in every slot (got {item})")
        return value

    @field_validator("charge_mode")
    @classmethod
    def mode_is_binary(cls, value: list[int]) -> list[int]:
        _require_slots("charge_mode", len(value))
        for item in value:
            if item not in (0, 1):
                raise ValueError(
                    f"charge_mode must be 0 or 1 in every slot (got {item})"
                )
        return value

    @model_validator(mode="after")
    def slots_align(self) -> Self:
        lengths = (
            len(self.charge_kw),
            len(self.discharge_kw),
            len(self.grid_import_kw),
            len(self.soc),
            len(self.charge_mode),
        )
        if len(set(lengths)) != 1:
            raise ValueError(
                "charge_kw, discharge_kw, grid_import_kw, soc, and charge_mode "
                f"must have the same length (got {', '.join(str(n) for n in lengths)})"
            )
        return self


def _require_slots(name: str, length: int) -> None:
    if length == 0:
        raise ValueError(f"{name} must contain at least one slot")
