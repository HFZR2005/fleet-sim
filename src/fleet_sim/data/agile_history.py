"""Bulk historical Agile rate fetcher with on-disk caching.

Downloads half-hourly unit rates from the Octopus Energy API for a given
product, region, and date range.  Results are cached per
(product, region, year-month) chunk so re-runs skip already-fetched data.

This module handles the *raw* API data.  Inversion to wholesale prices
lives in :mod:`fleet_sim.data.agile_formula`.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

_DEFAULT_CACHE_DIR = Path(".cache") / "prices"
_PAGE_SIZE = 1500


class HistoricalRate(BaseModel):
    """One half-hour Agile rate from the Octopus API."""

    model_config = ConfigDict(extra="ignore")

    value_exc_vat: float
    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime | None = None


class _RatesPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int
    next: str | None = None
    results: list[HistoricalRate]


def load_agile_rates(
    *,
    product: str,
    region: str,
    period_from: datetime,
    period_to: datetime,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[HistoricalRate]:
    """Fetch Agile rates for one product/region over a date range.

    Rates are cached on disk per (product, region, year-month) so repeated
    calls skip the network.  Pass *opener* to inject a test double.
    """
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    fetch = _urlopen if opener is None else opener

    all_rates: list[HistoricalRate] = []
    cursor = _month_start(period_from)
    end = period_to

    while cursor < end:
        next_month = _next_month(cursor)
        chunk_end = min(next_month, end)
        chunk_key = f"{product}_{region}_{cursor.year:04d}-{cursor.month:02d}"
        cache_path = directory / f"{chunk_key}.json"

        if cache_path.is_file():
            rates = _read_cache(cache_path)
        else:
            rates = _download_range(fetch, product, region, cursor, chunk_end)
            _write_cache(cache_path, rates)

        for rate in rates:
            stamp = rate.valid_from.replace(tzinfo=UTC)
            if period_from <= stamp < period_to:
                all_rates.append(rate)

        cursor = next_month

    all_rates.sort(key=lambda r: r.valid_from)
    return all_rates


def _download_range(
    opener: Callable[[str], bytes],
    product: str,
    region: str,
    period_from: datetime,
    period_to: datetime,
) -> list[HistoricalRate]:
    tariff = f"E-1R-{product}-{region}"
    query = urllib.parse.urlencode(
        {
            "period_from": _zulu(period_from),
            "period_to": _zulu(period_to),
            "page_size": _PAGE_SIZE,
        }
    )
    url: str | None = (
        f"https://api.octopus.energy/v1/products/{product}/"
        f"electricity-tariffs/{tariff}/standard-unit-rates/?{query}"
    )
    rates: list[HistoricalRate] = []
    pages_seen: set[str] = set()

    while url is not None:
        if url in pages_seen:
            raise ValueError(f"Agile rates response repeats a page: {url}")
        if len(pages_seen) > 100:
            raise ValueError("Agile rates response has too many pages")
        pages_seen.add(url)

        body = opener(url)
        page = _parse_page(body)
        rates.extend(page.results)
        if page.next is None:
            url = None
        else:
            url = urllib.parse.urljoin(url, page.next)

    return rates


def _parse_page(body: bytes) -> _RatesPage:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Agile rates response is not JSON") from exc
    try:
        return _RatesPage.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            "Agile rates response does not match the expected schema"
        ) from exc


def _read_cache(path: Path) -> list[HistoricalRate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [HistoricalRate.model_validate(r) for r in raw]


def _write_cache(path: Path, rates: list[HistoricalRate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    data = [r.model_dump(mode="json") for r in rates]
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def _month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def _next_month(dt: datetime) -> datetime:
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, tzinfo=UTC)
    return datetime(dt.year, dt.month + 1, 1, tzinfo=UTC)


def _zulu(stamp: datetime) -> str:
    return stamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _urlopen(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    if not isinstance(body, bytes):
        raise TypeError(f"Agile response was {type(body).__name__}, expected bytes")
    return body
