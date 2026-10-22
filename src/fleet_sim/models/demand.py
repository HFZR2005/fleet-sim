"""Half-hourly household demand for one civil day."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from fleet_sim.models.home import SLOTS_PER_DAY

ElexonSeason = Literal["Wtr", "Spr", "Smr", "Hsr", "Aut"]


class DemandSeries(BaseModel):
    """Energy demand for one day, one value per half-hour slot.

    ``demand_kwh[t]`` is energy in slot ``t``. Average power in kW is that
    energy divided by 0.5 hours, which is (DT) in ``docs/formulation.md``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    demand_kwh: list[float]

    @field_validator("demand_kwh")
    @classmethod
    def demand_is_a_day_of_non_negative_energy(cls, value: list[float]) -> list[float]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                "demand_kwh must contain "
                f"{SLOTS_PER_DAY} half-hour values (got {len(value)})"
            )
        for item in value:
            if item < 0:
                raise ValueError(
                    f"demand_kwh must be at least 0 in every slot (got {item})"
                )
        return value


class DemandFallback(BaseModel):
    """A simulated day that did not have a matching trial day.

    ``trial_day`` is the household day that was used instead. ``wanted_season``
    and ``wanted_weekend`` are what the simulated date asked for. A run stores
    this record in its metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    household_id: str
    simulated_day: date
    trial_day: date
    wanted_season: ElexonSeason
    wanted_weekend: bool


class HouseholdLoad(BaseModel):
    """One simulated day's demand, taken from one trial day of one household."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    series: DemandSeries
    household_id: str
    trial_day: date
    fallback: DemandFallback | None = None
