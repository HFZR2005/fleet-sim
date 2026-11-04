"""Clustered battery ownership: ρ blends individual and transformer draws."""

from datetime import date
from pathlib import Path

import pytest

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.fleet.generate import (
    _clustered_scores,
    _owned_indices,
    battery_owner_count,
    generate_fleet,
)
from fleet_sim.fleet.topology import build_topology
from fleet_sim.models.network import NetworkSettings
from fleet_sim.random_streams import RandomStreams

_FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2026, 1, 1)


def _pool() -> HouseholdDemandPool:
    return HouseholdDemandPool.read(_FIXTURE)


def _network_settings(**overrides: object) -> NetworkSettings:
    defaults: dict[str, object] = {
        "n_transformers": 2,
        "admd_kw": 1.0,
        "headroom": 1.0,
        "power_factor": 1.0,
        "ratings_kva": [100.0],
        "lat_min": 51.3,
        "lat_max": 51.7,
        "lon_min": -0.3,
        "lon_max": 0.1,
    }
    defaults.update(overrides)
    return NetworkSettings(**defaults)


class TestRhoZeroRegression:
    """With ρ = 0, ownership is identical to milestone 3's for the same seed."""

    def test_same_owners_as_without_transformer_map(self) -> None:
        pool = _pool()
        seed = 11
        penetration = 0.5

        without = generate_fleet(pool, _DAY, 2, seed, penetration)
        owners_without = {
            h.home_id for h in without.fleet.homes if h.battery is not None
        }

        settings = _network_settings()
        home_ids = [f"home-{i + 1}" for i in range(2)]
        spec = build_topology(home_ids, settings, RandomStreams(seed))

        with_map = generate_fleet(
            pool,
            _DAY,
            2,
            seed,
            penetration,
            transformer_map=spec.home_transformer,
            rho=0.0,
        )
        owners_with = {h.home_id for h in with_map.fleet.homes if h.battery is not None}

        assert owners_without == owners_with

    def test_same_batteries_as_without_transformer_map(self) -> None:
        pool = _pool()
        seed = 11

        without = generate_fleet(pool, _DAY, 2, seed, 1.0)
        settings = _network_settings()
        home_ids = [f"home-{i + 1}" for i in range(2)]
        spec = build_topology(home_ids, settings, RandomStreams(seed))

        with_map = generate_fleet(
            pool, _DAY, 2, seed, 1.0, transformer_map=spec.home_transformer, rho=0.0
        )

        for a, b in zip(without.fleet.homes, with_map.fleet.homes, strict=True):
            assert a.battery == b.battery


class TestExactCounts:
    def test_count_at_various_penetrations(self) -> None:
        pool = _pool()
        seed = 42
        settings = _network_settings()
        home_ids = [f"home-{i + 1}" for i in range(2)]
        spec = build_topology(home_ids, settings, RandomStreams(seed))

        for p in [0.0, 0.25, 0.5, 0.75, 1.0]:
            fleet = generate_fleet(
                pool,
                _DAY,
                2,
                seed,
                p,
                transformer_map=spec.home_transformer,
                rho=0.5,
            )
            n_owners = sum(1 for h in fleet.fleet.homes if h.battery is not None)
            assert n_owners == battery_owner_count(p, 2)


class TestNesting:
    def test_lower_penetration_is_a_subset(self) -> None:
        pool = _pool()
        seed = 7
        settings = _network_settings()
        home_ids = [f"home-{i + 1}" for i in range(2)]
        spec = build_topology(home_ids, settings, RandomStreams(seed))

        low = generate_fleet(
            pool,
            _DAY,
            2,
            seed,
            0.25,
            transformer_map=spec.home_transformer,
            rho=0.8,
        )
        high = generate_fleet(
            pool,
            _DAY,
            2,
            seed,
            1.0,
            transformer_map=spec.home_transformer,
            rho=0.8,
        )
        low_owners = {h.home_id for h in low.fleet.homes if h.battery is not None}
        high_owners = {h.home_id for h in high.fleet.homes if h.battery is not None}

        assert low_owners <= high_owners


class TestClusteringSpread:
    """As ρ increases, per-transformer penetration spreads out."""

    def test_spread_increases_with_rho(self) -> None:
        """With many homes and two transformers, higher ρ concentrates
        ownership on one transformer, increasing the variance of
        per-transformer penetration.
        """
        # We need more than 2 homes for a meaningful spread test.
        # Use _owned_indices directly to avoid needing a large pool.
        n_homes = 100
        n_transformers = 4
        penetration = 0.5
        seed = 99
        home_ids = [f"home-{i + 1}" for i in range(n_homes)]
        settings = _network_settings(n_transformers=n_transformers)
        spec = build_topology(home_ids, settings, RandomStreams(seed))

        spreads: list[float] = []
        for rho in [0.0, 0.5, 1.0]:
            streams = RandomStreams(seed)
            individual = [
                float(v) for v in streams.generator("penetration").random(n_homes)
            ]
            if rho > 0:
                scores = _clustered_scores(
                    individual, home_ids, spec.home_transformer, rho, streams
                )
            else:
                scores = individual
            owned = set(_owned_indices(scores, penetration))
            counts: dict[str, int] = {
                nid: 0 for nid in set(spec.home_transformer.values())
            }
            totals: dict[str, int] = {nid: 0 for nid in counts}
            for i, hid in enumerate(home_ids):
                tid = spec.home_transformer[hid]
                totals[tid] += 1
                if i in owned:
                    counts[tid] += 1
            per_tx = [counts[tid] / totals[tid] for tid in counts if totals[tid] > 0]
            mean_p = sum(per_tx) / len(per_tx)
            variance = sum((p - mean_p) ** 2 for p in per_tx) / len(per_tx)
            spreads.append(variance)

        # spread should be non-decreasing as ρ increases
        assert spreads[0] <= spreads[1] + 1e-9
        assert spreads[1] <= spreads[2] + 1e-9
        # ρ=1 should have strictly more spread than ρ=0
        assert spreads[2] > spreads[0]


class TestClusteredScores:
    def test_rho_zero_returns_individual_draws(self) -> None:
        individual = [0.1, 0.5, 0.9]
        home_ids = ["home-1", "home-2", "home-3"]
        tmap = {"home-1": "tx-1", "home-2": "tx-1", "home-3": "tx-2"}
        scores = _clustered_scores(individual, home_ids, tmap, 0.0, RandomStreams(0))
        assert scores == pytest.approx(individual)

    def test_rho_one_groups_by_transformer(self) -> None:
        individual = [0.1, 0.5, 0.9]
        home_ids = ["home-1", "home-2", "home-3"]
        tmap = {"home-1": "tx-1", "home-2": "tx-1", "home-3": "tx-2"}
        scores = _clustered_scores(individual, home_ids, tmap, 1.0, RandomStreams(0))
        # Homes on the same transformer get the same score
        assert scores[0] == scores[1]
        # Home on a different transformer gets a different score
        assert scores[2] != scores[0]

    def test_reproducible(self) -> None:
        individual = [0.3, 0.7]
        home_ids = ["home-1", "home-2"]
        tmap = {"home-1": "tx-1", "home-2": "tx-2"}
        a = _clustered_scores(individual, home_ids, tmap, 0.5, RandomStreams(42))
        b = _clustered_scores(individual, home_ids, tmap, 0.5, RandomStreams(42))
        assert a == b
