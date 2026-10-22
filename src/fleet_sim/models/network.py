"""The network a scenario names, the flow on it, and how far a limit was exceeded.

``NetworkSettings`` is the ``[network]`` section of a scenario. ``NetworkSpec``
is the tree a run builds. ``HomeProfile`` is the only view of a home that
evaluation receives. ``NodeFeedback`` is the flow that comes back, and the
overload types reduce that flow to how far a transformer sat over its limit.
"""

from datetime import date
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class Location(BaseModel):
    """A point, in degrees, for a later map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: float
    longitude: float

    @field_validator("latitude")
    @classmethod
    def latitude_is_in_range(cls, value: float) -> float:
        if value < -90 or value > 90:
            raise ValueError(f"latitude must be in [-90, 90] (got {value})")
        return float(value)

    @field_validator("longitude")
    @classmethod
    def longitude_is_in_range(cls, value: float) -> float:
        if value < -180 or value > 180:
            raise ValueError(f"longitude must be in [-180, 180] (got {value})")
        return float(value)


class NetworkNode(BaseModel):
    """One node in the tree.

    ``parent_id`` is ``None`` only for the root. ``limit_kw`` is ``None``
    when the node is unconstrained. ``location`` is ``None`` until a later
    issue places the node.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    parent_id: str | None = None
    limit_kw: float | None = None
    location: Location | None = None

    @field_validator("node_id")
    @classmethod
    def node_id_is_present(cls, value: str) -> str:
        if value == "":
            raise ValueError("node_id must not be empty")
        return value

    @field_validator("limit_kw")
    @classmethod
    def limit_is_positive(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"limit_kw must be a number (got {value!r})")
        if value <= 0:
            raise ValueError(f"limit_kw must be greater than 0 (got {value})")
        return float(value)


class NetworkSpec(BaseModel):
    """A tree of nodes, and which transformer each home sits under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: list[NetworkNode]
    home_transformer: dict[str, str]

    @model_validator(mode="after")
    def the_nodes_form_a_tree(self) -> Self:
        if len(self.nodes) == 0:
            raise ValueError("nodes must contain at least the root")
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node_id values must be unique")
        known = set(ids)
        roots = [node for node in self.nodes if node.parent_id is None]
        if len(roots) != 1:
            raise ValueError(f"the tree must have one root (got {len(roots)})")
        by_id = {node.node_id: node for node in self.nodes}
        for node in self.nodes:
            parent = node.parent_id
            if parent is None:
                continue
            if parent not in known:
                raise ValueError(
                    f"node {node.node_id} names an unknown parent {parent}"
                )
            seen = {node.node_id}
            while parent is not None:
                if parent in seen:
                    raise ValueError(f"node {node.node_id} is in a cycle")
                seen.add(parent)
                parent = by_id[parent].parent_id
        for home_id, transformer_id in self.home_transformer.items():
            if home_id == "":
                raise ValueError("home_id must not be empty")
            if transformer_id not in known:
                raise ValueError(
                    f"home {home_id} names an unknown transformer {transformer_id}"
                )
            if by_id[transformer_id].parent_id is None:
                raise ValueError(f"home {home_id} is placed on the root")
        return self


class NetworkSettings(BaseModel):
    """The ``[network]`` section of a scenario.

    The topology stub reads ``n_transformers`` and ``limit_kw``. The other
    fields are the sizing, location, and clustering parameters later issues
    use. They are accepted and ignored until those stubs are replaced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_transformers: int
    limit_kw: float
    rho: float = 0.0
    admd_kw: float = 1.0
    headroom: float = 1.0
    power_factor: float = 1.0
    ratings_kva: list[float] = Field(default_factory=lambda: [25.0, 50.0, 100.0])
    lat_min: float = 51.3
    lat_max: float = 51.7
    lon_min: float = -0.3
    lon_max: float = 0.1

    @field_validator("n_transformers", mode="before")
    @classmethod
    def transformer_count_is_an_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"n_transformers must be an int (got {value!r})")
        return value

    @field_validator("n_transformers")
    @classmethod
    def transformer_count_is_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"n_transformers must be at least 1 (got {value})")
        return value

    @field_validator("limit_kw", "admd_kw", "headroom")
    @classmethod
    def positive_quantities(cls, value: float, info: ValidationInfo) -> float:
        name = "value" if info.field_name is None else info.field_name
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"{name} must be a number (got {value!r})")
        if value <= 0:
            raise ValueError(f"{name} must be greater than 0 (got {value})")
        return float(value)

    @field_validator("rho")
    @classmethod
    def rho_is_a_fraction(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"rho must be a number (got {value!r})")
        if not 0 <= float(value) <= 1:
            raise ValueError(f"rho must be in [0, 1] (got {value})")
        return float(value)

    @field_validator("power_factor")
    @classmethod
    def power_factor_is_a_fraction(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError(f"power_factor must be a number (got {value!r})")
        if not 0 < float(value) <= 1:
            raise ValueError(f"power_factor must be in (0, 1] (got {value})")
        return float(value)

    @field_validator("ratings_kva")
    @classmethod
    def ratings_are_positive(cls, value: list[float]) -> list[float]:
        if len(value) == 0:
            raise ValueError("ratings_kva must contain at least one rating")
        checked: list[float] = []
        for rating in value:
            if isinstance(rating, bool) or not isinstance(rating, int | float):
                raise TypeError(f"ratings_kva must be numbers (got {rating!r})")
            if rating <= 0:
                raise ValueError(f"ratings_kva must be greater than 0 (got {rating})")
            checked.append(float(rating))
        return checked

    @model_validator(mode="after")
    def the_box_is_ordered(self) -> Self:
        if self.lat_min >= self.lat_max:
            raise ValueError(
                f"lat_min {self.lat_min} must be below lat_max {self.lat_max}"
            )
        if self.lon_min >= self.lon_max:
            raise ValueError(
                f"lon_min {self.lon_min} must be below lon_max {self.lon_max}"
            )
        return self


class HomeProfile(BaseModel):
    """Grid import of one solved home, in kW, one value per slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str
    grid_import_kw: list[float]

    @field_validator("grid_import_kw")
    @classmethod
    def import_is_non_negative(cls, value: list[float]) -> list[float]:
        if len(value) == 0:
            raise ValueError("grid_import_kw must contain at least one slot")
        for item in value:
            if item < 0:
                raise ValueError(
                    f"grid_import_kw must be at least 0 in every slot (got {item})"
                )
        return value


class NodeFeedback(BaseModel):
    """Flow through one network node over the day.

    ``limit_kw`` is ``None`` when the node is unconstrained. ``overload_kw``
    is how far ``flow_kw`` sits above that limit, and it is zero when there
    is no limit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    flow_kw: list[float]
    limit_kw: float | None
    overload_kw: list[float]


class TransformerOverload(BaseModel):
    """One transformer on one day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    peak_utilisation: float
    overload_energy_kwh: float
    overloaded_slots: int


class DayOverload(BaseModel):
    """Every transformer on one civil day, plus the hidden-overload share.

    The hidden-overload share is the fraction of slots where the fleet total
    is inside the sum of the limits but at least one transformer is over its
    own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    transformers: list[TransformerOverload]
    hidden_overload_share: float


class ReplicationOverload(BaseModel):
    """The day's overloads, reduced to one replication.

    ``overload_hour`` is the hour of day in which overloaded slots occur
    most. It is ``None`` when no slot is overloaded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transformers_overloaded_share: float
    mean_peak_utilisation: float
    worst_peak_utilisation: float
    total_overload_energy_kwh: float
    overload_hour: int | None
    hidden_overload_share: float
