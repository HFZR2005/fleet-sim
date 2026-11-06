"""Tests for gas price, carbon price, and fuel cost loaders.

All tests use opener injection and tmp_path — no network calls.
"""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fleet_sim.data.carbon_price import (
    CarbonPriceRow,
    cps_rate_for,
    load_carbon_prices,
    parse_ccm_html,
    parse_eu_ets_csv,
)
from fleet_sim.data.fuel_cost import compute_fuel_cost
from fleet_sim.data.gas_price import (
    GasPriceRow,
    _excel_serial_to_date,
    _parse_sap_xlsx,
    load_gas_prices,
)

_FIXTURES = Path(__file__).parent / "fixtures"


# ── Unit conversions ────────────────────────────────────────────────


class TestUnitConversions:
    def test_excel_serial_to_date(self) -> None:
        assert _excel_serial_to_date(43101) == date(2018, 1, 1)
        assert _excel_serial_to_date(45092) == date(2023, 6, 15)


# ── Gas price XLSX parser ──────────────────────────────────────────


class TestGasPriceXlsxParser:
    def test_parses_fixture(self) -> None:
        """The fixture XLSX has 3 rows for 2023-06-15..17, p/kWh = 2.5, 3.0, 1.5."""
        raw = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        rows = _parse_sap_xlsx(raw)
        assert len(rows) == 3
        assert all(isinstance(r, GasPriceRow) for r in rows)

    def test_conversion_p_kwh_to_gbp_mwh(self) -> None:
        """2.5 p/kWh × 10 = 25.0 £/MWh."""
        raw = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        rows = _parse_sap_xlsx(raw)
        assert rows[0].sap_gbp_per_mwh == pytest.approx(25.0)
        assert rows[1].sap_gbp_per_mwh == pytest.approx(30.0)
        assert rows[2].sap_gbp_per_mwh == pytest.approx(15.0)

    def test_dates_are_correct(self) -> None:
        raw = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        rows = _parse_sap_xlsx(raw)
        assert rows[0].price_date == date(2023, 6, 15)
        assert rows[1].price_date == date(2023, 6, 16)
        assert rows[2].price_date == date(2023, 6, 17)

    def test_rows_sorted_by_date(self) -> None:
        raw = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        rows = _parse_sap_xlsx(raw)
        dates = [r.price_date for r in rows]
        assert dates == sorted(dates)


class TestGasPriceLoader:
    def test_loads_with_opener(self, tmp_path: Path) -> None:
        """load_gas_prices with opener injection skips network."""
        xlsx_bytes = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        landing_html = (
            b'<a href="/file?uri=/economy/systemaveragepriceofgas'
            b'/2023/sap.xlsx">Download</a>'
        )
        calls: list[str] = []

        def opener(url: str) -> bytes:
            calls.append(url)
            if "datasets" in url:
                return landing_html
            return xlsx_bytes

        rows = load_gas_prices(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener=opener,
        )
        assert len(rows) == 3
        assert len(calls) == 2  # landing page + xlsx

    def test_caching(self, tmp_path: Path) -> None:
        xlsx_bytes = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        landing_html = (
            b'<a href="/file?uri=/economy/systemaveragepriceofgas'
            b'/2023/sap.xlsx">Download</a>'
        )
        calls: list[str] = []

        def opener(url: str) -> bytes:
            calls.append(url)
            if "datasets" in url:
                return landing_html
            return xlsx_bytes

        load_gas_prices(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener=opener,
        )
        first_count = len(calls)
        assert first_count > 0

        calls.clear()
        load_gas_prices(
            start_year=2023,
            end_year=2023,
            cache_dir=tmp_path,
            opener=opener,
        )
        assert len(calls) == 0, "second call should use cache"

    def test_year_filter(self, tmp_path: Path) -> None:
        xlsx_bytes = (_FIXTURES / "ons_gas_sap_excerpt.xlsx").read_bytes()
        landing_html = (
            b'<a href="/file?uri=/economy/systemaveragepriceofgas'
            b'/2023/sap.xlsx">Download</a>'
        )

        def opener(url: str) -> bytes:
            if "datasets" in url:
                return landing_html
            return xlsx_bytes

        rows = load_gas_prices(
            start_year=2024,
            end_year=2024,
            cache_dir=tmp_path,
            opener=opener,
        )
        assert len(rows) == 0, "fixture has only 2023 data"


# ── Carbon price: CCM HTML parser ──────────────────────────────────


class TestCcmParser:
    def test_parses_3month_table(self) -> None:
        """Row Aug-21: monitoring May, Jun, Jul → prices 49.09, 46.08, 44.15."""
        html = (_FIXTURES / "ccm_excerpt.html").read_text()
        prices = parse_ccm_html(html)

        assert prices[date(2021, 5, 1)] == pytest.approx(49.09)
        assert prices[date(2021, 6, 1)] == pytest.approx(46.08)
        assert prices[date(2021, 7, 1)] == pytest.approx(44.15)

    def test_parses_6month_table(self) -> None:
        """Row Feb-23: monitoring Aug-22..Jan-23."""
        html = (_FIXTURES / "ccm_excerpt.html").read_text()
        prices = parse_ccm_html(html)

        assert prices[date(2022, 8, 1)] == pytest.approx(89.05)
        assert prices[date(2022, 9, 1)] == pytest.approx(79.41)
        assert prices[date(2022, 10, 1)] == pytest.approx(72.96)
        assert prices[date(2022, 11, 1)] == pytest.approx(70.50)
        assert prices[date(2022, 12, 1)] == pytest.approx(77.58)
        assert prices[date(2023, 1, 1)] == pytest.approx(69.09)

    def test_overlapping_rows_agree(self) -> None:
        """Sep-21 and Jan-23 both have Oct-22 = 72.96; later wins, same value."""
        html = (_FIXTURES / "ccm_excerpt.html").read_text()
        prices = parse_ccm_html(html)
        assert prices[date(2022, 10, 1)] == pytest.approx(72.96)


# ── Carbon price: EU ETS CSV parser ────────────────────────────────


class TestEuEtsCsv:
    def test_parses_csv(self) -> None:
        text = (_FIXTURES / "eu_ets_monthly.csv").read_text()
        prices = parse_eu_ets_csv(text)
        assert prices[date(2021, 1, 1)] == pytest.approx(28.50)
        assert prices[date(2021, 4, 1)] == pytest.approx(38.50)
        assert len(prices) == 4


# ── Carbon Price Support ───────────────────────────────────────────


class TestCarbonPriceSupport:
    def test_cps_rate_fy_2019(self) -> None:
        """April 2019 → FY starting 2019 → £18."""
        assert cps_rate_for(date(2019, 4, 1)) == pytest.approx(18.00)

    def test_cps_rate_jan_2020(self) -> None:
        """January 2020 → FY starting 2019 (Jan is before April) → £18."""
        assert cps_rate_for(date(2020, 1, 1)) == pytest.approx(18.00)

    def test_cps_rate_fy_2015(self) -> None:
        """FY 2015-16 → £18.08, the last rate before the £18 cap."""
        assert cps_rate_for(date(2015, 6, 1)) == pytest.approx(18.08)

    def test_cps_rate_fy_2016_first_capped_year(self) -> None:
        """March 2016 is still FY 2015-16; April 2016 starts the £18 cap."""
        assert cps_rate_for(date(2016, 3, 1)) == pytest.approx(18.08)
        assert cps_rate_for(date(2016, 4, 1)) == pytest.approx(18.00)

    def test_cps_rate_fy_2027_last_published(self) -> None:
        """HMRC's published rate runs to 31 March 2028; nothing after."""
        assert cps_rate_for(date(2028, 3, 1)) == pytest.approx(18.00)
        with pytest.raises(ValueError, match="no CPS rate"):
            cps_rate_for(date(2028, 4, 1))

    def test_cps_rate_fy_2014(self) -> None:
        """FY 2014-15 → £9.55."""
        assert cps_rate_for(date(2014, 7, 1)) == pytest.approx(9.55)

    def test_unknown_fy_raises(self) -> None:
        with pytest.raises(ValueError, match="no CPS rate"):
            cps_rate_for(date(2010, 1, 1))


# ── Carbon price loader integration ───────────────────────────────


class TestCarbonPriceLoader:
    def test_loads_uk_and_eu_ets(self, tmp_path: Path) -> None:
        """Loads EU ETS from CSV and UK ETS from HTML in the same call."""
        shutil.copy(_FIXTURES / "eu_ets_monthly.csv", tmp_path / "eu_ets_monthly.csv")
        ccm_html = (_FIXTURES / "ccm_excerpt.html").read_bytes()

        def opener(url: str) -> bytes:
            return ccm_html

        rows = load_carbon_prices(
            start_year=2021,
            end_year=2023,
            include_carbon_price_support=True,
            cache_dir=tmp_path,
            opener=opener,
        )
        assert len(rows) > 0
        assert all(isinstance(r, CarbonPriceRow) for r in rows)

        jan_21 = next(r for r in rows if r.month_start == date(2021, 1, 1))
        assert jan_21.ets_gbp_per_tco2 == pytest.approx(28.50)
        assert jan_21.cps_gbp_per_tco2 == pytest.approx(18.00)

    def test_cps_excluded_when_flag_false(self, tmp_path: Path) -> None:
        shutil.copy(_FIXTURES / "eu_ets_monthly.csv", tmp_path / "eu_ets_monthly.csv")
        ccm_html = (_FIXTURES / "ccm_excerpt.html").read_bytes()

        def opener(url: str) -> bytes:
            return ccm_html

        rows = load_carbon_prices(
            start_year=2021,
            end_year=2021,
            include_carbon_price_support=False,
            cache_dir=tmp_path,
            opener=opener,
        )
        for row in rows:
            assert row.cps_gbp_per_tco2 == 0.0


# ── Fuel cost formula ──────────────────────────────────────────────


class TestFuelCostFormula:
    def test_hand_worked_example(self, tmp_path: Path) -> None:
        """Hand computation from issue #67.

        Gas price G = £25/MWh, ETS = £40/tCO₂, CPS = £18/tCO₂ (FY 2023-24),
        HR = 2.0 (MWh gas / MWh elec), c_gas = 0.184 (tCO₂ / MWh gas).

        C_t = 40 + 18 = 58
        k_t = HR × (G_t + c_gas × C_t)
             = 2.0 × (25 + 0.184 × 58)
             = 2.0 × (25 + 10.672)
             = 2.0 × 35.672
             = £71.344/MWh
        """
        _write_gas_fixture(tmp_path, date(2023, 6, 15), sap_p_kwh=2.5)

        _write_carbon_fixtures(
            tmp_path,
            month=date(2023, 6, 1),
            ets_price=40.0,
        )

        gas_xlsx = (tmp_path / "ons_gas_sap.xlsx").read_bytes()
        ccm_html = (tmp_path / "uk_ets_monthly.html").read_bytes()

        def gas_opener(url: str) -> bytes:
            if "datasets" in url:
                return _landing_html()
            return gas_xlsx

        def carbon_opener(url: str) -> bytes:
            return ccm_html

        results = compute_fuel_cost(
            start_year=2023,
            end_year=2023,
            heat_rate=2.0,
            gas_carbon_intensity=0.184,
            include_carbon_price_support=True,
            cache_dir=tmp_path,
            gas_opener=gas_opener,
            carbon_opener=carbon_opener,
        )

        assert len(results) == 48
        for _, k_t in results:
            assert k_t == pytest.approx(71.344, abs=0.001)

    def test_cps_excluded(self, tmp_path: Path) -> None:
        """Without CPS, C_t = ETS only.

        k_t = 2.0 × (25 + 0.184 × 40)
             = 2.0 × (25 + 7.36)
             = 2.0 × 32.36
             = £64.72/MWh
        """
        _write_gas_fixture(tmp_path, date(2023, 6, 15), sap_p_kwh=2.5)
        _write_carbon_fixtures(
            tmp_path,
            month=date(2023, 6, 1),
            ets_price=40.0,
            include_cps=False,
        )

        gas_xlsx = (tmp_path / "ons_gas_sap.xlsx").read_bytes()
        ccm_html = (tmp_path / "uk_ets_monthly.html").read_bytes()

        results = compute_fuel_cost(
            start_year=2023,
            end_year=2023,
            heat_rate=2.0,
            gas_carbon_intensity=0.184,
            include_carbon_price_support=False,
            cache_dir=tmp_path,
            gas_opener=lambda u: _landing_html() if "datasets" in u else gas_xlsx,
            carbon_opener=lambda u: ccm_html,
        )

        _, k_t = results[0]
        assert k_t == pytest.approx(64.72, abs=0.01)

    def test_spans_uk_local_day_in_settlement_periods(self, tmp_path: Path) -> None:
        """A BST day maps to 48 periods from 23:00 UTC the previous evening."""
        _write_gas_fixture(tmp_path, date(2023, 6, 15), sap_p_kwh=2.5)
        _write_carbon_fixtures(tmp_path, month=date(2023, 6, 1), ets_price=40.0)
        gas_xlsx = (tmp_path / "ons_gas_sap.xlsx").read_bytes()
        ccm_html = (tmp_path / "uk_ets_monthly.html").read_bytes()

        results = compute_fuel_cost(
            start_year=2023,
            end_year=2023,
            heat_rate=2.0,
            gas_carbon_intensity=0.184,
            include_carbon_price_support=True,
            cache_dir=tmp_path,
            gas_opener=lambda u: _landing_html() if "datasets" in u else gas_xlsx,
            carbon_opener=lambda u: ccm_html,
        )

        stamps = [ts for ts, _ in results]
        assert len(stamps) == 48
        assert stamps[0] == datetime(2023, 6, 14, 23, 0, tzinfo=UTC)
        assert stamps[-1] == datetime(2023, 6, 15, 22, 30, tzinfo=UTC)

    def test_clock_change_day_has_46_periods(self, tmp_path: Path) -> None:
        """2023-03-26 (spring forward) has 46 settlement periods."""
        _write_gas_fixture(tmp_path, date(2023, 3, 26), sap_p_kwh=2.5)
        _write_carbon_fixtures(tmp_path, month=date(2023, 3, 1), ets_price=40.0)
        gas_xlsx = (tmp_path / "ons_gas_sap.xlsx").read_bytes()
        ccm_html = (tmp_path / "uk_ets_monthly.html").read_bytes()

        results = compute_fuel_cost(
            start_year=2023,
            end_year=2023,
            heat_rate=2.0,
            gas_carbon_intensity=0.184,
            include_carbon_price_support=True,
            cache_dir=tmp_path,
            gas_opener=lambda u: _landing_html() if "datasets" in u else gas_xlsx,
            carbon_opener=lambda u: ccm_html,
        )

        assert len(results) == 46

    def test_timestamps_are_utc(self, tmp_path: Path) -> None:
        _write_gas_fixture(tmp_path, date(2023, 6, 15), sap_p_kwh=2.5)
        _write_carbon_fixtures(
            tmp_path,
            month=date(2023, 6, 1),
            ets_price=40.0,
        )

        gas_xlsx = (tmp_path / "ons_gas_sap.xlsx").read_bytes()
        ccm_html = (tmp_path / "uk_ets_monthly.html").read_bytes()

        results = compute_fuel_cost(
            start_year=2023,
            end_year=2023,
            heat_rate=2.0,
            gas_carbon_intensity=0.184,
            include_carbon_price_support=True,
            cache_dir=tmp_path,
            gas_opener=lambda u: _landing_html() if "datasets" in u else gas_xlsx,
            carbon_opener=lambda u: ccm_html,
        )
        for ts, _ in results:
            assert ts.tzinfo == UTC


# ── Helpers ─────────────────────────────────────────────────────────


def _landing_html() -> bytes:
    return (
        b'<a href="/file?uri=/economy/systemaveragepriceofgas'
        b'/2023/sap.xlsx">Download</a>'
    )


def _write_gas_fixture(cache_dir: Path, price_date: date, sap_p_kwh: float) -> None:
    """Write a minimal XLSX with one gas price row."""
    import io
    import zipfile

    epoch = date(1899, 12, 30)
    serial = (price_date - epoch).days

    ss_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="{ss_ns}" count="3" uniqueCount="3">'
        "<si><t>Date</t></si>"
        "<si><t>SAP actual day</t></si>"
        "<si><t>SAP seven-day rolling average</t></si>"
        "</sst>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{ss_ns}"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="1.Daily SAP Gas" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        '<Relationship Id="rId2" Target="sharedStrings.xml"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="xl/workbook.xml"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        "</Types>"
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{ss_ns}"><sheetData>'
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s"><v>1</v></c>'
        "</row>"
        '<row r="2">'
        f'<c r="A2"><v>{serial}</v></c>'
        f'<c r="B2"><v>{sap_p_kwh}</v></c>'
        "</row>"
        "</sheetData></worksheet>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/sharedStrings.xml", shared_strings)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)

    (cache_dir / "ons_gas_sap.xlsx").write_bytes(buf.getvalue())


def _write_carbon_fixtures(
    cache_dir: Path,
    month: date,
    ets_price: float,
    include_cps: bool = True,
) -> None:
    """Write CCM HTML and optionally EU ETS CSV for testing."""
    # The assessment month must be one month AFTER the data month
    # so that _months_before produces the right month.
    assess_m = month.month + 1
    assess_y = month.year
    if assess_m > 12:
        assess_m = 1
        assess_y += 1

    month_names = [
        "",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    assess_label = f"{month_names[assess_m]}-{assess_y % 100:02d}"

    html = (
        "<table>"
        "<tr><th>Month</th><th>ref</th><th>trigger</th>"
        "<th>monitoring</th><th>M1 avg</th><th>CCM?</th></tr>"
        f"<tr><td>{assess_label}</td><td>ref</td><td>£0</td>"
        f"<td>{month_names[month.month]}</td>"
        f"<td>£{ets_price:.2f}</td><td>No</td></tr>"
        "</table>"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "uk_ets_monthly.html").write_text(html, encoding="utf-8")
