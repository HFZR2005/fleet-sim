"""Tests for gas price, carbon price, and fuel cost loaders.

All tests use opener injection and tmp_path — no network calls.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fleet_sim.data.carbon_price import (
    cps_rate_for,
    load_carbon_prices,
    parse_ccm_html,
    parse_eu_ets_csv,
)
from fleet_sim.data.fuel_cost import compute_fuel_cost
from fleet_sim.data.gas_price import load_gas_prices

_FIXTURES = Path(__file__).parent / "fixtures"


def _gas_opener(calls: list[str]) -> Callable[[str], bytes]:
    """Serve the ONS landing page, then the fixture XLSX.

    The fixture has SAP 2.5, 3.0, 1.5 p/kWh for 2023-06-15..17.
    """
    landing = (
        b'<a href="/file?uri=/economy/systemaveragepriceofgas'
        b'/2023/sap.xlsx">Download</a>'
    )
    xlsx = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()

    def opener(url: str) -> bytes:
        calls.append(url)
        return landing if "datasets" in url else xlsx

    return opener


def _ccm_html(month: date, ets_price: float) -> bytes:
    """A one-row CCM table giving *ets_price* for *month*.

    The row's assessment month is the month after the monitored month.
    """
    assessment = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return (
        "<table>"
        "<tr><th>Month</th><th>ref</th><th>trigger</th>"
        "<th>monitoring</th><th>M1 avg</th><th>CCM?</th></tr>"
        f"<tr><td>{assessment:%b-%y}</td><td>ref</td><td>£0</td>"
        f"<td>{month:%b}</td><td>£{ets_price:.2f}</td><td>No</td></tr>"
        "</table>"
    ).encode()


def test_load_gas_prices_converts_to_gbp_per_mwh_and_caches(tmp_path: Path) -> None:
    """p/kWh × 10 = £/MWh: 2.5 → 25, 3.0 → 30, 1.5 → 15."""
    calls: list[str] = []
    opener = _gas_opener(calls)

    rows = load_gas_prices(
        start_year=2023, end_year=2023, cache_dir=tmp_path, opener=opener
    )
    assert [r.price_date for r in rows] == [
        date(2023, 6, 15),
        date(2023, 6, 16),
        date(2023, 6, 17),
    ]
    assert [r.sap_gbp_per_mwh for r in rows] == pytest.approx([25.0, 30.0, 15.0])
    assert len(calls) == 2  # landing page + XLSX

    calls.clear()
    later = load_gas_prices(
        start_year=2024, end_year=2024, cache_dir=tmp_path, opener=opener
    )
    assert later == []  # filtered to the requested years
    assert calls == []  # served from the cache


def test_parse_ccm_html_reads_three_and_six_month_tables() -> None:
    """Row Aug-21 monitors May–Jul 21; row Feb-23 monitors Aug-22–Jan-23."""
    prices = parse_ccm_html((_FIXTURES / "ccm_excerpt.html").read_text())
    expected = {
        date(2021, 5, 1): 49.09,
        date(2021, 6, 1): 46.08,
        date(2021, 7, 1): 44.15,
        date(2022, 8, 1): 89.05,
        date(2022, 9, 1): 79.41,
        date(2022, 10, 1): 72.96,
        date(2022, 11, 1): 70.50,
        date(2022, 12, 1): 77.58,
        date(2023, 1, 1): 69.09,
    }
    assert {month: prices[month] for month in expected} == pytest.approx(expected)


def test_parse_eu_ets_csv() -> None:
    prices = parse_eu_ets_csv((_FIXTURES / "eu_ets_monthly.csv").read_text())
    assert len(prices) == 4
    assert prices[date(2021, 1, 1)] == pytest.approx(28.50)
    assert prices[date(2021, 4, 1)] == pytest.approx(38.50)


@pytest.mark.parametrize(
    ("month", "rate"),
    [
        (date(2014, 7, 1), 9.55),
        (date(2015, 6, 1), 18.08),
        # March 2016 is still FY 2015-16; April 2016 starts the £18 cap.
        (date(2016, 3, 1), 18.08),
        (date(2016, 4, 1), 18.00),
        # January belongs to the financial year that began the April before.
        (date(2020, 1, 1), 18.00),
        # The last published rate runs to 31 March 2028.
        (date(2028, 3, 1), 18.00),
    ],
)
def test_cps_rate_follows_the_financial_year(month: date, rate: float) -> None:
    assert cps_rate_for(month) == pytest.approx(rate)


@pytest.mark.parametrize("month", [date(2010, 1, 1), date(2028, 4, 1)])
def test_cps_rate_outside_the_table_is_an_error(month: date) -> None:
    with pytest.raises(ValueError, match="no CPS rate"):
        cps_rate_for(month)


@pytest.mark.parametrize(("include_cps", "expected_cps"), [(True, 18.0), (False, 0.0)])
def test_load_carbon_prices_joins_eu_and_uk_ets(
    tmp_path: Path, include_cps: bool, expected_cps: float
) -> None:
    """EU ETS comes from the CSV in the cache, UK ETS from the CCM page."""
    shutil.copy(_FIXTURES / "eu_ets_monthly.csv", tmp_path / "eu_ets_monthly.csv")
    ccm_html = (_FIXTURES / "ccm_excerpt.html").read_bytes()

    rows = load_carbon_prices(
        start_year=2021,
        end_year=2021,
        include_carbon_price_support=include_cps,
        cache_dir=tmp_path,
        opener=lambda url: ccm_html,
    )
    by_month = {r.month_start: r for r in rows}

    assert by_month[date(2021, 1, 1)].ets_gbp_per_tco2 == pytest.approx(28.50)
    assert by_month[date(2021, 5, 1)].ets_gbp_per_tco2 == pytest.approx(49.09)
    assert all(r.cps_gbp_per_tco2 == expected_cps for r in rows)


@pytest.mark.parametrize(
    ("include_cps", "expected_k"),
    [
        # C = 40 + 18 = 58.  k = 2.0 × (25 + 0.184 × 58) = 2.0 × 35.672 = 71.344
        (True, [71.344, 81.344, 51.344]),
        # C = 40.         k = 2.0 × (25 + 0.184 × 40) = 2.0 × 32.36  = 64.72
        (False, [64.72, 74.72, 44.72]),
    ],
)
def test_fuel_cost_hand_worked(
    tmp_path: Path, include_cps: bool, expected_k: list[float]
) -> None:
    """k_t = HR × (G_t + c_gas × C_t), HR = 2.0, c_gas = 0.184, ETS = £40/tCO₂.

    G = 25, 30, 15 £/MWh on 15–17 June 2023, so days 2 and 3 differ from
    day 1 by HR × ΔG = 2.0 × (+5) = +10 and 2.0 × (−10) = −20. Each BST day
    spans 48 periods from 23:00 UTC the evening before.
    """
    results = compute_fuel_cost(
        start_year=2023,
        end_year=2023,
        heat_rate=2.0,
        gas_carbon_intensity=0.184,
        include_carbon_price_support=include_cps,
        cache_dir=tmp_path,
        gas_opener=_gas_opener([]),
        carbon_opener=lambda url: _ccm_html(date(2023, 6, 1), 40.0),
    )

    assert len(results) == 3 * 48
    assert results[0][0] == datetime(2023, 6, 14, 23, 0, tzinfo=UTC)
    assert results[47][0] == datetime(2023, 6, 15, 22, 30, tzinfo=UTC)
    daily_k = [results[day * 48][1] for day in range(3)]
    assert daily_k == pytest.approx(expected_k)
    assert {k for _, k in results[:48]} == {daily_k[0]}
