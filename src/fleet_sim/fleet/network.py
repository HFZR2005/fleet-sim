"""One root node that adds up every home's grid import.

Through milestone 3 this network has no limit. Transformers arrive later,
inside this type. A home does not see the node; it only ever sees a price.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

ROOT_NODE_ID = "root"


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


class Network:
    """Every home under one root node, with no flow limit."""

    def __init__(self, node_id: str = ROOT_NODE_ID) -> None:
        self._node_id = node_id

    def evaluate(self, profiles: Sequence[HomeProfile]) -> list[NodeFeedback]:
        """Add the homes' imports into the root node's flow.

        The root has no limit, so its overload is zero in every slot.
        """
        if len(profiles) == 0:
            raise ValueError("profiles must contain at least one home")
        n_slots = len(profiles[0].grid_import_kw)
        for profile in profiles:
            if len(profile.grid_import_kw) != n_slots:
                raise ValueError(
                    "every profile must cover the same slots "
                    f"(got {len(profile.grid_import_kw)} and {n_slots})"
                )
        flow = [0.0] * n_slots
        for profile in profiles:
            for slot, imported in enumerate(profile.grid_import_kw):
                flow[slot] += imported
        return [
            NodeFeedback(
                node_id=self._node_id,
                flow_kw=flow,
                limit_kw=None,
                overload_kw=[0.0] * n_slots,
            )
        ]
