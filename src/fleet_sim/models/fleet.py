"""A set of homes, before the solve and after it."""

from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from fleet_sim.models.demand import DemandFallback
from fleet_sim.models.home import SLOTS_PER_DAY, BatterySpec, Schedule
from fleet_sim.models.network import NodeFeedback


class Home(BaseModel):
    """One home's identity, battery, and half-hourly demand.

    This is the standing description from the home config. A day's prices are
    not part of it. ``battery`` is omitted when the home has no battery.
    ``household_id`` is the Low Carbon London household this home keeps for a
    whole run, when the fleet was drawn from that pool. ``transformer_id`` is
    the network node above the home, and nothing reads that field yet.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    region: str
    transformer_id: str | None = None
    battery: BatterySpec | None = None
    household_id: str | None = None
    demand_kw: list[float]

    @field_validator("home_id", "region")
    @classmethod
    def identity_is_present(cls, value: str, info: ValidationInfo) -> str:
        if value == "":
            name = "value" if info.field_name is None else info.field_name
            raise ValueError(f"{name} must not be empty")
        return value

    @field_validator("demand_kw")
    @classmethod
    def demand_is_a_day_of_non_negative_power(cls, value: list[float]) -> list[float]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                "demand_kw must contain "
                f"{SLOTS_PER_DAY} half-hour values (got {len(value)})"
            )
        for item in value:
            if item < 0:
                raise ValueError(
                    f"demand_kw must be at least 0 in every slot (got {item})"
                )
        return value


class Fleet(BaseModel):
    """Homes whose ``home_id`` values can be told apart."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    homes: list[Home]

    @model_validator(mode="after")
    def home_ids_are_unique(self) -> Self:
        seen: set[str] = set()
        for home in self.homes:
            if home.home_id in seen:
                raise ValueError(f"duplicate home_id {home.home_id!r}")
            seen.add(home.home_id)
        return self


class GeneratedFleet(BaseModel):
    """A fleet for one day, plus any trial-day fallbacks behind its demand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fleet: Fleet
    fallbacks: list[DemandFallback]


class SolvedHome(BaseModel):
    """One home's schedule for the day, with the demand it was given."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    transformer_id: str | None
    demand_kw: list[float]
    schedule: Schedule


class FleetDay(BaseModel):
    """Schedules for every home, and the network's flow for the day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    homes: list[SolvedHome]
    nodes: list[NodeFeedback]
