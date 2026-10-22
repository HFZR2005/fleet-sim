"""Household demand for one civil day.

``DemandProfile`` is the interface. ``FixedDemandProfile`` wraps the kW list
milestone 1 stored in the home config. ``ElexonProfileClass1`` is Elexon's
published domestic unrestricted shape.
"""

import csv
from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from fleet_sim.models.demand import DemandSeries, ElexonSeason
from fleet_sim.models.home import SLOTS_PER_DAY

# (DT) in docs/formulation.md. The published profile is average kW, and a
# slot's energy is that power times this many hours.
HOURS_PER_SLOT = 0.5

# The 1997 average Profile Class 1 customer, as published. Not resized to a
# later typical annual consumption.
_ANNUAL_SCALE = 1.0

_PROFILE_PATH = Path(__file__).with_name("profile_class_1.csv")


class DemandProfile(Protocol):
    """Half-hourly demand for one UK civil day."""

    def demand(self, day: date) -> DemandSeries:
        """Return 48 slot energies in kWh for ``day``."""


class FixedDemandProfile:
    """The same half-hours on every date.

    ``demand_kw`` is average power, the unit in the home config. Slot energy
    is that power times 0.5 hours.
    """

    def __init__(self, demand_kw: Sequence[float]) -> None:
        if len(demand_kw) != SLOTS_PER_DAY:
            raise ValueError(
                "demand_kw must contain "
                f"{SLOTS_PER_DAY} half-hour values (got {len(demand_kw)})"
            )
        demand_kwh: list[float] = []
        for power_kw in demand_kw:
            if power_kw < 0:
                raise ValueError(
                    f"demand_kw must be at least 0 in every slot (got {power_kw})"
                )
            demand_kwh.append(power_kw * HOURS_PER_SLOT)
        self._demand_kwh = demand_kwh

    def demand(self, day: date) -> DemandSeries:
        """Return the configured day, labelled with ``day``."""
        return DemandSeries(day=day, demand_kwh=self._demand_kwh)


class ElexonProfileClass1:
    """Elexon Profile Class 1, domestic unrestricted customers.

    The shape is the UKERC Energy Data Centre dataset "Electricity user load
    profiles by profile class" (Elexon Ltd, published by the Electricity
    Association, 1997, open access):

    https://data.ceda.ac.uk/edc/d1/5af8ae29-86a7-4e8c-9fe4-1e2d99d9fb96

    ``profile_class_1.csv`` is that Profile Class 1 file. Each value is
    average kW. This profile multiplies by 0.5 hours and by ``_ANNUAL_SCALE``,
    which is 1, so a winter weekday totals 12.290 kWh. The file's clock time
    is the end of the half hour, and the rows run from local midnight.

    Seasons and day types follow Elexon's profiling definitions. The table
    has a weekday, a Saturday, and a Sunday in each season, so a bank holiday
    uses the weekday column. A clock-change date still gets these 48 values:
    the price loader is what rejects that civil day.
    """

    def demand(self, day: date) -> DemandSeries:
        """Return the published shape for ``day``'s season and day type."""
        column = _profiles()[_column_name(day)]
        demand_kwh = [power_kw * HOURS_PER_SLOT * _ANNUAL_SCALE for power_kw in column]
        return DemandSeries(day=day, demand_kwh=demand_kwh)


def _column_name(day: date) -> str:
    if day.weekday() == 5:
        day_type = "Sat"
    elif day.weekday() == 6:
        day_type = "Sun"
    else:
        day_type = "Wd"
    return f"{elexon_season(day)} {day_type}"


def elexon_season(day: date) -> ElexonSeason:
    """Elexon season for ``day``: Wtr, Spr, Smr, Hsr, or Aut.

    Winter runs from the autumn clock change through the day before the
    spring clock change. Spring then runs until the Friday before summer.
    Summer is the ten weeks before high summer. High summer runs from the
    sixth Saturday before the August bank holiday through the Sunday after
    it. Autumn runs from the next Monday through the day before the autumn
    clock change.
    """
    bank_holiday = _last_weekday(day.year, 8, 0)
    high_summer_start = bank_holiday - timedelta(days=37)
    high_summer_end = bank_holiday + timedelta(days=6)
    summer_start = high_summer_start - timedelta(days=70)
    summer_end = high_summer_start - timedelta(days=1)
    autumn_start = bank_holiday + timedelta(days=7)
    autumn_end = _last_weekday(day.year, 10, 6) - timedelta(days=1)
    spring_start = _last_weekday(day.year, 3, 6)
    spring_end = summer_start - timedelta(days=1)
    if summer_start <= day <= summer_end:
        return "Smr"
    if high_summer_start <= day <= high_summer_end:
        return "Hsr"
    if autumn_start <= day <= autumn_end:
        return "Aut"
    if spring_start <= day <= spring_end:
        return "Spr"
    return "Wtr"


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last ``weekday`` (Monday is 0) in ``month`` of ``year``."""
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


@lru_cache(maxsize=1)
def _profiles() -> dict[str, tuple[float, ...]]:
    with _PROFILE_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        columns = {
            name: list[float]() for name in fieldnames if name != "Time" and name
        }
        for row in reader:
            for name, values in columns.items():
                values.append(float(row[name]))
    loaded = {name: tuple(values) for name, values in columns.items()}
    for name, slots in loaded.items():
        if len(slots) != SLOTS_PER_DAY:
            raise ValueError(
                f"{name} must contain {SLOTS_PER_DAY} half-hour values "
                f"(got {len(slots)})"
            )
    return loaded
