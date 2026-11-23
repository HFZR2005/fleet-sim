"""Shared fixtures."""

import shutil
from pathlib import Path

import pytest

_PRICE_INPUTS = Path(__file__).parent / "fixtures" / "price_inputs_2024-06-15"


@pytest.fixture
def price_cache(tmp_path: Path) -> Path:
    """A price-curve cache holding 15 June 2024, region C, and nothing else.

    Agile rates and gas prices cover 15 and 16 June; residual load only the
    15th. Elexon wind is cached a month at a time, so the other months of
    2024 are empty files rather than downloads.
    """
    cache = tmp_path / "prices"
    shutil.copytree(_PRICE_INPUTS, cache)
    for month in range(1, 13):
        path = cache / f"elexon_wind_2024-{month:02d}.json"
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
    return cache
