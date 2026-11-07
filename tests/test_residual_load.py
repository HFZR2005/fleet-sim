"""Tests for settlement periods, the NESO and Elexon loaders, and residual load.

All tests use opener injection and tmp_path — no network calls.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.data.elexon_generation import load_elexon_wind
from fleet_sim.data.neso_demand import load_neso_demand
from fleet_sim.data.residual_load import load_residual_load
from fleet_sim.data.settlement import (
    expected_periods,
    period_to_utc,
    settlement_periods_utc,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _neso_opener(calls: list[str]) -> Callable[[str], bytes]:
    """Serve the CKAN package listing, then the fixture CSV."""
    package = json.dumps(
        {"result": {"resources": [{"path": "https://example/demanddata_2023.csv"}]}}
    ).encode()
    csv_bytes = (_FIXTURES / "neso_demand_excerpt.csv").read_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        return package if "datapackage_show" in url else csv_bytes

    return opener


def _elexon_opener(calls: list[str]) -> Callable[[str], bytes]:
    """Serve the same three-period fixture for every month."""
    fixture = (_FIXTURES / "elexon_wind_excerpt.json").read_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        return fixture

    return opener


@pytest.mark.parametrize(
    ("day", "periods", "first_utc"),
    [
        # BST: local midnight is 23:00 UTC the evening before.
        (date(2023, 6, 15), 48, datetime(2023, 6, 14, 23, 0, tzinfo=UTC)),
        (date(2023, 1, 15), 48, datetime(2023, 1, 15, 0, 0, tzinfo=UTC)),
        # Spring forward (last Sunday of March) and fall back (of October).
        (date(2023, 3, 26), 46, datetime(2023, 3, 26, 0, 0, tzinfo=UTC)),
        (date(2023, 10, 29), 50, datetime(2023, 10, 28, 23, 0, tzinfo=UTC)),
    ],
)
def test_settlement_periods_cover_the_local_day(
    day: date, periods: int, first_utc: datetime
) -> None:
    stamps = settlement_periods_utc(day)
    assert len(stamps) == expected_periods(day) == periods
    assert stamps[0] == period_to_utc(day, 1) == first_utc
    assert all(b - a == timedelta(minutes=30) for a, b in itertools.pairwise(stamps))


def test_period_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="out of range"):
        period_to_utc(date(2023, 6, 15), 49)


def test_neso_demand_parses_and_caches(tmp_path: Path) -> None:
    """Interconnector flow sums IFA … GREENLINK.

    P1: 500 + 200 + 100 − 50 + 250 = 1000
    P2: 400 + 100 + 100 − 100 + 200 = 700
    P3: 300 + 0 + 100 − 150 + 150 = 400
    """
    calls: list[str] = []
    opener = _neso_opener(calls)

    rows = load_neso_demand(year=2023, cache_dir=tmp_path, opener=opener)
    assert [r.nd_mw for r in rows] == [30000.0, 29000.0, 28000.0]
    assert [r.interconnector_flow_mw for r in rows] == pytest.approx(
        [1000.0, 700.0, 400.0]
    )

    calls.clear()
    load_neso_demand(year=2023, cache_dir=tmp_path, opener=opener)
    assert calls == []


@pytest.mark.parametrize(
    "date_cell",
    # As written in the real yearly files.
    ["01-JAN-2024", "01-Jan-24", '"2024-01-01"', "01/01/2024"],
)
def test_neso_demand_reads_each_date_format(tmp_path: Path, date_cell: str) -> None:
    (tmp_path / "neso_demand_2024.csv").write_text(
        "SETTLEMENT_DATE,SETTLEMENT_PERIOD,ND,PUMP_STORAGE_PUMPING\n"
        f"{date_cell},1,21783,0\n"
    )

    [row] = load_neso_demand(year=2024, cache_dir=tmp_path)

    assert row.settlement_date == date(2024, 1, 1)


def test_elexon_wind_parses_and_caches_per_month(tmp_path: Path) -> None:
    calls: list[str] = []
    opener = _elexon_opener(calls)

    rows = load_elexon_wind(year=2023, cache_dir=tmp_path, opener=opener)
    assert len(calls) == 12
    assert {(r.settlement_period, r.generation_mw) for r in rows} == {
        (1, 5000.0),
        (2, 4800.0),
        (3, 4600.0),
    }

    calls.clear()
    load_elexon_wind(year=2023, cache_dir=tmp_path, opener=opener)
    assert calls == []


def test_residual_load_hand_worked(tmp_path: Path) -> None:
    """2023-06-15, periods 1–3.

    NESO (MW): ND = 30000, 29000, 28000; pump = 1000, 800, 600;
               ICF = 1000, 700, 400.
    Elexon wind (MW): 5000, 4800, 4600.

    Flexibility = −ICF + pump = 0, 100, 200, so F̄ = 100 MW.

    R = ND − wind + F̄:
      P1: 30000 − 5000 + 100 = 25100 MW = 25.1 GW
      P2: 29000 − 4800 + 100 = 24300 MW = 24.3 GW
      P3: 28000 − 4600 + 100 = 23500 MW = 23.5 GW
    """
    results = load_residual_load(
        start_year=2023,
        end_year=2023,
        cache_dir=tmp_path,
        opener_neso=_neso_opener([]),
        opener_elexon=_elexon_opener([]),
    )

    stamps = [ts for ts, _ in results]
    loads_gw = [load for _, load in results]
    first = datetime(2023, 6, 14, 23, 0, tzinfo=UTC)
    assert stamps == [first + timedelta(minutes=30 * i) for i in range(3)]
    assert loads_gw == pytest.approx([25.1, 24.3, 23.5])
