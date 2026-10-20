"""Import prices for one region over one UK day.

The day length is the time grid in ``docs/formulation.md``.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from fleet_sim.models.home import SLOTS_PER_DAY

GSP_REGIONS = frozenset(
    {"A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P"}
)
_LONDON = ZoneInfo("Europe/London")
_HALF_HOUR = timedelta(minutes=30)


class ClockChangeDayError(ValueError):
    """The UK civil day does not have 48 half-hour slots.

    The clocks going forward leave 46 slots, and the clocks going back leave
    50. The time grid in ``docs/formulation.md`` is a 48-slot day, so these
    dates are rejected.
    """


class PriceSeries(BaseModel):
    """Half-hourly Agile import prices for one region and one UK civil day.

    ``timestamps_utc`` are timezone-aware UTC instants, 30 minutes apart.
    ``price_p_per_kwh`` is the same series as in ``docs/formulation.md``.
    A clock-change day cannot be represented: it does not span 48 slots.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    region: str
    day: date
    timestamps_utc: list[datetime]
    price_p_per_kwh: list[float]

    @field_validator("region")
    @classmethod
    def region_is_a_gsp_letter(cls, value: str) -> str:
        return require_gsp_region(value)

    @field_validator("timestamps_utc")
    @classmethod
    def timestamps_are_half_hours_in_utc(cls, value: list[datetime]) -> list[datetime]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                "timestamps_utc must contain "
                f"{SLOTS_PER_DAY} half-hour values (got {len(value)})"
            )
        previous: datetime | None = None
        for index, stamp in enumerate(value):
            if stamp.utcoffset() != timedelta(0):
                raise ValueError(
                    f"timestamps_utc[{index}] must be timezone-aware UTC "
                    f"(got {stamp!r})"
                )
            if previous is not None and stamp - previous != _HALF_HOUR:
                raise ValueError(
                    f"timestamps_utc[{index}] must be 30 minutes after the "
                    f"previous timestamp (got {stamp.isoformat()})"
                )
            previous = stamp
        return value

    @field_validator("price_p_per_kwh")
    @classmethod
    def prices_cover_a_day(cls, value: list[float]) -> list[float]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                "price_p_per_kwh must contain "
                f"{SLOTS_PER_DAY} half-hour values (got {len(value)})"
            )
        return value

    @model_validator(mode="after")
    def covers_the_london_day(self) -> "PriceSeries":
        start, end = london_day_bounds_utc(self.day)
        if self.timestamps_utc[0] != start:
            raise ValueError(
                f"timestamps_utc[0] must be Europe/London midnight on "
                f"{self.day.isoformat()} in UTC ({start.isoformat()})"
            )
        if self.timestamps_utc[-1] + _HALF_HOUR != end:
            raise ValueError(
                f"timestamps_utc must cover Europe/London {self.day.isoformat()} "
                f"through {end.isoformat()}"
            )
        return self


def require_gsp_region(region: str) -> str:
    """Return the uppercase GSP letter, or raise if it is not an Agile region."""
    code = region.upper()
    if code not in GSP_REGIONS:
        letters = ", ".join(sorted(GSP_REGIONS))
        raise ValueError(f"region must be one of {letters} (got {region!r})")
    return code


def london_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` in UTC for a 48-slot Europe/London civil day.

    ``day`` is a calendar date. A ``datetime`` is rejected so a clock time is
    not silently dropped. The spring and autumn clock changes do not last
    24 hours and raise ``ClockChangeDayError``, as in the time grid of
    ``docs/formulation.md``.
    """
    if isinstance(day, datetime):
        raise TypeError(f"day must be a datetime.date, not a datetime (got {day!r})")
    start = datetime.combine(day, time.min, tzinfo=_LONDON).astimezone(UTC)
    end = datetime.combine(
        day + timedelta(days=1), time.min, tzinfo=_LONDON
    ).astimezone(UTC)
    elapsed = end - start
    if elapsed != timedelta(hours=24):
        slots = elapsed // _HALF_HOUR
        hours = elapsed.total_seconds() / 3600
        raise ClockChangeDayError(
            f"{day.isoformat()} is a UK clock-change day with {slots} half-hour "
            f"slots ({hours:g} hours), not {SLOTS_PER_DAY}. The time grid in "
            "docs/formulation.md is a 48-slot day, so this date is rejected."
        )
    return start, end
