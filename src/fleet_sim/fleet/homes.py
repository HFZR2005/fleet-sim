"""A fleet of homes that share one battery and one demand shape.

Each home keeps its own ``home_id``. Later results can name a home by that id.
"""

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

from fleet_sim.models.home import SLOTS_PER_DAY, BatterySpec


class Home(BaseModel):
    """One home's identity, battery, and half-hourly demand.

    This is the standing description from the home config. A day's prices are
    not part of it. ``transformer_id`` is the network node above the home,
    and nothing reads that field yet.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    region: str
    transformer_id: str | None = None
    battery: BatterySpec
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
    def home_ids_are_unique(self) -> "Fleet":
        seen: set[str] = set()
        for home in self.homes:
            if home.home_id in seen:
                raise ValueError(f"duplicate home_id {home.home_id!r}")
            seen.add(home.home_id)
        return self


def identical_homes(home: Home, n_homes: int) -> Fleet:
    """Build ``n_homes`` copies of one home config.

    ``home`` is the config's home: identity, battery, and demand. The copies
    share that battery, demand, region, and transformer. Each ``home_id`` is
    ``{home.home_id}-{index}`` with ``index`` starting at 1, so the copies
    do not share an id.
    """
    if isinstance(n_homes, bool) or not isinstance(n_homes, int):
        raise TypeError(f"n_homes must be an int (got {n_homes!r})")
    if n_homes < 1:
        raise ValueError(f"n_homes must be at least 1 (got {n_homes})")
    copies = [
        home.model_copy(
            update={
                "home_id": f"{home.home_id}-{index}",
                "demand_kw": list(home.demand_kw),
            }
        )
        for index in range(1, n_homes + 1)
    ]
    return Fleet(homes=copies)
