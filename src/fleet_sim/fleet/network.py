"""One root node that adds up every home's grid import.

A ``NetworkSpec`` adds the nodes between that root and the homes. Flow is
summed from the leaves upward. A home does not see the node; it only ever
sees a price.
"""

from collections.abc import Sequence

from fleet_sim.models.network import HomeProfile, NetworkSpec, NodeFeedback

ROOT_NODE_ID = "root"


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


def _evaluate_transformers(
    spec: NetworkSpec, profiles: Sequence[HomeProfile]
) -> list[NodeFeedback]:
    """Flow at each node, then its overload. See ``docs/formulation.md``, Network.

    Nodes are visited from the leaves upward. A node's flow in a slot is the
    sum of the imports of the homes attached to it and the flow of each
    child. Overload is ``max(0, flow - limit)`` when the node has a limit,
    and zero when it does not.
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
    children, order = _leaves_first(spec)
    attached: dict[str, list[HomeProfile]] = {node.node_id: [] for node in spec.nodes}
    for home_id, node_id in spec.home_transformer.items():
        attached[node_id].append(by_home[home_id])
    flows: dict[str, list[float]] = {}
    for node_id in order:
        flow = [0.0] * n_slots
        for profile in attached[node_id]:
            for slot, imported in enumerate(profile.grid_import_kw):
                flow[slot] += imported
        for child_id in children[node_id]:
            for slot, child_flow in enumerate(flows[child_id]):
                flow[slot] += child_flow
        flows[node_id] = flow
    return [
        NodeFeedback(
            node_id=node.node_id,
            flow_kw=flows[node.node_id],
            limit_kw=node.limit_kw,
            overload_kw=_overload(flows[node.node_id], node.limit_kw),
        )
        for node in spec.nodes
    ]


def _leaves_first(spec: NetworkSpec) -> tuple[dict[str, list[str]], list[str]]:
    """Child ids of each node, and every node id with children before parents."""
    children: dict[str, list[str]] = {node.node_id: [] for node in spec.nodes}
    root_id = next(node.node_id for node in spec.nodes if node.parent_id is None)
    for node in spec.nodes:
        if node.parent_id is not None:
            children[node.parent_id].append(node.node_id)
    order: list[str] = []

    def visit(node_id: str) -> None:
        for child_id in children[node_id]:
            visit(child_id)
        order.append(node_id)

    visit(root_id)
    return children, order


def _overload(flow: list[float], limit_kw: float | None) -> list[float]:
    if limit_kw is None:
        return [0.0] * len(flow)
    return [max(0.0, slot - limit_kw) for slot in flow]


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
        spec, each node's flow is summed from the leaves upward, and overload
        is how far that flow sits above the node's limit.
        """
        if self._spec is None:
            return _evaluate_root(self._node_id, profiles)
        return _evaluate_transformers(self._spec, profiles)
