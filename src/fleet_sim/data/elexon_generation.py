"""Loader for Elexon half-hourly generation by fuel type.

Downloads transmission-connected wind generation from the Elexon
Insights API (FUELHH dataset).  No API key is required.

Source: https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH
Licence: Creative Commons Attribution 4.0 (CC BY 4.0).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

_DEFAULT_CACHE_DIR = Path(".cache") / "prices"
_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH"


class ElexonWindRow(BaseModel):
    """One half-hour of transmission-connected wind generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_date: date
    settlement_period: int
    generation_mw: float


def load_elexon_wind(
    *,
    year: int,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[ElexonWindRow]:
    """Load half-hourly wind generation for one year, cached per month."""
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    fetch = _urlopen if opener is None else opener

    rows: list[ElexonWindRow] = []
    for month in range(1, 13):
        cache_path = directory / f"elexon_wind_{year}-{month:02d}.json"

        if cache_path.is_file():
            raw = cache_path.read_bytes()
        else:
            raw = _download_month(fetch, year, month)
            _write_cache(cache_path, raw)

        rows.extend(_parse_response(raw, year))

    rows.sort(key=lambda r: (r.settlement_date, r.settlement_period))
    return rows


def _download_month(
    fetch: Callable[[str], bytes],
    year: int,
    month: int,
) -> bytes:
    """Fetch wind generation for one calendar month."""
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)

    query = urllib.parse.urlencode(
        {
            "settlementDateFrom": first.isoformat(),
            "settlementDateTo": last.isoformat(),
            "fuelType": "WIND",
        }
    )
    url = f"{_BASE_URL}?{query}"
    return fetch(url)


def _parse_response(raw: bytes, year: int) -> list[ElexonWindRow]:
    """Parse Elexon FUELHH JSON into wind rows."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Elexon FUELHH response is not valid JSON") from exc

    data = payload.get("data")
    if not isinstance(data, list):
        raise TypeError("Elexon FUELHH response has no 'data' array")

    rows: list[ElexonWindRow] = []
    for record in data:
        try:
            sd = date.fromisoformat(record["settlementDate"])
        except (KeyError, ValueError) as exc:
            raise ValueError("Elexon FUELHH record has bad settlementDate") from exc

        if sd.year != year:
            continue

        try:
            row = ElexonWindRow(
                settlement_date=sd,
                settlement_period=record["settlementPeriod"],
                generation_mw=float(record["generation"]),
            )
        except (KeyError, ValidationError) as exc:
            raise ValueError("Elexon FUELHH record failed validation") from exc
        rows.append(row)

    return rows


def _write_cache(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _urlopen(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    if not isinstance(body, bytes):
        raise TypeError(f"Elexon response was {type(body).__name__}, expected bytes")
    return body
