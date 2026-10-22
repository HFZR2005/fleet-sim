"""Optimal schedule for one home.

The fields are the decision variables in ``docs/formulation.md``, plus the
tariff bill. That bill equals (COST) when every price adjustment is zero.
"""

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
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


def _field_name(info: ValidationInfo) -> str:
    if info.field_name is None:
        return "value"
    return info.field_name


def _require_slots(name: str, length: int) -> None:
    if length == 0:
        raise ValueError(f"{name} must contain at least one slot")
