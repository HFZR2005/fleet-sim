"""Build the transformer tree a fleet sits on.

Each home is assigned to a uniformly random transformer. The transformer's
limit comes from its home count, the after-diversity maximum demand, and the
headroom, rounded up to a standard rating. See ``docs/assumptions.md``.
"""

import numpy as np

from fleet_sim.models.fleet import Fleet, Home
from fleet_sim.models.network import Location, NetworkNode, NetworkSettings, NetworkSpec
from fleet_sim.random_streams import RandomStreams


def assign_transformers(fleet: Fleet, spec: NetworkSpec) -> Fleet:
    """Set each home's ``transformer_id`` from ``spec``."""
    homes: list[Home] = []
    for home in fleet.homes:
        transformer_id = spec.home_transformer.get(home.home_id)
        if transformer_id is None:
            raise ValueError(f"home {home.home_id} has no transformer")
        homes.append(home.model_copy(update={"transformer_id": transformer_id}))
    return Fleet(homes=homes)


def build_topology(
    home_ids: list[str],
    settings: NetworkSettings,
    streams: RandomStreams,
) -> NetworkSpec:
    """Assign homes to transformers and size each one.

    Homes are placed uniformly at random across ``settings.n_transformers``
    transformers. Each transformer's limit is the smallest standard rating
    that covers the design load of the homes it serves:

        design_kw = n_homes_on_transformer × admd_kw × headroom
        required_kva = design_kw / power_factor
        selected_kva = smallest rating ≥ required_kva
        limit_kw = selected_kva × power_factor

    See ``docs/assumptions.md``, Transformer sizing.
    """
    if len(home_ids) == 0:
        raise ValueError("home_ids must contain at least one home")
    n = settings.n_transformers
    gen = streams.generator("topology")
    assignments = gen.integers(0, n, size=len(home_ids))
    home_transformer: dict[str, str] = {}  # home_id -> transformer_id
    counts: dict[int, int] = {i: 0 for i in range(n)}
    for home_id, transformer_index in zip(home_ids, assignments, strict=True):
        idx = int(transformer_index)
        node_id = f"transformer-{idx + 1}"
        home_transformer[home_id] = node_id
        counts[idx] = counts.get(idx, 0) + 1
    ratings = sorted(settings.ratings_kva)
    nodes = [NetworkNode(node_id="root", parent_id=None, limit_kw=None, location=None)]
    for index in range(n):
        node_id = f"transformer-{index + 1}"
        homes_on = counts[index]
        limit_kw = _transformer_limit_kw(
            homes_on,
            settings.admd_kw,
            settings.headroom,
            settings.power_factor,
            ratings,
        )
        location = _random_location(
            gen,
            settings.lat_min,
            settings.lat_max,
            settings.lon_min,
            settings.lon_max,
        )
        nodes.append(
            NetworkNode(
                node_id=node_id,
                parent_id="root",
                limit_kw=limit_kw,
                location=location,
            )
        )
    return NetworkSpec(nodes=nodes, home_transformer=home_transformer)


def _transformer_limit_kw(
    n_homes: int,
    admd_kw: float,
    headroom: float,
    power_factor: float,
    ratings_kva: list[float],
) -> float:
    """Smallest standard rating that covers the design load, in kW.

    See ``docs/assumptions.md``, Transformer sizing.
    """
    design_kw = n_homes * admd_kw * headroom
    required_kva = design_kw / power_factor
    for rating in ratings_kva:
        if rating >= required_kva:
            return rating * power_factor
    return ratings_kva[-1] * power_factor


def _random_location(
    gen: np.random.Generator,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> Location:
    lat = float(gen.uniform(lat_min, lat_max))
    lon = float(gen.uniform(lon_min, lon_max))
    return Location(latitude=lat, longitude=lon)
