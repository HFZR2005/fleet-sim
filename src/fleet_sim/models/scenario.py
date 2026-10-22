"""One experiment, complete enough to run again.

The fields are the choices that change a fleet result: who is simulated,
how batteries are drawn, and the seed those draws start from.
"""

from datetime import date
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from fleet_sim.models.network import NetworkSettings
from fleet_sim.models.prices import require_gsp_region

FleetMode = Literal["diverse", "identical"]


class BatteryProductSpec(BaseModel):
    """One capacity and the inverter ratings sold with it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity_kwh: float
    power_kw: list[float]
    weight: float

    @field_validator("capacity_kwh")
    @classmethod
    def capacity_is_positive(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"capacity_kwh must be a number (got {value!r})")
        if value <= 0:
            raise ValueError(f"capacity_kwh must be greater than 0 (got {value})")
        return float(value)

    @field_validator("power_kw")
    @classmethod
    def powers_are_non_negative(cls, value: list[float]) -> list[float]:
        if len(value) == 0:
            raise ValueError("power_kw must contain at least one rating")
        for power in value:
            if power < 0:
                raise ValueError(f"power_kw must be at least 0 (got {power})")
        return value

    @field_validator("weight")
    @classmethod
    def weight_is_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"weight must be greater than 0 (got {value})")
        return float(value)


class EfficiencyDistribution(BaseModel):
    """A normal draw of one-way efficiency, kept inside ``[low, high]``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mean: float
    standard_deviation: float
    low: float
    high: float

    @model_validator(mode="after")
    def bounds_hold_the_mean(self) -> Self:
        if self.standard_deviation <= 0:
            raise ValueError(
                "standard_deviation must be greater than 0 "
                f"(got {self.standard_deviation})"
            )
        if not 0 < self.low < self.high <= 1:
            raise ValueError(
                "efficiency bounds must satisfy 0 < low < high <= 1 "
                f"(got low {self.low}, high {self.high})"
            )
        if not self.low <= self.mean <= self.high:
            raise ValueError(
                f"mean must sit inside [{self.low}, {self.high}] (got {self.mean})"
            )
        return self


class BatteryDistribution(BaseModel):
    """The products and efficiencies a fleet draws its batteries from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    products: list[BatteryProductSpec]
    efficiency: EfficiencyDistribution
    soc_initial: float

    @field_validator("products")
    @classmethod
    def there_is_a_product(
        cls, value: list[BatteryProductSpec]
    ) -> list[BatteryProductSpec]:
        if len(value) == 0:
            raise ValueError("products must contain at least one battery")
        return value

    @field_validator("soc_initial")
    @classmethod
    def soc_is_a_fraction(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(f"soc_initial must be in [0, 1] (got {value})")
        return float(value)


class Scenario(BaseModel):
    """The file that fixes one experiment.

    ``penetration`` is one level, or a list of levels. A list is the
    penetration sweep. Running that sweep is a later issue; this model
    only records it. ``seed`` is the master seed. ``replications`` is how
    many times that experiment is repeated. Repeating it is a later issue.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_homes: int
    penetration: float | list[float]
    mode: FleetMode
    region: str
    start: date
    end: date
    seed: int
    replications: int
    battery: BatteryDistribution
    network: NetworkSettings | None = None

    @field_validator("n_homes", "replications", "seed", mode="before")
    @classmethod
    def counts_are_ints(cls, value: object, info: ValidationInfo) -> object:
        name = "value" if info.field_name is None else info.field_name
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int (got {value!r})")
        return value

    @field_validator("n_homes", "replications")
    @classmethod
    def counts_are_positive(cls, value: int, info: ValidationInfo) -> int:
        if value < 1:
            name = "value" if info.field_name is None else info.field_name
            raise ValueError(f"{name} must be at least 1 (got {value})")
        return value

    @field_validator("seed")
    @classmethod
    def seed_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"seed must be at least 0 (got {value})")
        return value

    @field_validator("region")
    @classmethod
    def region_is_a_gsp_letter(cls, value: str) -> str:
        return require_gsp_region(value)

    @field_validator("penetration", mode="before")
    @classmethod
    def penetration_is_a_fraction(cls, value: object) -> float | list[float]:
        levels = value if isinstance(value, list) else [value]
        if len(levels) == 0:
            raise ValueError("penetration must contain at least one level")
        checked: list[float] = []
        for level in levels:
            if isinstance(level, bool) or not isinstance(level, int | float):
                raise TypeError(f"penetration must be a float (got {level!r})")
            if not 0 <= float(level) <= 1:
                raise ValueError(f"penetration must be in [0, 1] (got {level})")
            checked.append(float(level))
        if isinstance(value, list):
            return checked
        return checked[0]

    @model_validator(mode="after")
    def the_range_runs_forward(self) -> Self:
        if self.end < self.start:
            raise ValueError(
                f"end {self.end.isoformat()} is before start {self.start.isoformat()}"
            )
        return self

    def penetration_levels(self) -> list[float]:
        """Every penetration this file names, as a list."""
        if isinstance(self.penetration, list):
            return list(self.penetration)
        return [self.penetration]


class RunMetadata(BaseModel):
    """What was run, written next to the outputs.

    ``seed`` is the scenario's master seed, repeated here so a reader can
    see it without opening the scenario. ``git_commit`` is the commit the
    run was started from.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: Scenario
    seed: int
    package_version: str
    git_commit: str

    @model_validator(mode="after")
    def seed_matches_the_scenario(self) -> Self:
        if self.seed != self.scenario.seed:
            raise ValueError(
                f"seed {self.seed} does not match the scenario seed {self.scenario.seed}"
            )
        return self
