"""Build the transformer tree a fleet sits on.

The real generator, with a random stream and standard ratings, is a later
issue. This split is deterministic and carries no locations.
"""

from fleet_sim.models.fleet import Fleet, Home
from fleet_sim.models.network import NetworkNode, NetworkSettings, NetworkSpec
from fleet_sim.stubs import stub


def assign_transformers(fleet: Fleet, spec: NetworkSpec) -> Fleet:
    """Set each home's ``transformer_id`` from ``spec``."""
    homes: list[Home] = []
    for home in fleet.homes:
        transformer_id = spec.home_transformer.get(home.home_id)
        if transformer_id is None:
            raise ValueError(f"home {home.home_id} has no transformer")
        homes.append(home.model_copy(update={"transformer_id": transformer_id}))
    return Fleet(homes=homes)


@stub("homes are split into equal groups, one fixed limit, no locations")
def build_topology(home_ids: list[str], settings: NetworkSettings) -> NetworkSpec:
    """Put ``home_ids`` into ``settings.n_transformers`` equal groups.

    Homes keep the order they are given. Each transformer gets
    ``settings.limit_kw`` and no location. The root is unconstrained.
    """
    if len(home_ids) == 0:
        raise ValueError("home_ids must contain at least one home")
    if len(home_ids) % settings.n_transformers != 0:
        raise ValueError(
            f"{len(home_ids)} homes do not split equally across "
            f"{settings.n_transformers} transformers"
        )
    per_transformer = len(home_ids) // settings.n_transformers
    nodes = [NetworkNode(node_id="root", parent_id=None, limit_kw=None, location=None)]
    home_transformer: dict[str, str] = {}
    for index in range(settings.n_transformers):
        node_id = f"transformer-{index + 1}"
        nodes.append(
            NetworkNode(
                node_id=node_id,
                parent_id="root",
                limit_kw=settings.limit_kw,
                location=None,
            )
        )
        start = index * per_transformer
        for home_id in home_ids[start : start + per_transformer]:
            home_transformer[home_id] = node_id
    return NetworkSpec(nodes=nodes, home_transformer=home_transformer)
