"""Wholesale electricity prices derived from Agile retail tariffs.

Inverts the Agile import price to recover half-hourly wholesale
electricity prices.  Capped slots (where the retail cap binds) are
excluded because the wholesale price cannot be recovered.

See ``docs/data/agile.md`` for the formula and its derivation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fleet_sim.data.agile_formula import (
    InvertedRate,
    invert_agile,
    is_peak,
    version_date_ranges,
)
from fleet_sim.data.agile_history import HistoricalRate, load_agile_rates


def load_wholesale_prices(
    *,
    start_year: int,
    end_year: int,
    regions: list[str] | None = None,
    cache_dir: Path | None = None,
) -> list[tuple[datetime, float]]:
    """Return ``(timestamp_utc, price_gbp_per_mwh)`` pairs.

    Fetches Agile retail rates from the Octopus API (cached on disk),
    inverts them to wholesale, and drops capped slots.

    When multiple *regions* are given, the first region is used (the
    wholesale price is national; multiple regions are for consistency
    checks, not for averaging).
    """
    region = (regions or ["C"])[0].upper()

    start = datetime(start_year, 1, 1, tzinfo=UTC)
    end = datetime(end_year + 1, 1, 1, tzinfo=UTC)

    inverted = invert_rates(
        region=region,
        period_from=start,
        period_to=end,
        cache_dir=cache_dir,
    )

    return [
        (r.settlement_start, r.wholesale_gbp_per_mwh) for r in inverted if not r.capped
    ]


def invert_rates(
    *,
    region: str,
    period_from: datetime,
    period_to: datetime,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[InvertedRate]:
    """Invert Agile rates to wholesale for the full date range.

    Returns all slots including capped ones (with ``capped=True``).
    """
    spans = version_date_ranges(period_from.date(), period_to.date())

    results: list[InvertedRate] = []
    for version, span_start, span_end in spans:
        span_from = datetime(
            span_start.year, span_start.month, span_start.day, tzinfo=UTC
        )
        span_to = (
            datetime(span_end.year, span_end.month, span_end.day, tzinfo=UTC) + _ONE_DAY
        )

        rates = load_agile_rates(
            product=version.product_code,
            region=region,
            period_from=max(span_from, period_from),
            period_to=min(span_to, period_to),
            cache_dir=cache_dir,
            opener=opener,
        )

        for rate in rates:
            results.append(_invert_one(rate, region, version.product_code))

    results.sort(key=lambda r: r.settlement_start)
    return results


_ONE_DAY = __import__("datetime").timedelta(days=1)


def _invert_one(
    rate: HistoricalRate,
    region: str,
    product_code: str,
) -> InvertedRate:
    from fleet_sim.data.agile_formula import best_version_for_date

    stamp = rate.valid_from.replace(tzinfo=UTC)
    version = best_version_for_date(stamp.date())
    peak = is_peak(stamp)
    wholesale_p, capped = invert_agile(
        rate.value_exc_vat, region=region, peak=peak, version=version
    )
    return InvertedRate(
        settlement_start=stamp,
        wholesale_gbp_per_mwh=wholesale_p * 10,
        capped=capped,
        product_code=product_code,
        region=region,
    )
