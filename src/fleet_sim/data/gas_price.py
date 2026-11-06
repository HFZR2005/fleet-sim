"""Loader for daily GB gas System Average Price (SAP).

Downloads the latest XLSX edition from the ONS, which republishes
National Gas Transmission's SAP data as daily prices in p/kWh.

Source: https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas
Licence: Open Government Licence v3.0.
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_DEFAULT_CACHE_DIR = Path(".cache") / "prices"

_LANDING_URL = (
    "https://www.ons.gov.uk/economy/economicoutputandproductivity"
    "/output/datasets/systemaveragepricesapofgas"
)

_EXCEL_EPOCH = date(1899, 12, 30)

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_P_KWH_TO_GBP_MWH = 10.0


class GasPriceRow(BaseModel):
    """One day of GB gas SAP data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    price_date: date
    sap_gbp_per_mwh: float


def load_gas_prices(
    *,
    start_year: int,
    end_year: int,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[GasPriceRow]:
    """Load daily gas SAP for *start_year* through *end_year* inclusive.

    Downloads the latest ONS XLSX edition (which contains the full
    history from 2018 onwards), caches it on disk, and parses the
    daily SAP sheet.

    Returns rows sorted by date, filtered to [start_year, end_year].
    """
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    fetch = _urlopen if opener is None else opener

    xlsx_bytes = _get_xlsx(directory, fetch)
    all_rows = _parse_sap_xlsx(xlsx_bytes)

    return [row for row in all_rows if start_year <= row.price_date.year <= end_year]


def _get_xlsx(cache_dir: Path, fetch: Callable[[str], bytes]) -> bytes:
    """Download the ONS SAP XLSX, caching on disk."""
    cache_path = cache_dir / "ons_gas_sap.xlsx"

    if cache_path.is_file():
        return cache_path.read_bytes()

    landing_html = fetch(_LANDING_URL).decode("utf-8", errors="replace")
    xlsx_url = _find_latest_xlsx_url(landing_html)
    raw = fetch(xlsx_url)
    _write_cache(cache_path, raw)
    return raw


def _find_latest_xlsx_url(html: str) -> str:
    """Extract the most recent XLSX download link from the ONS landing page."""
    pattern = r'href="(/file\?uri=[^"]*systemaveragepriceofgas[^"]*\.xlsx)"'
    matches = re.findall(pattern, html, re.IGNORECASE)
    if not matches:
        raise ValueError("no XLSX download link found on the ONS SAP page")
    url_path = matches[0]
    return f"https://www.ons.gov.uk{url_path}"


def _parse_sap_xlsx(raw: bytes) -> list[GasPriceRow]:
    """Parse the ONS SAP XLSX into daily price rows.

    The workbook has a sheet named ``1.Daily SAP Gas`` with columns:
    A = Date (Excel serial number), B = SAP actual day (p/kWh).
    """
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        shared_strings = _parse_shared_strings(zf)
        sheet_file = _find_daily_sheet(zf)
        return _parse_sheet(zf, sheet_file, shared_strings)


def _parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Parse the XLSX shared strings table."""
    try:
        ss_xml = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(ss_xml)
    strings: list[str] = []
    for si in root.findall(f".//{{{_SPREADSHEET_NS}}}si"):
        parts: list[str] = []
        for t_el in si.findall(f".//{{{_SPREADSHEET_NS}}}t"):
            if t_el.text:
                parts.append(t_el.text)
        strings.append("".join(parts))
    return strings


def _find_daily_sheet(zf: zipfile.ZipFile) -> str:
    """Find the worksheet file for '1.Daily SAP Gas'."""
    wb_xml = zf.read("xl/workbook.xml")
    wb_root = ET.fromstring(wb_xml)

    rels_xml = zf.read("xl/_rels/workbook.xml.rels")
    rels_root = ET.fromstring(rels_xml)

    rid_to_target: dict[str, str] = {}
    for rel in rels_root.findall(f"{{{_RELS_NS}}}Relationship"):
        rid_to_target[rel.attrib["Id"]] = rel.attrib["Target"]

    for sheet in wb_root.findall(f".//{{{_SPREADSHEET_NS}}}sheet"):
        name = sheet.attrib.get("name", "")
        if "daily" in name.lower() and "sap" in name.lower():
            rid = sheet.attrib[
                f"{{{_RELS_NS.replace('package/2006', 'officeDocument/2006')}}}id"
            ]
            target = rid_to_target.get(rid, "")
            return f"xl/{target}"

    raise ValueError("no 'Daily SAP Gas' sheet found in the XLSX workbook")


def _parse_sheet(
    zf: zipfile.ZipFile,
    sheet_file: str,
    shared_strings: list[str],
) -> list[GasPriceRow]:
    """Parse date and SAP columns from the daily sheet."""
    sheet_xml = zf.read(sheet_file)
    root = ET.fromstring(sheet_xml)

    header_row = _find_header_row(root, shared_strings)

    rows: list[GasPriceRow] = []
    for row_el in root.findall(f".//{{{_SPREADSHEET_NS}}}row"):
        row_num = int(row_el.attrib.get("r", "0"))
        if row_num <= header_row:
            continue

        cells = {
            _col_letter(c.attrib.get("r", "")): _cell_value(c, shared_strings)
            for c in row_el.findall(f"{{{_SPREADSHEET_NS}}}c")
        }

        date_val = cells.get("A", "")
        sap_val = cells.get("B", "")

        if not date_val or not sap_val:
            continue

        try:
            serial = int(float(date_val))
            price_date = _excel_serial_to_date(serial)
            sap_p_kwh = float(sap_val)
        except (ValueError, OverflowError):
            continue

        rows.append(
            GasPriceRow(
                price_date=price_date,
                sap_gbp_per_mwh=sap_p_kwh * _P_KWH_TO_GBP_MWH,
            )
        )

    rows.sort(key=lambda r: r.price_date)
    return rows


def _find_header_row(root: ET.Element, shared_strings: list[str]) -> int:
    """Find the row number of the header row ('Date', 'SAP actual day')."""
    for row_el in root.findall(f".//{{{_SPREADSHEET_NS}}}row"):
        for c in row_el.findall(f"{{{_SPREADSHEET_NS}}}c"):
            val = _cell_value(c, shared_strings)
            if val.strip().lower() == "date":
                return int(row_el.attrib.get("r", "0"))
    return 0


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Extract the display value of a cell."""
    typ = cell.attrib.get("t", "")
    v_el = cell.find(f"{{{_SPREADSHEET_NS}}}v")
    if v_el is None or v_el.text is None:
        return ""
    if typ == "s":
        idx = int(v_el.text)
        return shared_strings[idx] if idx < len(shared_strings) else ""
    return v_el.text


def _col_letter(ref: str) -> str:
    """Extract column letter(s) from a cell reference like 'B12'."""
    return "".join(c for c in ref if c.isalpha())


def _excel_serial_to_date(serial: int) -> date:
    """Convert an Excel serial number to a Python date."""
    return _EXCEL_EPOCH + timedelta(days=serial)


def _write_cache(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _urlopen(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read()
    if not isinstance(body, bytes):
        raise TypeError(f"ONS response was {type(body).__name__}, expected bytes")
    return body
