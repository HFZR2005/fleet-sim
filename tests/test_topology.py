"""The topology generator assigns homes, sizes transformers, and places them."""

import pytest

from fleet_sim.fleet.topology import build_topology
from fleet_sim.models.network import NetworkSettings
from fleet_sim.random_streams import RandomStreams


def _settings(**overrides: object) -> NetworkSettings:
    defaults: dict[str, object] = {
        "n_transformers": 3,
        "admd_kw": 2.0,
        "headroom": 1.2,
        "power_factor": 0.95,
        "ratings_kva": [25.0, 50.0, 100.0, 200.0],
        "lat_min": 51.3,
        "lat_max": 51.7,
        "lon_min": -0.3,
        "lon_max": 0.1,
    }
    defaults.update(overrides)
    return NetworkSettings(**defaults)


def _home_ids(n: int) -> list[str]:
    return [f"home-{i + 1}" for i in range(n)]


def test_the_same_seed_builds_the_same_topology() -> None:
    ids = _home_ids(60)
    settings = _settings()
    a = build_topology(ids, settings, RandomStreams(42))
    b = build_topology(ids, settings, RandomStreams(42))
    c = build_topology(ids, settings, RandomStreams(43))
    assert a == b
    assert a.home_transformer != c.home_transformer


def test_topology_is_a_sized_and_placed_two_level_tree() -> None:
    """Every home is assigned; each transformer has a standard rating × power
    factor that covers its design load (homes × ADMD × headroom) and sits in the
    bounding box; the root has no limit and no location.
    """
    ids = _home_ids(30)
    settings = _settings(n_transformers=4)
    spec = build_topology(ids, settings, RandomStreams(99))

    assert set(spec.home_transformer) == set(ids)
    assert len(spec.nodes) == 4 + 1

    root = next(n for n in spec.nodes if n.parent_id is None)
    assert root.limit_kw is None
    assert root.location is None

    counts: dict[str, int] = {}
    for transformer_id in spec.home_transformer.values():
        counts[transformer_id] = counts.get(transformer_id, 0) + 1
    valid_limits = {r * settings.power_factor for r in settings.ratings_kva}
    for node in spec.nodes:
        if node.parent_id is None:
            continue
        design_kw = counts.get(node.node_id, 0) * settings.admd_kw * settings.headroom
        assert node.limit_kw in valid_limits
        assert node.limit_kw is not None
        assert node.limit_kw >= design_kw
        assert node.location is not None
        assert settings.lat_min <= node.location.latitude <= settings.lat_max
        assert settings.lon_min <= node.location.longitude <= settings.lon_max


@pytest.mark.parametrize(
    ("n_homes", "admd_kw", "ratings_kva", "expected_kw"),
    [
        # Design load 1 × 0.5 = 0.5 kW: the smallest rating covers it.
        (1, 0.5, [25.0, 50.0], 25.0),
        # Design load 100 × 50 = 5000 kW exceeds every rating: use the largest.
        (100, 50.0, [10.0, 20.0], 20.0),
    ],
)
def test_the_smallest_covering_rating_is_chosen(
    n_homes: int, admd_kw: float, ratings_kva: list[float], expected_kw: float
) -> None:
    settings = _settings(
        n_transformers=1,
        admd_kw=admd_kw,
        headroom=1.0,
        power_factor=1.0,
        ratings_kva=ratings_kva,
    )
    spec = build_topology(_home_ids(n_homes), settings, RandomStreams(0))
    transformer = next(n for n in spec.nodes if n.parent_id is not None)
    assert transformer.limit_kw == expected_kw


def test_a_transformer_without_homes_gets_the_smallest_rating() -> None:
    """50 transformers and 2 homes leave most transformers empty."""
    settings = _settings(
        n_transformers=50,
        admd_kw=1.0,
        headroom=1.0,
        power_factor=1.0,
        ratings_kva=[25.0, 50.0],
    )
    spec = build_topology(_home_ids(2), settings, RandomStreams(0))
    empty = [
        n
        for n in spec.nodes
        if n.parent_id is not None and n.node_id not in spec.home_transformer.values()
    ]
    assert empty
    assert all(n.limit_kw == 25.0 for n in empty)


def test_no_homes_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one home"):
        build_topology([], _settings(), RandomStreams(0))
