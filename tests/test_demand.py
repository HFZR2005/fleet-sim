"""Demand profiles. These tests never touch the network."""

from datetime import date

import pytest
from pydantic import ValidationError

from fleet_sim.data.demand import (
    HOURS_PER_SLOT,
    DemandProfile,
    ElexonProfileClass1,
    FixedDemandProfile,
)
from fleet_sim.models.demand import DemandSeries

# Profile Class 1 winter weekday, published average kW summed over the day
# and converted at 0.5 kWh per kW. The scale factor is 1.
_WINTER_WEEKDAY_KWH = 12.290


def test_fixed_profile_converts_power_to_energy_and_repeats_the_day() -> None:
    profile: DemandProfile = FixedDemandProfile([1.0] * 48)

    monday = profile.demand(date(2024, 1, 15))
    tuesday = profile.demand(date(2024, 1, 16))

    assert monday.demand_kwh == [HOURS_PER_SLOT] * 48
    assert tuesday.demand_kwh == monday.demand_kwh
    assert sum(monday.demand_kwh) == pytest.approx(24.0)


def test_fixed_profile_rejects_a_short_or_negative_day() -> None:
    with pytest.raises(ValueError, match="48 half-hour values"):
        FixedDemandProfile([1.0] * 47)
    with pytest.raises(ValueError, match="at least 0"):
        FixedDemandProfile([-0.1] + [1.0] * 47)


def test_elexon_winter_weekday_matches_the_published_day() -> None:
    # 2024-01-15 is a Monday in winter. The first published winter-weekday
    # half hour is 0.33 kW, so the slot energy is 0.165 kWh. The day total
    # is the published column with no annual rescaling.
    series = ElexonProfileClass1().demand(date(2024, 1, 15))

    assert len(series.demand_kwh) == 48
    assert all(slot >= 0 for slot in series.demand_kwh)
    assert series.demand_kwh[0] == pytest.approx(0.33 * HOURS_PER_SLOT)
    assert sum(series.demand_kwh) == pytest.approx(_WINTER_WEEKDAY_KWH)


@pytest.mark.parametrize(
    ("day", "first_kw"),
    [
        (date(2024, 3, 30), 0.39),  # Saturday before the spring change: winter
        (date(2024, 3, 31), 0.33),  # spring clock change, a Sunday: spring
        (date(2024, 6, 15), 0.31),  # Saturday: summer
        (date(2024, 8, 26), 0.29),  # August bank holiday, a Monday: high summer
        (date(2024, 10, 26), 0.31),  # Saturday before the autumn change: autumn
        (date(2024, 10, 27), 0.41),  # autumn clock change, a Sunday: winter
    ],
)
def test_elexon_season_boundaries(day: date, first_kw: float) -> None:
    series = ElexonProfileClass1().demand(day)

    assert series.demand_kwh[0] == pytest.approx(first_kw * HOURS_PER_SLOT)
    assert all(slot >= 0 for slot in series.demand_kwh)


def test_demand_series_rejects_a_negative_slot() -> None:
    with pytest.raises(ValidationError, match="at least 0"):
        DemandSeries(day=date(2024, 1, 15), demand_kwh=[-1.0] + [0.0] * 47)
