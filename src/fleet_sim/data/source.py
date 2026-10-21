"""Price lookup by region and date.

Callers depend on ``PriceSource``. The Agile fetcher is one implementation.
"""

from datetime import date
from typing import Protocol

from fleet_sim.models.prices import PriceSeries, require_gsp_region


class PriceSource(Protocol):
    """Import prices for one region and one UK civil day."""

    def load(self, day: date, region: str) -> PriceSeries:
        """Return the half-hourly import prices for ``region`` on ``day``."""


class FixturePriceSource:
    """One saved ``PriceSeries``, for tests that must not touch the network."""

    def __init__(self, series: PriceSeries) -> None:
        self._series = series

    def load(self, day: date, region: str) -> PriceSeries:
        """Return the saved series when the day and region match it."""
        region_code = require_gsp_region(region)
        saved = self._series
        if day != saved.day or region_code != saved.region:
            raise ValueError(
                f"fixture has prices for {saved.region} on "
                f"{saved.day.isoformat()}, not {region_code} on {day.isoformat()}"
            )
        return saved
