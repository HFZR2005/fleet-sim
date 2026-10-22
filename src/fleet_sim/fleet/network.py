"""One root node that adds up every home's grid import.

A ``NetworkSpec`` adds a transformer under that root. Flows on those
transformers are the sum of their homes. Overloads on that path are always
zero until the evaluation stub is replaced. A home does not see the node;
it only ever sees a price.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from fleet_sim.models.network import NetworkSpec
from fleet_sim.stubs import stub

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


def _evaluate_root(node_id: str, profiles: Sequence[HomeProfile]) -> list[NodeFeedback]:
    if len(profiles) == 0:
        raise ValueError("profiles must contain at least one home")
    n_slots = _slot_count(profiles)
    flow = [0.0] * n_slots
    for profile in profiles:
        for slot, imported in enumerate(profile.grid_import_kw):
            flow[slot] += imported
    return [
        NodeFeedback(
            node_id=node_id,
            flow_kw=flow,
            limit_kw=None,
            overload_kw=[0.0] * n_slots,
        )
    ]


@stub("transformer overloads are reported as zero")
def _evaluate_transformers(
    spec: NetworkSpec, profiles: Sequence[HomeProfile]
) -> list[NodeFeedback]:
    """Sum each home onto its transformer, and those totals onto the root.

    ``overload_kw`` is zero on every node. The limit is carried on the
    feedback and not compared with the flow.
    """
    if len(profiles) == 0:
        raise ValueError("profiles must contain at least one home")
    n_slots = _slot_count(profiles)
    by_home = {profile.home_id: profile for profile in profiles}
    if len(by_home) != len(profiles):
        raise ValueError("profiles must have unique home ids")
    expected = set(spec.home_transformer)
    if set(by_home) != expected:
        raise ValueError(
            "profiles must be exactly the homes on the network "
            f"(got {sorted(by_home)}, expected {sorted(expected)})"
        )
    flows = {node.node_id: [0.0] * n_slots for node in spec.nodes}
    for home_id, transformer_id in spec.home_transformer.items():
        for slot, imported in enumerate(by_home[home_id].grid_import_kw):
            flows[transformer_id][slot] += imported
    root = next(node for node in spec.nodes if node.parent_id is None)
    for node in spec.nodes:
        if node.parent_id == root.node_id:
            for slot in range(n_slots):
                flows[root.node_id][slot] += flows[node.node_id][slot]
    return [
        NodeFeedback(
            node_id=node.node_id,
            flow_kw=flows[node.node_id],
            limit_kw=node.limit_kw,
            overload_kw=[0.0] * n_slots,
        )
        for node in spec.nodes
    ]


def _slot_count(profiles: Sequence[HomeProfile]) -> int:
    n_slots = len(profiles[0].grid_import_kw)
    for profile in profiles:
        if len(profile.grid_import_kw) != n_slots:
            raise ValueError(
                "every profile must cover the same slots "
                f"(got {len(profile.grid_import_kw)} and {n_slots})"
            )
    return n_slots


class Network:
    """Homes under the root, or under the transformers in a ``NetworkSpec``."""

    def __init__(
        self, node_id: str = ROOT_NODE_ID, *, spec: NetworkSpec | None = None
    ) -> None:
        self._node_id = node_id
        self._spec = spec

    def evaluate(self, profiles: Sequence[HomeProfile]) -> list[NodeFeedback]:
        """Add the homes' imports into each node's flow.

        With no spec, the root has no limit and its overload is zero. With a
        spec, transformer flows are the homes on that transformer and the
        root is their sum. Overloads on that path are zero regardless of the
        limit.
        """
        if self._spec is None:
            return _evaluate_root(self._node_id, profiles)
        return _evaluate_transformers(self._spec, profiles)
