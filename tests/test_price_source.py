"""Price sources. The fixture source never touches the network."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.data import AgilePriceSource, FixturePriceSource, PriceSource
from fleet_sim.data.agile import AGILE_IMPORT_PRODUCT
from fleet_sim.models import PriceSeries
from fleet_sim.models.prices import london_day_bounds_utc

DAY = date(2024, 6, 15)
FIXTURE = Path(__file__).parent / "fixtures" / "agile_import_c_2024-06-15.json"


def _series() -> PriceSeries:
    start, _end = london_day_bounds_utc(DAY)
    return PriceSeries(
        region="C",
        day=DAY,
        timestamps_utc=[start + timedelta(minutes=30) * index for index in range(48)],
        price_p_per_kwh=[float(index) for index in range(48)],
    )


def test_fixture_source_returns_its_series() -> None:
    series = _series()
    source: PriceSource = FixturePriceSource(series)

    assert source.load(DAY, "c") == series


def test_fixture_source_rejects_a_different_day() -> None:
    source = FixturePriceSource(_series())

    with pytest.raises(ValueError, match="not C on 2024-06-16"):
        source.load(date(2024, 6, 16), "C")


def test_agile_source_uses_the_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return FIXTURE.read_bytes()

    source = AgilePriceSource(cache_dir=tmp_path, opener=opener)
    first = source.load(DAY, "C")
    second = source.load(DAY, "c")

    assert second == first
    assert len(calls) == 1
    assert first.price_p_per_kwh[0] == -8.25
    assert first.timestamps_utc[0] == datetime(2024, 6, 14, 23, 0, tzinfo=UTC)
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1
    assert cached[0].name == f"{AGILE_IMPORT_PRODUCT}_C_2024-06-15.json"
