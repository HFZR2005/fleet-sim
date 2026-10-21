"""A fleet over three fixture days. No network."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fleet_sim.data import AgilePriceSource
from fleet_sim.data.source import PriceSource
from fleet_sim.fleet import Fleet, Home, identical_homes, run_fleet_days
from fleet_sim.models import BatterySpec, ClockChangeDayError, PriceSeries
from fleet_sim.models.prices import london_day_bounds_utc

FIXTURE = Path(__file__).parent / "fixtures" / "fleet_prices_three_days.json"
AGILE = Path(__file__).parent / "fixtures" / "agile_import_c_2024-06-15.json"


class _Days:
    def __init__(self, series: dict[date, PriceSeries]) -> None:
        self._series = series
        self.calls: list[date] = []

    def load(self, day: date, region: str) -> PriceSeries:
        self.calls.append(day)
        return self._series[day]


def _series_from_fixture() -> dict[date, PriceSeries]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    series: dict[date, PriceSeries] = {}
    for item in raw["days"]:
        day = date.fromisoformat(item["day"])
        start, _end = london_day_bounds_utc(day)
        series[day] = PriceSeries(
            region=raw["region"],
            day=day,
            timestamps_utc=[
                start + timedelta(minutes=30) * index for index in range(48)
            ],
            price_p_per_kwh=item["price_p_per_kwh"],
        )
    return series


def _fleet() -> Fleet:
    template = Home(
        home_id="home",
        region="C",
        battery=BatterySpec(
            capacity_kwh=2.0,
            max_charge_kw=8.0,
            max_discharge_kw=2.0,
            eta_charge=0.5,
            eta_discharge=0.5,
            soc_initial=0.25,
        ),
        demand_kw=[1.0] * 48,
    )
    fleet = identical_homes(template, 2)
    return fleet.model_copy(
        update={
            "homes": [
                fleet.homes[0],
                fleet.homes[1].model_copy(update={"demand_kw": [3.0] * 48}),
            ]
        }
    )


def test_three_fixture_days_report_each_day_and_the_spread() -> None:
    # Flat prices, lossy batteries: both homes stay idle. Imports are 1 kW
    # and 3 kW, so the fleet peak is 4 kW in slot 0 on every day. The mean
    # is 4, so the peak-to-average ratio is 1. Home peaks are 1 and 3, so
    # the coincidence factor is 1. Bills match the no-battery bills, so the
    # saving is 0. The three days differ only in the price level, which does
    # not move an idle battery, so the median and both ends of the range are
    # those same numbers.
    source = _Days(_series_from_fixture())
    report = run_fleet_days(
        _fleet(),
        start=date(2024, 6, 15),
        end=date(2024, 6, 17),
        region="C",
        price_source=source,
    )

    assert source.calls == [
        date(2024, 6, 15),
        date(2024, 6, 16),
        date(2024, 6, 17),
    ]
    assert [item.day for item in report.days] == source.calls
    for item in report.days:
        assert item.metrics.peak_demand_kw == pytest.approx(4.0)
        assert item.metrics.peak_slot == 0
        assert item.metrics.total_savings_pence == pytest.approx(0.0)
        assert item.metrics.coincidence_factor == pytest.approx(1.0)
    assert report.peak_demand_kw.median == pytest.approx(4.0)
    assert report.peak_demand_kw.minimum == pytest.approx(4.0)
    assert report.peak_demand_kw.maximum == pytest.approx(4.0)
    assert report.total_savings_pence.median == pytest.approx(0.0)


def test_a_clock_change_day_is_rejected_before_a_request() -> None:
    class _Source:
        def load(self, day: date, region: str) -> PriceSeries:
            raise AssertionError(day)

    with pytest.raises(ClockChangeDayError, match="clock-change"):
        run_fleet_days(
            _fleet(),
            start=date(2024, 10, 27),
            end=date(2024, 10, 27),
            region="C",
            price_source=_Source(),
        )


def test_a_second_run_reuses_cached_prices(tmp_path: Path) -> None:
    calls: list[str] = []

    def opener(url: str) -> bytes:
        calls.append(url)
        return AGILE.read_bytes()

    source: PriceSource = AgilePriceSource(cache_dir=tmp_path, opener=opener)
    template = Home(
        home_id="home",
        region="C",
        battery=BatterySpec(
            capacity_kwh=2.0,
            max_charge_kw=8.0,
            max_discharge_kw=2.0,
            eta_charge=0.5,
            eta_discharge=0.5,
            soc_initial=0.25,
        ),
        demand_kw=[1.0] * 48,
    )
    fleet = identical_homes(template, 1)
    first = run_fleet_days(
        fleet,
        start=date(2024, 6, 15),
        end=date(2024, 6, 15),
        region="C",
        price_source=source,
    )
    second = run_fleet_days(
        fleet,
        start=date(2024, 6, 15),
        end=date(2024, 6, 15),
        region="C",
        price_source=source,
    )

    assert len(calls) == 1
    assert second.days[0].metrics == first.days[0].metrics
