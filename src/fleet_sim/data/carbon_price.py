"""Loader for GB carbon prices faced by electricity generators.

Combines:
- UK ETS monthly average settlement prices (May 2021 onwards),
  scraped from the gov.uk CCM trigger-price table.
- EU ETS monthly average settlement prices (before May 2021),
  loaded from a user-provided CSV in the cache directory.
- Carbon Price Support (CPS) rate, an annual levy set by HMRC,
  embedded as a lookup table.

See ``docs/data/fuel-cost.md`` for sources, licences, and units.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_DEFAULT_CACHE_DIR = Path(".cache") / "prices"

_CCM_URL = (
    "https://www.gov.uk/government/publications"
    "/taking-part-in-the-uk-emissions-trading-scheme-markets"
    "/cost-containment-mechanism-ccm-trigger-prices"
    "-and-average-monthly-prices-full-table"
)

_MONTH_ABBR: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Carbon Price Support rate in £/tCO₂, by financial year start.
# Source: HMRC, Climate Change Levy rates and allowances.
# https://www.gov.uk/government/publications/rates-and-allowances-climate-change-levy
#
# The CPS rate is the £/tCO₂ levy on fossil fuels used in electricity
# generation.  It has been frozen at £18.08/tCO₂ since April 2015.
_CPS_RATES_GBP_PER_TCO2: dict[int, float] = {
    2013: 4.94,
    2014: 9.55,
    2015: 18.08,
    2016: 18.08,
    2017: 18.08,
    2018: 18.08,
    2019: 18.08,
    2020: 18.08,
    2021: 18.08,
    2022: 18.08,
    2023: 18.08,
    2024: 18.08,
    2025: 18.08,
    2026: 18.08,
    2027: 18.08,
}


class CarbonPriceRow(BaseModel):
    """Monthly carbon price faced by GB generators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    month_start: date
    ets_gbp_per_tco2: float
    cps_gbp_per_tco2: float


def load_carbon_prices(
    *,
    start_year: int,
    end_year: int,
    include_carbon_price_support: bool,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[CarbonPriceRow]:
    """Load monthly carbon prices for *start_year* through *end_year*.

    UK ETS data (May 2021 onwards) is downloaded from gov.uk.
    EU ETS data (before May 2021) is read from a CSV file at
    ``<cache_dir>/eu_ets_monthly.csv`` with columns
    ``month`` (YYYY-MM) and ``price_gbp_per_tco2``.

    When *include_carbon_price_support* is ``True``, the CPS rate
    for each month is looked up and included; otherwise it is zero.
    """
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    fetch = _urlopen if opener is None else opener

    ets_prices: dict[date, float] = {}

    eu_rows = _load_eu_ets(directory)
    ets_prices.update(eu_rows)

    uk_rows = _load_uk_ets(directory, fetch)
    ets_prices.update(uk_rows)

    start = date(start_year, 1, 1)
    end = date(end_year, 12, 1)

    results: list[CarbonPriceRow] = []
    for month_start, ets_price in sorted(ets_prices.items()):
        if month_start < start or month_start > end:
            continue
        cps = cps_rate_for(month_start) if include_carbon_price_support else 0.0
        results.append(
            CarbonPriceRow(
                month_start=month_start,
                ets_gbp_per_tco2=ets_price,
                cps_gbp_per_tco2=cps,
            )
        )

    if not results:
        raise ValueError(
            f"no carbon price data for {start_year}–{end_year}; "
            f"check that eu_ets_monthly.csv is present in {directory} "
            f"for dates before May 2021"
        )

    return results


def cps_rate_for(month_start: date) -> float:
    """Look up the Carbon Price Support rate for a given month.

    The CPS rate changes on 1 April each year (the UK financial year).
    """
    fy_start = month_start.year if month_start.month >= 4 else month_start.year - 1

    rate = _CPS_RATES_GBP_PER_TCO2.get(fy_start)
    if rate is None:
        known_years = sorted(_CPS_RATES_GBP_PER_TCO2.keys())
        raise ValueError(
            f"no CPS rate for financial year starting {fy_start}; "
            f"known years: {known_years[0]}–{known_years[-1]}"
        )
    return rate


# ── UK ETS from gov.uk CCM table ────────────────────────────────────


def _load_uk_ets(
    cache_dir: Path,
    fetch: Callable[[str], bytes],
) -> dict[date, float]:
    """Download and parse UK ETS monthly averages from gov.uk."""
    cache_path = cache_dir / "uk_ets_monthly.html"

    if cache_path.is_file():
        html = cache_path.read_text(encoding="utf-8")
    else:
        raw = fetch(_CCM_URL)
        html = raw.decode("utf-8", errors="replace")
        _write_cache_text(cache_path, html)

    return parse_ccm_html(html)


def parse_ccm_html(html: str) -> dict[date, float]:
    """Extract monthly average UKA prices from the CCM table HTML.

    Each row has a label like ``Aug-21``, a monitoring period of
    N consecutive months ending just before the label month, and
    N price columns giving the monthly average for each monitoring
    month.  Prices marked ``[x]`` or ``TBD`` are skipped.

    Returns ``{date(year, month, 1): price}`` for each month with
    a valid price.  Later rows overwrite earlier ones for the same
    month, which is harmless as the prices agree.
    """
    prices: dict[date, float] = {}

    rows = re.findall(
        r"<tr[^>]*>(.*?)</tr>",
        html,
        re.DOTALL | re.IGNORECASE,
    )

    for row_html in rows:
        cells = re.findall(
            r"<t[dh][^>]*>(.*?)</t[dh]>",
            row_html,
            re.DOTALL | re.IGNORECASE,
        )
        if len(cells) < 5:
            continue

        label = _strip_tags(cells[0])
        assessment = _parse_month_year(label)
        if assessment is None:
            continue

        # cells[4:-1]: skip the first 4 metadata columns and the last
        # column ("CCM triggered?") to get only the price columns.
        price_cells = cells[4:-1] if len(cells) > 5 else cells[4:]
        price_values: list[float | None] = []
        for cell in price_cells:
            text = _strip_tags(cell).replace("£", "").replace(",", "").strip()
            if not text or text.lower() in ("tbd", "[x]", "n/a", ""):
                price_values.append(None)
            else:
                try:
                    price_values.append(float(text))
                except ValueError:
                    price_values.append(None)

        n_prices = len(price_values)
        if n_prices == 0:
            continue

        monitoring_months = _months_before(assessment, n_prices)

        for month_date, price in zip(monitoring_months, price_values):
            if price is not None:
                prices[month_date] = price

    return prices


def _parse_month_year(text: str) -> date | None:
    """Parse ``'Aug-21'`` → ``date(2021, 8, 1)``."""
    match = re.match(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\W*(\d{2})\b",
        text.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    month = _MONTH_ABBR[match.group(1)[:3].lower()]
    year = 2000 + int(match.group(2))
    return date(year, month, 1)


def _months_before(assessment: date, count: int) -> list[date]:
    """Return *count* consecutive month-start dates ending just before *assessment*.

    For ``assessment=date(2021, 8, 1)`` and ``count=3``,
    returns ``[date(2021, 5, 1), date(2021, 6, 1), date(2021, 7, 1)]``.
    """
    result: list[date] = []
    y, m = assessment.year, assessment.month
    for _ in range(count):
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    for _ in range(count):
        result.append(date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


# ── EU ETS from user CSV ────────────────────────────────────────────


def _load_eu_ets(cache_dir: Path) -> dict[date, float]:
    """Load EU ETS monthly prices from a user-provided CSV.

    Expected format: columns ``month`` (YYYY-MM) and
    ``price_gbp_per_tco2``.  If the file is absent, returns empty.
    """
    csv_path = cache_dir / "eu_ets_monthly.csv"
    if not csv_path.is_file():
        return {}

    return parse_eu_ets_csv(csv_path.read_text(encoding="utf-8"))


def parse_eu_ets_csv(text: str) -> dict[date, float]:
    """Parse EU ETS CSV text into ``{month_start: price}``."""
    reader = csv.DictReader(io.StringIO(text))
    prices: dict[date, float] = {}
    for record in reader:
        month_str = record.get("month", "").strip()
        price_str = record.get("price_gbp_per_tco2", "").strip()
        if not month_str or not price_str:
            continue
        parts = month_str.split("-")
        month_date = date(int(parts[0]), int(parts[1]), 1)
        prices[month_date] = float(price_str)
    return prices


# ── Utilities ────────────────────────────────────────────────────────


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def _write_cache_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _urlopen(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read()
    if not isinstance(body, bytes):
        raise TypeError(f"response was {type(body).__name__}, expected bytes")
    return body
