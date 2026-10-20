"""One day of Octopus Agile import prices, cached on disk.

The day is the time grid in ``docs/formulation.md``. Clock-change days are
rejected by ``london_day_bounds_utc`` before any request.
"""

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.models.prices import (
    PriceSeries,
    london_day_bounds_utc,
    require_gsp_region,
)

AGILE_IMPORT_PRODUCT = "AGILE-24-10-01"
_HALF_HOUR = timedelta(minutes=30)
_DEFAULT_CACHE_DIR = Path(".cache") / "agile"


class _UnitRate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime | None = None


class _RatesPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    next: str | None = None
    results: list[_UnitRate]


def load_agile_import_prices(
    day: date,
    region: str,
    *,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> PriceSeries:
    """Return Agile import prices for one region and one UK civil ``day``.

    The series is the time grid in ``docs/formulation.md``: 48 half-hour
    slots, timestamps in UTC, prices in p/kWh. A UK clock-change day has 46
    slots when the clocks go forward and 50 when they go back. Those dates
    raise ``ClockChangeDayError`` and are not requested.

    Prices are ``value_inc_vat`` for product ``AGILE-24-10-01`` (import tariff
    ``E-1R``). A successful result is written under ``cache_dir`` (default
    ``.cache/agile``, which is gitignored). The next call with the same day,
    region, and cache reads that file and does not call ``opener``.
    """
    region_code = require_gsp_region(region)
    start, end = london_day_bounds_utc(day)
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    path = directory / f"{AGILE_IMPORT_PRODUCT}_{region_code}_{day.isoformat()}.json"
    if path.is_file():
        return _read_cache(path, day=day, region=region_code)

    fetch = _urlopen if opener is None else opener
    rates = _download_rates(fetch, _first_page_url(region_code, start, end))
    series = _series_from_rates(region_code, day, start, end, rates)
    _write_cache(path, series)
    return series


def _urlopen(url: str) -> bytes:
    # No timeout is set by urllib, so a stalled connection would wait forever.
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    if not isinstance(body, bytes):
        raise TypeError(f"Agile response was {type(body).__name__}, expected bytes")
    return body


def _first_page_url(region: str, start: datetime, end: datetime) -> str:
    tariff = f"E-1R-{AGILE_IMPORT_PRODUCT}-{region}"
    query = urllib.parse.urlencode(
        {"period_from": _zulu(start), "period_to": _zulu(end)}
    )
    return (
        "https://api.octopus.energy/v1/products/"
        f"{AGILE_IMPORT_PRODUCT}/electricity-tariffs/{tariff}/"
        f"standard-unit-rates/?{query}"
    )


def _zulu(stamp: datetime) -> str:
    return stamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _download_rates(opener: Callable[[str], bytes], url: str) -> list[_UnitRate]:
    seen: set[str] = set()
    rates: list[_UnitRate] = []
    page_url: str | None = url
    while page_url is not None:
        if page_url in seen:
            raise ValueError(f"Agile rates response repeats a page: {page_url}")
        if len(seen) >= SLOTS_PER_DAY:
            raise ValueError("Agile rates response has too many pages")
        seen.add(page_url)
        page = _read_page(opener(page_url))
        rates.extend(page.results)
        if page.next is None:
            page_url = None
        else:
            page_url = urllib.parse.urljoin(page_url, page.next)
    return rates


def _read_page(body: bytes) -> _RatesPage:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Agile rates response is not JSON") from exc
    try:
        return _RatesPage.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            "Agile rates response does not match the unit-rate page"
        ) from exc


def _series_from_rates(
    region: str,
    day: date,
    start: datetime,
    end: datetime,
    rates: list[_UnitRate],
) -> PriceSeries:
    expected = [start + _HALF_HOUR * index for index in range(SLOTS_PER_DAY)]
    expected_set = set(expected)
    found: dict[datetime, float] = {}
    for rate in rates:
        stamp = _as_utc(rate.valid_from)
        if stamp < start or stamp >= end:
            continue
        if stamp not in expected_set:
            raise ValueError(
                f"Agile rate at {stamp.isoformat()} is not a half-hour boundary"
            )
        if rate.valid_to is not None:
            valid_to = _as_utc(rate.valid_to)
            if valid_to - stamp != _HALF_HOUR:
                raise ValueError(
                    f"Agile rate at {stamp.isoformat()} does not last 30 minutes "
                    f"(valid_to is {valid_to.isoformat()})"
                )
        if stamp in found:
            raise ValueError(f"duplicate Agile rate at {stamp.isoformat()}")
        found[stamp] = rate.value_inc_vat

    missing = [stamp for stamp in expected if stamp not in found]
    if missing:
        raise ValueError(
            f"Agile rates for {day.isoformat()} region {region} are missing "
            f"{len(missing)} half-hour slots, starting at {missing[0].isoformat()}"
        )
    return PriceSeries(
        region=region,
        day=day,
        timestamps_utc=expected,
        price_p_per_kwh=[found[stamp] for stamp in expected],
    )


def _as_utc(stamp: datetime) -> datetime:
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(
            f"Agile rate timestamp must be timezone-aware (got {stamp.isoformat()})"
        )
    return stamp.astimezone(UTC)


def _read_cache(path: Path, *, day: date, region: str) -> PriceSeries:
    try:
        series = PriceSeries.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(
            f"cached Agile prices at {path} are not a PriceSeries"
        ) from exc
    if series.day != day or series.region != region:
        raise ValueError(
            f"cached Agile prices at {path} are for region {series.region} on "
            f"{series.day.isoformat()}, not region {region} on {day.isoformat()}"
        )
    return series


def _write_cache(path: Path, series: PriceSeries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(series.model_dump_json(), encoding="utf-8")
    temporary.replace(path)
