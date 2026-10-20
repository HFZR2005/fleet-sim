"""Agile import prices from a saved fixture. These tests never touch the network."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pytest
from pydantic import ValidationError

from fleet_sim.data import load_agile_import_prices
from fleet_sim.data.agile import AGILE_IMPORT_PRODUCT
from fleet_sim.models import ClockChangeDayError, PriceSeries

FIXTURE = Path(__file__).parent / "fixtures" / "agile_import_c_2024-06-15.json"
DAY = date(2024, 6, 15)
# 2024-06-15 is BST, so local midnight is 23:00 UTC the previous calendar day.
START = datetime(2024, 6, 14, 23, 0, tzinfo=UTC)


def _opener(body: bytes, calls: list[str]) -> Callable[[str], bytes]:
    def opener(url: str) -> bytes:
        calls.append(url)
        return body

    return opener


def _fail(url: str) -> bytes:
    raise AssertionError(f"network used for {url}")


def test_load_returns_forty_eight_utc_prices(tmp_path: Path) -> None:
    # Region C, 2024-06-15. Slot 0 is value_inc_vat -8.25, not value_exc_vat
    # -9.25. The fixture lists rates newest first, and slot 5 has valid_to null.
    calls: list[str] = []
    series = load_agile_import_prices(
        DAY, "c", cache_dir=tmp_path, opener=_opener(FIXTURE.read_bytes(), calls)
    )

    assert len(calls) == 1
    requested = unquote(calls[0])
    assert AGILE_IMPORT_PRODUCT == "AGILE-24-10-01"
    assert f"E-1R-{AGILE_IMPORT_PRODUCT}-C/standard-unit-rates/" in requested
    assert "period_from=2024-06-14T23:00:00Z" in requested
    assert "period_to=2024-06-15T23:00:00Z" in requested

    assert series.region == "C"
    assert series.day == DAY
    assert len(series.timestamps_utc) == 48
    assert len(series.price_p_per_kwh) == 48
    assert series.timestamps_utc[0] == START
    assert series.timestamps_utc[-1] == datetime(2024, 6, 15, 22, 30, tzinfo=UTC)
    assert series.price_p_per_kwh[0] == -8.25
    assert series.price_p_per_kwh[1] == 1.0
    assert series.price_p_per_kwh[47] == 47.0
    for index, stamp in enumerate(series.timestamps_utc):
        assert stamp.utcoffset() == timedelta(0)
        if index:
            assert stamp - series.timestamps_utc[index - 1] == timedelta(minutes=30)


def test_second_call_reads_the_cache_and_does_not_request(tmp_path: Path) -> None:
    calls: list[str] = []
    first = load_agile_import_prices(
        DAY, "C", cache_dir=tmp_path, opener=_opener(FIXTURE.read_bytes(), calls)
    )

    second = load_agile_import_prices(DAY, "C", cache_dir=tmp_path, opener=_fail)

    assert second == first
    assert len(calls) == 1
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1
    assert cached[0].name == f"{AGILE_IMPORT_PRODUCT}_C_2024-06-15.json"


def test_default_cache_directory_is_dot_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    load_agile_import_prices(DAY, "C", opener=_opener(FIXTURE.read_bytes(), calls))

    cache = tmp_path / ".cache" / "agile" / f"{AGILE_IMPORT_PRODUCT}_C_2024-06-15.json"
    assert cache.is_file()
    again = load_agile_import_prices(DAY, "C", opener=_fail)
    assert again.price_p_per_kwh[0] == -8.25
    assert len(calls) == 1


def test_follows_next_until_the_pages_end(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = payload["results"]
    next_url = "https://api.octopus.energy/fixture-page-2"
    page_1 = {**payload, "results": results[:20], "next": next_url}
    page_2 = {**payload, "results": results[20:], "next": None}
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        if len(calls) == 1:
            return json.dumps(page_1).encode()
        assert url == next_url
        return json.dumps(page_2).encode()

    series = load_agile_import_prices(DAY, "C", cache_dir=tmp_path, opener=opener)

    assert len(calls) == 2
    assert series.price_p_per_kwh[0] == -8.25
    assert series.price_p_per_kwh[47] == 47.0


def test_a_repeated_page_url_is_an_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        page = {**payload, "next": url}
        return json.dumps(page).encode()

    with pytest.raises(ValueError, match="repeats a page"):
        load_agile_import_prices(DAY, "C", cache_dir=tmp_path, opener=opener)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("day", "slots"),
    [
        # 2024-03-31: midnight 00:00Z, next midnight 23:00Z the same day (23h).
        (date(2024, 3, 31), 46),
        # 2024-10-27: midnight 23:00Z the previous day, next midnight 00:00Z
        # two calendar days later (25h).
        (date(2024, 10, 27), 50),
        (date(2025, 3, 30), 46),
        (date(2026, 10, 25), 50),
    ],
)
def test_clock_change_days_are_rejected_without_a_request(
    tmp_path: Path, day: date, slots: int
) -> None:
    with pytest.raises(ClockChangeDayError, match=f"{slots} half-hour") as caught:
        load_agile_import_prices(day, "C", cache_dir=tmp_path, opener=_fail)

    assert str(day) in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_the_day_before_the_spring_change_is_requested(tmp_path: Path) -> None:
    calls: list[str] = []
    with pytest.raises(ValueError, match="missing"):
        load_agile_import_prices(
            date(2024, 3, 30),
            "C",
            cache_dir=tmp_path,
            opener=_opener(FIXTURE.read_bytes(), calls),
        )

    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_unknown_region_is_rejected_without_a_request(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="region"):
        load_agile_import_prices(DAY, "I", cache_dir=tmp_path, opener=_fail)


def test_a_datetime_is_not_a_civil_date(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="datetime.date"):
        load_agile_import_prices(
            datetime(2024, 6, 15, 12, 0),
            "C",
            cache_dir=tmp_path,
            opener=_fail,
        )


def test_missing_slot_is_an_error_and_is_not_cached(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["results"] = payload["results"][:-1]
    calls: list[str] = []
    with pytest.raises(ValueError, match="missing"):
        load_agile_import_prices(
            DAY,
            "C",
            cache_dir=tmp_path,
            opener=_opener(json.dumps(payload).encode(), calls),
        )

    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_duplicate_slot_is_an_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["results"].append(payload["results"][0])
    with pytest.raises(ValueError, match="duplicate"):
        load_agile_import_prices(
            DAY,
            "C",
            cache_dir=tmp_path,
            opener=_opener(json.dumps(payload).encode(), []),
        )


def test_a_rate_that_does_not_last_half_an_hour_is_an_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["results"][0]["valid_to"] = "2024-06-15T23:30:00Z"
    with pytest.raises(ValueError, match="30 minutes"):
        load_agile_import_prices(
            DAY,
            "C",
            cache_dir=tmp_path,
            opener=_opener(json.dumps(payload).encode(), []),
        )


def test_a_naive_rate_timestamp_is_an_error(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["results"][0]["valid_from"] = "2024-06-15T22:30:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        load_agile_import_prices(
            DAY,
            "C",
            cache_dir=tmp_path,
            opener=_opener(json.dumps(payload).encode(), []),
        )


def test_price_series_rejects_a_short_day() -> None:
    stamps = [START + timedelta(minutes=30 * index) for index in range(47)]
    with pytest.raises(ValidationError, match="48 half-hour"):
        PriceSeries(
            region="C",
            day=DAY,
            timestamps_utc=stamps,
            price_p_per_kwh=[1.0] * 47,
        )


def test_price_series_rejects_a_naive_timestamp() -> None:
    stamps = [START + timedelta(minutes=30 * index) for index in range(48)]
    stamps[3] = stamps[3].replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        PriceSeries(
            region="C",
            day=DAY,
            timestamps_utc=stamps,
            price_p_per_kwh=[1.0] * 48,
        )


def test_price_series_rejects_a_clock_change_day() -> None:
    # Spring forward: local midnight is 00:00Z, but the civil day is only 23h.
    start = datetime(2024, 3, 31, 0, 0, tzinfo=UTC)
    stamps = [start + timedelta(minutes=30 * index) for index in range(48)]
    with pytest.raises(ValidationError, match="clock-change"):
        PriceSeries(
            region="C",
            day=date(2024, 3, 31),
            timestamps_utc=stamps,
            price_p_per_kwh=[1.0] * 48,
        )
