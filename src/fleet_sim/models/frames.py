"""One record per half-hour, the view every later chart reads.

``demand_kw`` sits beside ``import_kw`` so a chart can draw the
without-battery import from the file alone. ``import_kw`` is the scheduled
grid import.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from fleet_sim.models.scenario import RunMetadata

HomeMode = Literal["charging", "discharging", "idle"]


class HomeFrame(BaseModel):
    """One home in one slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    transformer_id: str | None
    soc: float
    mode: HomeMode
    import_kw: float
    demand_kw: float

    @field_validator("soc")
    @classmethod
    def soc_is_a_fraction(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(f"soc must be in [0, 1] (got {value})")
        return value

    @field_validator("import_kw", "demand_kw")
    @classmethod
    def power_is_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError(f"power must be at least 0 (got {value})")
        return value


class NodeFrame(BaseModel):
    """One network node in one slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    flow_kw: float
    limit_kw: float | None
    overload_kw: float


class Frame(BaseModel):
    """One half-hour: the price, each home, and each node's flow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_start: datetime
    price_p_per_kwh: float
    homes: list[HomeFrame]
    nodes: list[NodeFrame]


class FrameLog(BaseModel):
    """The JSON file a run writes. ``schema_version`` is 1.

    ``metadata`` is set when the frames come from a scenario run. It is the
    same record written beside the other outputs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    frames: list[Frame]
    metadata: RunMetadata | None = None
