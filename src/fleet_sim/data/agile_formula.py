"""Agile tariff formula: forward (apply) and inverse (invert).

The Octopus Agile tariff sets half-hourly retail rates from the national
wholesale price using a regional multiplier and a peak-time adder::

    value_exc_vat = min(wholesale_p × multiplier + peak_adder, cap)
    value_inc_vat = value_exc_vat × 1.05

See ``docs/data/agile.md §Formula`` for derivation and sources.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator

from fleet_sim.models.prices import GSP_REGIONS

_LONDON = ZoneInfo("Europe/London")
_CAP_TOLERANCE_P_PER_KWH = 0.1
_VAT_MULTIPLIER = 1.05


class AgileVersion(BaseModel):
    """One Agile product version and its cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_code: str
    cap_exc_vat_p_per_kwh: float
    available_from: date
    available_to: date | None = None

    @field_validator("cap_exc_vat_p_per_kwh")
    @classmethod
    def cap_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"cap must be positive (got {value})")
        return value


class RegionParams(BaseModel):
    """Regional multiplier and peak adder for the Agile formula."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    multiplier: float
    peak_adder_p_per_kwh: float

    @field_validator("multiplier")
    @classmethod
    def multiplier_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(f"multiplier must be positive (got {value})")
        return value

    @field_validator("peak_adder_p_per_kwh")
    @classmethod
    def adder_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError(f"peak_adder must be non-negative (got {value})")
        return value


class InvertedRate(BaseModel):
    """One half-hour wholesale price recovered from an Agile retail rate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_start: datetime
    wholesale_gbp_per_mwh: float
    capped: bool
    product_code: str
    region: str


# Sorted by descending cap (highest cap = most data recovered).
AGILE_VERSIONS: list[AgileVersion] = [
    AgileVersion(
        product_code="AGILE-24-10-01",
        cap_exc_vat_p_per_kwh=95.23,
        # First rates are for 00:00 UK time on 16 September 2024.
        available_from=date(2024, 9, 16),
    ),
    AgileVersion(
        product_code="AGILE-23-12-06",
        cap_exc_vat_p_per_kwh=95.23,
        available_from=date(2023, 12, 1),
    ),
    AgileVersion(
        product_code="AGILE-22-08-31",
        cap_exc_vat_p_per_kwh=round(78 / _VAT_MULTIPLIER, 2),
        available_from=date(2022, 8, 1),
    ),
    AgileVersion(
        product_code="AGILE-22-07-22",
        cap_exc_vat_p_per_kwh=round(55 / _VAT_MULTIPLIER, 2),
        available_from=date(2022, 6, 1),
    ),
    AgileVersion(
        product_code="AGILE-18-02-21",
        cap_exc_vat_p_per_kwh=round(35 / _VAT_MULTIPLIER, 2),
        available_from=date(2018, 2, 1),
    ),
]

# Source: agilerates.co.uk, cross-verified against API data.
REGION_PARAMS: dict[str, RegionParams] = {
    "A": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=13),
    "B": RegionParams(multiplier=2.00, peak_adder_p_per_kwh=14),
    "C": RegionParams(multiplier=2.00, peak_adder_p_per_kwh=12),
    "D": RegionParams(multiplier=2.20, peak_adder_p_per_kwh=13),
    "E": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=12),
    "F": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=12),
    "G": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=12),
    "H": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=12),
    "J": RegionParams(multiplier=2.20, peak_adder_p_per_kwh=12),
    "K": RegionParams(multiplier=2.20, peak_adder_p_per_kwh=12),
    "L": RegionParams(multiplier=2.30, peak_adder_p_per_kwh=11),
    "M": RegionParams(multiplier=2.00, peak_adder_p_per_kwh=13),
    "N": RegionParams(multiplier=2.10, peak_adder_p_per_kwh=13),
    "P": RegionParams(multiplier=2.40, peak_adder_p_per_kwh=12),
}

assert set(REGION_PARAMS) == GSP_REGIONS


def is_peak(settlement_start: datetime) -> bool:
    """True when the slot falls in the 4–7 pm UK-local peak window.

    See ``docs/data/agile.md §Formula``.
    """
    uk_hour = settlement_start.astimezone(_LONDON).hour
    return 16 <= uk_hour < 19


def apply_agile(
    wholesale_p_per_kwh: float,
    *,
    region: str,
    peak: bool,
    version: AgileVersion,
) -> tuple[float, bool]:
    """Forward formula: wholesale → exc-VAT retail rate.

    Returns ``(value_exc_vat, capped)``.

    See ``docs/data/agile.md §Formula``.
    """
    params = _require_region_params(region)
    adder = params.peak_adder_p_per_kwh if peak else 0.0
    uncapped = wholesale_p_per_kwh * params.multiplier + adder
    cap = version.cap_exc_vat_p_per_kwh
    capped = uncapped >= cap
    return (min(uncapped, cap), capped)


def invert_agile(
    value_exc_vat: float,
    *,
    region: str,
    peak: bool,
    version: AgileVersion,
) -> tuple[float, bool]:
    """Inverse formula: exc-VAT retail rate → wholesale.

    Returns ``(wholesale_p_per_kwh, capped)``.  When *capped* is True the
    returned wholesale is a lower bound, not the true price.

    See ``docs/data/agile.md §Inversion``.
    """
    params = _require_region_params(region)
    cap = version.cap_exc_vat_p_per_kwh
    capped = value_exc_vat >= cap - _CAP_TOLERANCE_P_PER_KWH
    adder = params.peak_adder_p_per_kwh if peak else 0.0
    wholesale_p = (value_exc_vat - adder) / params.multiplier
    return (wholesale_p, capped)


def best_version_for_date(day: date) -> AgileVersion:
    """Return the product with the highest cap that covers *day*.

    Raises ``ValueError`` if no product covers the date.
    """
    for version in AGILE_VERSIONS:
        if day < version.available_from:
            continue
        if version.available_to is not None and day > version.available_to:
            continue
        return version
    first = AGILE_VERSIONS[-1].available_from
    raise ValueError(
        f"no Agile product covers {day.isoformat()} "
        f"(earliest available: {first.isoformat()})"
    )


def version_date_ranges(
    start: date,
    end: date,
) -> list[tuple[AgileVersion, date, date]]:
    """Partition [start, end] into (version, chunk_start, chunk_end) spans.

    Each span uses the best available product.  Spans are contiguous and
    non-overlapping.
    """
    spans: list[tuple[AgileVersion, date, date]] = []
    cursor = start
    while cursor <= end:
        version = best_version_for_date(cursor)
        chunk_end = end
        for v in AGILE_VERSIONS:
            if v is version:
                continue
            if v.available_from > cursor and v.available_from <= end:
                candidate = v.available_from - timedelta(days=1)
                if candidate < chunk_end:
                    better = best_version_for_date(v.available_from)
                    if better is not version:
                        chunk_end = candidate
        spans.append((version, cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return spans


def _require_region_params(region: str) -> RegionParams:
    code = region.upper()
    if code not in REGION_PARAMS:
        raise ValueError(
            f"unknown Agile region {region!r} (expected one of {sorted(REGION_PARAMS)})"
        )
    return REGION_PARAMS[code]
