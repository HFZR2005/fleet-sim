"""Loader for NESO Historic Demand Data.

Downloads yearly CSV files from the NESO data portal (formerly National
Grid ESO).  Each row is one settlement period with National Demand,
embedded generation estimates, pump-storage pumping, and interconnector
flows.

Source: https://neso.energy/data-portal/historic-demand-data
Licence: Creative Commons Attribution 4.0 (CC BY 4.0).
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

_DEFAULT_CACHE_DIR = Path(".cache") / "prices"
_DATASET_ID = "8f2fe0af-871c-488d-8bad-960426f24601"
_PACKAGE_URL = (
    "https://api.neso.energy/api/3/action/datapackage_show?id=historic-demand-data"
)

_INTERCONNECTOR_COLUMNS = (
    "IFA_FLOW",
    "IFA2_FLOW",
    "BRITNED_FLOW",
    "MOYLE_FLOW",
    "EAST_WEST_FLOW",
    "NEMO_FLOW",
    "NSL_FLOW",
    "ELECLINK_FLOW",
    "VIKING_FLOW",
    "GREENLINK_FLOW",
)


class NesoDemandRow(BaseModel):
    """One settlement period from the NESO Historic Demand Data CSV."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_date: date
    settlement_period: int
    nd_mw: float
    pump_storage_pumping_mw: float
    interconnector_flow_mw: float


def load_neso_demand(
    *,
    year: int,
    cache_dir: Path | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> list[NesoDemandRow]:
    """Load NESO demand data for one year, caching the raw CSV on disk."""
    directory = _DEFAULT_CACHE_DIR if cache_dir is None else cache_dir
    fetch = _urlopen if opener is None else opener
    cache_path = directory / f"neso_demand_{year}.csv"

    if cache_path.is_file():
        raw = cache_path.read_bytes()
    else:
        url = _csv_url_for_year(year, fetch)
        raw = fetch(url)
        _write_cache(cache_path, raw)

    return _parse_csv(raw, year)


def _csv_url_for_year(year: int, fetch: Callable[[str], bytes]) -> str:
    """Discover the CSV download URL for *year* via the CKAN API."""
    body = fetch(_PACKAGE_URL)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("NESO package response is not valid JSON") from exc

    resources: list[dict[str, object]] = payload.get("result", {}).get("resources", [])
    needle = f"demanddata_{year}"
    needle_alt = f"demanddataupdate_{year}"
    for resource in resources:
        path = str(resource.get("path", "")).lower()
        if needle in path or needle_alt in path:
            url = resource.get("url") or resource.get("path")
            if isinstance(url, str) and url:
                return url

    raise ValueError(f"no NESO Historic Demand Data CSV found for year {year}")


def _parse_csv(raw: bytes, year: int) -> list[NesoDemandRow]:
    """Parse a NESO demand CSV into validated rows."""
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("NESO CSV has no header row")

    normalised = {_normalise(col): col for col in reader.fieldnames}
    rows: list[NesoDemandRow] = []

    for line_no, record in enumerate(reader, start=2):
        try:
            sd = _parse_date(record[normalised["SETTLEMENT_DATE"]])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"NESO CSV line {line_no}: bad SETTLEMENT_DATE") from exc

        if sd.year != year:
            continue

        period = int(record[normalised["SETTLEMENT_PERIOD"]])
        nd = _float(record, normalised, "ND")
        pump = _float(record, normalised, "PUMP_STORAGE_PUMPING")
        icf = _sum_interconnectors(record, normalised)

        try:
            row = NesoDemandRow(
                settlement_date=sd,
                settlement_period=period,
                nd_mw=nd,
                pump_storage_pumping_mw=pump,
                interconnector_flow_mw=icf,
            )
        except ValidationError as exc:
            raise ValueError(f"NESO CSV line {line_no}: validation failed") from exc
        rows.append(row)

    if not rows:
        raise ValueError(f"NESO CSV contains no rows for year {year}")
    return rows


def _sum_interconnectors(
    record: dict[str, str],
    normalised: dict[str, str],
) -> float:
    """Sum all interconnector flow columns present in the row."""
    total = 0.0
    for col in _INTERCONNECTOR_COLUMNS:
        original = normalised.get(col)
        if original is not None:
            val = record.get(original, "").strip()
            if val:
                total += float(val)
    return total


def _float(
    record: dict[str, str],
    normalised: dict[str, str],
    column: str,
) -> float:
    original = normalised.get(column)
    if original is None:
        raise ValueError(f"missing column {column} in NESO CSV")
    val = record[original].strip()
    if not val:
        raise ValueError(f"empty value for {column}")
    return float(val)


def _normalise(name: str) -> str:
    return name.strip().upper().replace(" ", "_")


def _parse_date(value: str) -> date:
    """Parse NESO date strings: DD/MM/YYYY, YYYY-MM-DD, or DD-Mon-YY."""
    from datetime import datetime as _dt

    value = value.strip()
    if "/" in value:
        parts = value.split("/")
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    parts = value.split("-")
    if len(parts) == 3 and parts[1].isalpha():
        return _dt.strptime(value, "%d-%b-%y").date()
    return date.fromisoformat(value)


def _write_cache(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _urlopen(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    if not isinstance(body, bytes):
        raise TypeError(f"NESO response was {type(body).__name__}, expected bytes")
    return body
