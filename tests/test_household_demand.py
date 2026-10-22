"""Low Carbon London household days. The fixture is a real extract."""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from fleet_sim.data.households import (
    HouseholdDemandPool,
    _year_distance,
    ingest_low_carbon_london,
)
from fleet_sim.random_streams import RandomStreams

_FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "lcl_household_days.csv"


def _pool() -> HouseholdDemandPool:
    return HouseholdDemandPool.read(_FIXTURE)


def test_fixture_days_keep_the_published_half_hours() -> None:
    # MAC000002 on 2012-10-29, first stamp 00:30:00, which ends the first
    # half hour: 0.338 kWh. MAC000003 on 2012-02-21 starts at 3.3789999 kWh.
    pool = _pool()
    october = pool.load("MAC000002", date(2012, 10, 29))
    february = pool.load("MAC000003", date(2012, 2, 21))

    assert october.trial_day == date(2012, 10, 29)
    assert october.fallback is None
    assert october.series.day == date(2012, 10, 29)
    assert october.series.demand_kwh[0] == pytest.approx(0.338)
    assert len(october.series.demand_kwh) == 48
    assert february.series.demand_kwh[0] == pytest.approx(3.3789999)
    assert all(slot >= 0 for slot in october.series.demand_kwh)


def test_incomplete_and_null_days_are_dropped() -> None:
    # 2012-10-12 has 47 half hours. 2012-12-19 contains a Null at 12:37:27.
    # Neither date is a trial day the pool will return.
    pool = _pool()

    assert pool.load("MAC000002", date(2012, 10, 12)).trial_day != date(2012, 10, 12)
    assert pool.load("MAC000002", date(2012, 12, 19)).trial_day != date(2012, 12, 19)


def test_a_matching_season_and_day_type_uses_the_nearest_trial_day() -> None:
    # 1 January and 29 October are both winter weekdays in the fixture.
    # 1 January 2026 is that day of the year. 29 October 2026 is the other.
    # 30 November is 32 days from each on a non-leap year, so the earlier
    # trial day is used. 3 January 2026 is a winter Saturday, and the only
    # winter weekend in the fixture is 28 October 2012.
    pool = _pool()
    new_year = pool.load("MAC000002", date(2026, 1, 1))
    late_october = pool.load("MAC000002", date(2026, 10, 29))
    midpoint = pool.load("MAC000002", date(2026, 11, 30))
    weekend = pool.load("MAC000002", date(2026, 1, 3))

    assert new_year.trial_day == date(2013, 1, 1)
    assert new_year.fallback is None
    assert new_year.series.day == date(2026, 1, 1)
    assert new_year.series.demand_kwh[0] == pytest.approx(0.241)
    assert late_october.trial_day == date(2012, 10, 29)
    assert late_october.fallback is None
    assert midpoint.trial_day == date(2012, 10, 29)
    assert midpoint.fallback is None
    assert weekend.trial_day == date(2012, 10, 28)
    assert weekend.series.demand_kwh[0] == pytest.approx(0.395)
    assert weekend.fallback is None


def test_a_missing_bin_falls_back_and_records_what_was_wanted() -> None:
    # MAC000003 has only Tuesday 21 February 2012, a winter weekday.
    # 15 June 2026 is a summer weekday, so the February day is the fallback.
    # 27 July 2026 is a high-summer weekday. The nearest MAC000002 day is
    # 13 May 2013, 75 days away, against 93 days to 28 October.
    pool = _pool()
    missing = pool.load("MAC000003", date(2026, 6, 15))
    high_summer = pool.load("MAC000002", date(2026, 7, 27))

    assert missing.trial_day == date(2012, 2, 21)
    assert missing.series.day == date(2026, 6, 15)
    assert missing.fallback is not None
    assert missing.fallback.household_id == "MAC000003"
    assert missing.fallback.simulated_day == date(2026, 6, 15)
    assert missing.fallback.trial_day == date(2012, 2, 21)
    assert missing.fallback.wanted_season == "Smr"
    assert missing.fallback.wanted_weekend is False
    assert high_summer.trial_day == date(2013, 5, 13)
    assert high_summer.series.demand_kwh[0] == pytest.approx(0.138)
    assert high_summer.fallback is not None
    assert high_summer.fallback.wanted_season == "Hsr"
    assert high_summer.fallback.wanted_weekend is False


def test_assignment_is_a_reproducible_draw_without_replacement() -> None:
    pool = _pool()
    first = pool.assign(2, RandomStreams(7))
    second = pool.assign(2, RandomStreams(7))
    battery_first = RandomStreams(7)
    battery_first.generator("battery").random(4)

    assert first == second
    assert sorted(first) == ["MAC000002", "MAC000003"]
    assert len(set(first)) == 2
    assert pool.assign(2, battery_first) == first


def test_a_fleet_larger_than_the_pool_is_rejected() -> None:
    pool = _pool()

    with pytest.raises(ValueError, match="the pool has 2"):
        pool.assign(3, RandomStreams(1))


def test_year_distance_wraps_and_treats_29_february_as_28_february() -> None:
    assert _year_distance(date(2024, 2, 29), date(2012, 2, 28)) == 0
    assert _year_distance(date(2026, 1, 1), date(2012, 12, 31)) == 1


def test_ingest_writes_a_cache_that_reads_back(tmp_path: Path) -> None:
    cached = ingest_low_carbon_london(_FIXTURE, cache_dir=tmp_path)
    reread = HouseholdDemandPool.read(cached)
    original = _pool().load("MAC000002", date(2026, 1, 3))
    again = reread.load("MAC000002", date(2026, 1, 3))

    assert cached == tmp_path / "household_days.csv"
    assert again.trial_day == original.trial_day
    assert again.series.demand_kwh == pytest.approx(original.series.demand_kwh)


def test_a_zip_and_a_directory_of_csvs_read_the_same_days(tmp_path: Path) -> None:
    archive_path = tmp_path / "lcl.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(_FIXTURE, "CC_LCL-FullData.csv")
    directory = tmp_path / "parts"
    directory.mkdir()
    (directory / "part.csv").write_bytes(_FIXTURE.read_bytes())
    expected = _pool().load("MAC000002", date(2026, 6, 15))

    from_zip = HouseholdDemandPool.read(archive_path).load(
        "MAC000002", date(2026, 6, 15)
    )
    from_dir = HouseholdDemandPool.read(directory).load("MAC000002", date(2026, 6, 15))

    assert from_zip.trial_day == expected.trial_day
    assert from_zip.series.demand_kwh == pytest.approx(expected.series.demand_kwh)
    assert from_dir.trial_day == expected.trial_day
