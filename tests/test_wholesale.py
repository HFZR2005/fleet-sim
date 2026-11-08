"""Tests for Agile formula inversion and wholesale price loader."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.data.agile_formula import (
    AGILE_VERSIONS,
    AgileVersion,
    EpgAdjustment,
    apply_agile,
    best_version_for_date,
    invert_agile,
    is_peak,
    version_date_ranges,
)
from fleet_sim.data.agile_history import load_agile_rates
from fleet_sim.data.wholesale import invert_rates

_VERSIONS = {v.product_code: v for v in AGILE_VERSIONS}
_V18 = _VERSIONS["AGILE-18-02-21"]
_V22 = _VERSIONS["AGILE-22-08-31"]
_V24 = _VERSIONS["AGILE-24-10-01"]
# A slot outside the Energy Price Guarantee window.
_NO_EPG = datetime(2024, 6, 15, tzinfo=UTC)


def _api_page(valid_from: list[datetime], exc: list[float]) -> bytes:
    """A single-page Octopus API response."""
    results = [
        {
            "value_exc_vat": value,
            "value_inc_vat": round(value * 1.05, 6),
            "valid_from": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valid_to": None,
        }
        for stamp, value in zip(valid_from, exc, strict=True)
    ]
    return json.dumps(
        {"count": len(results), "next": None, "results": results}
    ).encode()


@pytest.mark.parametrize(
    ("wholesale", "region", "peak", "expected_exc", "expected_capped"),
    [
        # Region C off-peak: 7 × 2.00 = 14.
        (7.0, "C", False, 14.0, False),
        # Region A off-peak: 7 × 2.10 = 14.7.
        (7.0, "A", False, 14.7, False),
        # Region C peak: 7.4 × 2.00 + 12 = 26.8.
        (7.4, "C", True, 26.8, False),
        # Region A peak: 7.4 × 2.10 + 13 = 28.54.
        (7.4, "A", True, 28.54, False),
        # Region C off-peak: min(50 × 2.00, 95.23) = 95.23, capped.
        (50.0, "C", False, 95.23, True),
    ],
)
def test_apply_agile_hand_worked(
    wholesale: float,
    region: str,
    peak: bool,
    expected_exc: float,
    expected_capped: bool,
) -> None:
    exc, capped = apply_agile(wholesale, region=region, peak=peak, version=_V24)
    assert exc == pytest.approx(expected_exc)
    assert capped is expected_capped


@pytest.mark.parametrize("version", [_V18, _V24], ids=lambda v: v.product_code)
@pytest.mark.parametrize("region", ["A", "P"])
@pytest.mark.parametrize("peak", [False, True])
def test_invert_recovers_an_uncapped_wholesale_price(
    version: AgileVersion, region: str, peak: bool
) -> None:
    """apply then invert returns the input, for the extreme region multipliers."""
    exc, _ = apply_agile(5.0, region=region, peak=peak, version=version)
    wholesale, capped = invert_agile(
        exc, region=region, peak=peak, version=version, settlement_start=_NO_EPG
    )
    assert wholesale == pytest.approx(5.0)
    assert not capped


@pytest.mark.parametrize(
    ("value_exc_vat", "version", "expected"),
    [
        (95.23, _V24, True),
        # The 35p cap is 35 / 1.05 = 33.333…, which the API rounds to 33.33.
        # 33.33 ≥ 33.33 − 0.1 tolerance → capped.
        (33.33, _V18, True),
        (30.0, _V18, False),
    ],
)
def test_invert_flags_a_rate_at_the_cap(
    value_exc_vat: float, version: AgileVersion, expected: bool
) -> None:
    _, capped = invert_agile(
        value_exc_vat,
        region="C",
        peak=False,
        version=version,
        settlement_start=_NO_EPG,
    )
    assert capped is expected


_EPG_Q4 = datetime(2022, 11, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value_exc_vat", "stamp", "expected_wholesale", "expected_capped"),
    [
        # At the 34.0926 floor inside the window: censored.
        (34.0926, _EPG_Q4, 34.0926 / 2, True),
        # Same value before the window is an ordinary rate: 34.0926 / 2.
        (34.0926, datetime(2022, 9, 15, 12, tzinfo=UTC), 34.0926 / 2, False),
        # Rounding variant of the floor.
        (34.0927, _EPG_Q4, 34.0927 / 2, True),
        # Below the floor the formula is untouched: 30 / 2 = 15.
        (30.0, _EPG_Q4, 15.0, False),
        # Above the floor, add D back: (35.0017 + 16.9983) / 2 = 52 / 2 = 26.
        (35.0017, _EPG_Q4, 26.0, False),
        # 57.2817 + 16.9983 = 74.28 ≥ 74.29 − 0.1: the 78p cap binds.
        (57.2817, _EPG_Q4, 74.28 / 2, True),
        # Q1 2023 discount is unknown, so an above-floor rate can't be recovered.
        (34.8798, datetime(2023, 2, 1, 12, tzinfo=UTC), 34.8798 / 2, True),
    ],
)
def test_invert_undoes_the_epg_adjustment_in_region_c(
    value_exc_vat: float,
    stamp: datetime,
    expected_wholesale: float,
    expected_capped: bool,
) -> None:
    """Region C off-peak, multiplier 2.00, AGILE-22-08-31 (cap 74.29)."""
    wholesale, capped = invert_agile(
        value_exc_vat, region="C", peak=False, version=_V22, settlement_start=stamp
    )
    assert wholesale == pytest.approx(expected_wholesale)
    assert capped is expected_capped


@pytest.mark.parametrize(
    ("start", "end", "discount", "message"),
    [
        (date(2023, 1, 1), date(2022, 12, 31), 1.0, "start 2023-01-01 is after end"),
        (date(2022, 10, 1), date(2022, 12, 31), 0.0, "discount must be positive"),
    ],
)
def test_epg_adjustment_rejects_invalid_values(
    start: date, end: date, discount: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        EpgAdjustment(start=start, end=end, discount_exc_vat_p_per_kwh=discount)


def test_invert_rejects_other_regions_inside_the_epg_window() -> None:
    with pytest.raises(ValueError, match="EPG adjustment for region 'A' is unknown"):
        invert_agile(
            20.0, region="A", peak=False, version=_V22, settlement_start=_EPG_Q4
        )


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        # Summer: 15:00 UTC = 16:00 BST, first peak slot.
        (datetime(2024, 6, 15, 15, 0, tzinfo=UTC), True),
        # Summer: 14:00 UTC = 15:00 BST.
        (datetime(2024, 6, 15, 14, 0, tzinfo=UTC), False),
        # Winter: 16:00 UTC = 16:00 GMT, first peak slot.
        (datetime(2024, 1, 15, 16, 0, tzinfo=UTC), True),
        # Winter: 19:00 GMT, peak has ended.
        (datetime(2024, 1, 15, 19, 0, tzinfo=UTC), False),
    ],
)
def test_peak_is_four_to_seven_uk_local(stamp: datetime, expected: bool) -> None:
    assert is_peak(stamp) is expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2020, 6, 1), "AGILE-18-02-21"),
        (date(2023, 1, 1), "AGILE-22-08-31"),
        # AGILE-24-10-01 has no rates before 16 September 2024.
        (date(2024, 9, 10), "AGILE-23-12-06"),
        (date(2024, 10, 15), "AGILE-24-10-01"),
    ],
)
def test_best_version_is_the_highest_cap_available(day: date, expected: str) -> None:
    assert best_version_for_date(day).product_code == expected


def test_no_version_before_agile_launched() -> None:
    with pytest.raises(ValueError, match="no Agile product"):
        best_version_for_date(date(2017, 1, 1))


def test_version_ranges_split_at_each_better_product() -> None:
    """22-07-22 (55p cap) starts 1 June, 22-08-31 (78p cap) starts 1 August."""
    spans = version_date_ranges(date(2022, 5, 1), date(2022, 9, 30))
    assert [(v.product_code, a, b) for v, a, b in spans] == [
        ("AGILE-18-02-21", date(2022, 5, 1), date(2022, 5, 31)),
        ("AGILE-22-07-22", date(2022, 6, 1), date(2022, 7, 31)),
        ("AGILE-22-08-31", date(2022, 8, 1), date(2022, 9, 30)),
    ]


def test_load_agile_rates_parses_and_caches(tmp_path: Path) -> None:
    start = datetime(2024, 6, 15, tzinfo=UTC)
    page = _api_page([start, start + timedelta(minutes=30)], [14.0, 13.5])
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return page

    def load() -> list[float]:
        rates = load_agile_rates(
            product="AGILE-24-10-01",
            region="C",
            period_from=start,
            period_to=start + timedelta(days=1),
            cache_dir=tmp_path,
            opener=opener,
        )
        return [r.value_exc_vat for r in rates]

    assert load() == [14.0, 13.5]
    assert load() == [14.0, 13.5]
    assert len(calls) == 1


def test_invert_rates_converts_to_gbp_per_mwh_and_flags_capped_slots(
    tmp_path: Path,
) -> None:
    """2020 uses the 35p product, region C off-peak.

    Uncapped: 10 / 2.00 = 5 p/kWh = £50/MWh. The last two slots sit at the cap.
    """
    start = datetime(2020, 6, 15, tzinfo=UTC)
    stamps = [start + timedelta(minutes=30 * i) for i in range(4)]
    cap = _V18.cap_exc_vat_p_per_kwh
    page = _api_page(stamps, [10.0, 10.0, cap, cap])

    inverted = invert_rates(
        region="C",
        period_from=start,
        period_to=start + timedelta(hours=2),
        cache_dir=tmp_path,
        opener=lambda url: page,
    )

    assert [r.capped for r in inverted] == [False, False, True, True]
    assert inverted[0].wholesale_gbp_per_mwh == pytest.approx(50.0)
    assert inverted[1].wholesale_gbp_per_mwh == pytest.approx(50.0)
