"""Tests for settlement period utilities, NESO demand loader,
Elexon wind loader, and the residual-load orchestrator.

All tests use opener injection and tmp_path — no network calls.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fleet_sim.data.elexon_generation import ElexonWindRow, load_elexon_wind
from fleet_sim.data.neso_demand import NesoDemandRow, load_neso_demand
from fleet_sim.data.residual_load import load_residual_load
from fleet_sim.data.settlement import (
    expected_periods,
    period_to_utc,
    settlement_periods_utc,
)

_FIXTURES = Path(__file__).parent / "fixtures"


# ── Settlement period utilities ──────────────────────────────────────


class TestSettlementPeriods:
    def test_normal_day_has_48_periods(self) -> None:
        stamps = settlement_periods_utc(date(2023, 6, 15))
        assert len(stamps) == 48

    def test_spring_forward_has_46_periods(self) -> None:
        # Last Sunday of March 2023 = 26 March
        stamps = settlement_periods_utc(date(2023, 3, 26))
        assert len(stamps) == 46
        assert expected_periods(date(2023, 3, 26)) == 46

    def test_fall_back_has_50_periods(self) -> None:
        # Last Sunday of October 2023 = 29 October
        stamps = settlement_periods_utc(date(2023, 10, 29))
        assert len(stamps) == 50
        assert expected_periods(date(2023, 10, 29)) == 50

    def test_period_1_is_midnight_local(self) -> None:
        # 2023-06-15 is BST (UTC+1), so midnight BST = 23:00 UTC on 14th
        utc = period_to_utc(date(2023, 6, 15), 1)
        assert utc == datetime(2023, 6, 14, 23, 0, tzinfo=UTC)

    def test_period_1_winter_is_midnight_utc(self) -> None:
        # 2023-01-15 is GMT, so midnight GMT = 00:00 UTC
        utc = period_to_utc(date(2023, 1, 15), 1)
        assert utc == datetime(2023, 1, 15, 0, 0, tzinfo=UTC)

    def test_period_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            period_to_utc(date(2023, 6, 15), 49)

    def test_all_stamps_are_utc(self) -> None:
        for stamp in settlement_periods_utc(date(2023, 6, 15)):
            assert stamp.tzinfo == UTC

    def test_stamps_are_30_min_apart(self) -> None:
        stamps = settlement_periods_utc(date(2023, 6, 15))
        for a, b in itertools.pairwise(stamps):
            assert (b - a).total_seconds() == 1800


# ── NESO demand loader ───────────────────────────────────────────────


def _neso_fixture_bytes() -> bytes:
    return (_FIXTURES / "neso_demand_excerpt.csv").read_bytes()


def _neso_opener(calls: list[str]) -> object:
    """Return an opener that serves the fixture CSV on the first URL
    and the CKAN package listing on the package URL.
    """
    package_response = json.dumps(
        {
            "result": {
                "resources": [
                    {
                        "path": "https://api.neso.energy/dataset/fake/demanddata_2023.csv",
                    },
                ],
            },
        }
    ).encode()
    csv_bytes = _neso_fixture_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        if "datapackage_show" in url:
            return package_response
        return csv_bytes

    return opener


class TestNesoDemandLoader:
    def test_parses_fixture(self, tmp_path: Path) -> None:
        calls: list[str] = []
        rows = load_neso_demand(
            year=2023,
            cache_dir=tmp_path,
            opener=_neso_opener(calls),  # type: ignore[arg-type]
        )
        assert len(rows) == 3
        assert all(isinstance(r, NesoDemandRow) for r in rows)

    def test_nd_values(self, tmp_path: Path) -> None:
        calls: list[str] = []
        rows = load_neso_demand(
            year=2023,
            cache_dir=tmp_path,
            opener=_neso_opener(calls),  # type: ignore[arg-type]
        )
        assert rows[0].nd_mw == 30000.0
        assert rows[1].nd_mw == 29000.0
        assert rows[2].nd_mw == 28000.0

    def test_interconnector_sum(self, tmp_path: Path) -> None:
        """IFA + IFA2 + BRITNED + MOYLE + EW + NEMO + NSL + ELECLINK + VIKING + GREENLINK.
        Period 1: 500+200+100+(-50)+0+0+250+0+0+0+0 = 1000
        Period 2: 400+100+100+(-100)+0+0+200+0+0+0+0 = 700
        Period 3: 300+0+100+(-150)+0+0+150+0+0+0+0 = 400
        """
        calls: list[str] = []
        rows = load_neso_demand(
            year=2023,
            cache_dir=tmp_path,
            opener=_neso_opener(calls),  # type: ignore[arg-type]
        )
        assert rows[0].interconnector_flow_mw == pytest.approx(1000.0)
        assert rows[1].interconnector_flow_mw == pytest.approx(700.0)
        assert rows[2].interconnector_flow_mw == pytest.approx(400.0)

    def test_caching(self, tmp_path: Path) -> None:
        calls: list[str] = []
        opener = _neso_opener(calls)
        load_neso_demand(year=2023, cache_dir=tmp_path, opener=opener)  # type: ignore[arg-type]
        first_call_count = len(calls)
        assert first_call_count > 0

        calls.clear()
        load_neso_demand(year=2023, cache_dir=tmp_path, opener=opener)  # type: ignore[arg-type]
        assert len(calls) == 0, "second call should use cache, not network"


# ── Elexon wind loader ───────────────────────────────────────────────


def _elexon_fixture_bytes() -> bytes:
    return (_FIXTURES / "elexon_wind_excerpt.json").read_bytes()


def _elexon_opener(calls: list[str]) -> object:
    fixture = _elexon_fixture_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        return fixture

    return opener


class TestElexonWindLoader:
    def test_parses_fixture(self, tmp_path: Path) -> None:
        calls: list[str] = []
        rows = load_elexon_wind(
            year=2023,
            cache_dir=tmp_path,
            opener=_elexon_opener(calls),  # type: ignore[arg-type]
        )
        # The fixture has 3 records, but loaded for all 12 months each
        # returning the same fixture. Only period/date matching 2023 pass.
        assert len(rows) > 0
        assert all(isinstance(r, ElexonWindRow) for r in rows)
        assert rows[0].generation_mw == 5000.0

    def test_caching(self, tmp_path: Path) -> None:
        calls: list[str] = []
        opener = _elexon_opener(calls)
        load_elexon_wind(year=2023, cache_dir=tmp_path, opener=opener)  # type: ignore[arg-type]
        first_call_count = len(calls)
        assert first_call_count == 12  # one per month

        calls.clear()
        load_elexon_wind(year=2023, cache_dir=tmp_path, opener=opener)  # type: ignore[arg-type]
        assert len(calls) == 0, "second call should use cache"


# ── Residual load end-to-end ─────────────────────────────────────────


def _combined_opener_neso(calls: list[str]) -> object:
    """NESO opener that serves both the CKAN listing and the fixture CSV."""
    package_response = json.dumps(
        {
            "result": {
                "resources": [
                    {
                        "path": "https://api.neso.energy/dataset/fake/demanddata_2023.csv",
                    },
                ],
            },
        }
    ).encode()
    csv_bytes = _neso_fixture_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        if "datapackage_show" in url:
            return package_response
        return csv_bytes

    return opener


def _combined_opener_elexon(calls: list[str]) -> object:
    fixture = _elexon_fixture_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        return fixture

    return opener


class TestResidualLoad:
    def test_hand_computed_residual_load(self, tmp_path: Path) -> None:
        """Hand computation for 2023-06-15, periods 1–3.

        NESO data (MW):
          P1: ND=30000, pump=1000, ICF=1000
          P2: ND=29000, pump=800,  ICF=700
          P3: ND=28000, pump=600,  ICF=400

        Elexon wind (MW):
          P1: 5000, P2: 4800, P3: 4600

        Flexibility = -ICF + pump:
          P1: -1000+1000 = 0
          P2: -700+800   = 100
          P3: -400+600   = 200

        F̄ = mean(0, 100, 200) = 100.0 MW

        R = ND - wind_tx + F̄  (MW):
          P1: 30000 - 5000 + 100 = 25100 → 25.1 GW
          P2: 29000 - 4800 + 100 = 24300 → 24.3 GW
          P3: 28000 - 4600 + 100 = 23500 → 23.5 GW
        """
        neso_calls: list[str] = []
        elexon_calls: list[str] = []
        results = load_residual_load(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener_neso=_combined_opener_neso(neso_calls),  # type: ignore[arg-type]
            opener_elexon=_combined_opener_elexon(elexon_calls),  # type: ignore[arg-type]
        )

        # Should produce 3 results for the 3 overlapping periods
        assert len(results) == 3

        _timestamps, loads_gw = zip(*results)

        assert loads_gw[0] == pytest.approx(25.1)
        assert loads_gw[1] == pytest.approx(24.3)
        assert loads_gw[2] == pytest.approx(23.5)

    def test_output_is_in_gw(self, tmp_path: Path) -> None:
        neso_calls: list[str] = []
        elexon_calls: list[str] = []
        results = load_residual_load(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener_neso=_combined_opener_neso(neso_calls),  # type: ignore[arg-type]
            opener_elexon=_combined_opener_elexon(elexon_calls),  # type: ignore[arg-type]
        )
        for _, load_gw in results:
            assert 0 < load_gw < 100, "residual load should be in GW, not MW"

    def test_timestamps_are_utc(self, tmp_path: Path) -> None:
        neso_calls: list[str] = []
        elexon_calls: list[str] = []
        results = load_residual_load(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener_neso=_combined_opener_neso(neso_calls),  # type: ignore[arg-type]
            opener_elexon=_combined_opener_elexon(elexon_calls),  # type: ignore[arg-type]
        )
        for ts, _ in results:
            assert ts.tzinfo == UTC

    def test_results_sorted_by_timestamp(self, tmp_path: Path) -> None:
        neso_calls: list[str] = []
        elexon_calls: list[str] = []
        results = load_residual_load(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener_neso=_combined_opener_neso(neso_calls),  # type: ignore[arg-type]
            opener_elexon=_combined_opener_elexon(elexon_calls),  # type: ignore[arg-type]
        )
        timestamps = [ts for ts, _ in results]
        assert timestamps == sorted(timestamps)
