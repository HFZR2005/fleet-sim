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


class TestReproducibility:
    def test_same_seed_same_result(self) -> None:
        ids = _home_ids(20)
        settings = _settings()
        a = build_topology(ids, settings, RandomStreams(42))
        b = build_topology(ids, settings, RandomStreams(42))
        assert a.home_transformer == b.home_transformer
        for na, nb in zip(a.nodes, b.nodes, strict=True):
            assert na.node_id == nb.node_id
            assert na.limit_kw == nb.limit_kw
            assert na.location == nb.location

    def test_different_seeds_differ(self) -> None:
        ids = _home_ids(60)
        settings = _settings()
        a = build_topology(ids, settings, RandomStreams(1))
        b = build_topology(ids, settings, RandomStreams(2))
        assert a.home_transformer != b.home_transformer


class TestHomeAssignment:
    def test_every_home_is_assigned(self) -> None:
        ids = _home_ids(30)
        spec = build_topology(ids, _settings(), RandomStreams(7))
        assert set(spec.home_transformer) == set(ids)

    def test_single_home(self) -> None:
        ids = _home_ids(1)
        spec = build_topology(ids, _settings(n_transformers=1), RandomStreams(0))
        assert set(spec.home_transformer) == {"home-1"}

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one home"):
            build_topology([], _settings(), RandomStreams(0))


class TestTransformerSizing:
    def test_limits_are_standard_ratings(self) -> None:
        """Every transformer's limit equals some rating × power_factor."""
        settings = _settings()
        spec = build_topology(_home_ids(30), settings, RandomStreams(99))
        valid_limits = {r * settings.power_factor for r in settings.ratings_kva}
        for node in spec.nodes:
            if node.parent_id is not None:
                assert node.limit_kw is not None
                assert node.limit_kw in valid_limits

    def test_limits_cover_design_load(self) -> None:
        """Each transformer's limit is at least the design load of its homes."""
        settings = _settings()
        spec = build_topology(_home_ids(30), settings, RandomStreams(99))
        counts: dict[str, int] = {}
        for transformer_id in spec.home_transformer.values():
            counts[transformer_id] = counts.get(transformer_id, 0) + 1
        by_id = {node.node_id: node for node in spec.nodes}
        for node_id, count in counts.items():
            design_kw = count * settings.admd_kw * settings.headroom
            node = by_id[node_id]
            assert node.limit_kw is not None
            assert node.limit_kw >= design_kw

    def test_smallest_rating_is_chosen(self) -> None:
        """With one home and small ADMD, the smallest rating is picked."""
        settings = _settings(
            n_transformers=1,
            admd_kw=0.5,
            headroom=1.0,
            power_factor=1.0,
            ratings_kva=[25.0, 50.0],
        )
        spec = build_topology(_home_ids(1), settings, RandomStreams(0))
        transformer = next(n for n in spec.nodes if n.parent_id is not None)
        assert transformer.limit_kw == 25.0

    def test_largest_rating_when_load_exceeds_all(self) -> None:
        """When the design load exceeds every rating, the largest is used."""
        settings = _settings(
            n_transformers=1,
            admd_kw=50.0,
            headroom=1.0,
            power_factor=1.0,
            ratings_kva=[10.0, 20.0],
        )
        spec = build_topology(_home_ids(100), settings, RandomStreams(0))
        transformer = next(n for n in spec.nodes if n.parent_id is not None)
        assert transformer.limit_kw == 20.0

    def test_empty_transformer_gets_smallest_rating(self) -> None:
        """A transformer with no homes gets the smallest standard rating.

        With many transformers and few homes, some transformers may have
        zero homes assigned. Their design load is zero, so the smallest
        rating covers it.
        """
        settings = _settings(
            n_transformers=50,
            admd_kw=1.0,
            headroom=1.0,
            power_factor=1.0,
            ratings_kva=[25.0, 50.0],
        )
        spec = build_topology(_home_ids(2), settings, RandomStreams(0))
        empty_nodes = [
            n
            for n in spec.nodes
            if n.parent_id is not None
            and n.node_id not in spec.home_transformer.values()
        ]
        assert len(empty_nodes) > 0
        for node in empty_nodes:
            assert node.limit_kw == 25.0


class TestLocations:
    def test_locations_within_bounding_box(self) -> None:
        settings = _settings()
        spec = build_topology(_home_ids(20), settings, RandomStreams(5))
        for node in spec.nodes:
            if node.parent_id is None:
                assert node.location is None
                continue
            assert node.location is not None
            assert settings.lat_min <= node.location.latitude <= settings.lat_max
            assert settings.lon_min <= node.location.longitude <= settings.lon_max

    def test_root_has_no_location(self) -> None:
        spec = build_topology(_home_ids(5), _settings(), RandomStreams(0))
        root = next(n for n in spec.nodes if n.parent_id is None)
        assert root.location is None


class TestTreeStructure:
    def test_node_count(self) -> None:
        n = 4
        spec = build_topology(
            _home_ids(10), _settings(n_transformers=n), RandomStreams(0)
        )
        assert len(spec.nodes) == n + 1

    def test_root_is_unconstrained(self) -> None:
        spec = build_topology(_home_ids(10), _settings(), RandomStreams(0))
        root = next(n for n in spec.nodes if n.parent_id is None)
        assert root.limit_kw is None
