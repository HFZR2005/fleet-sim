"""One day's price inputs for the fleet in the loop, and the price of load.

``day_price_inputs`` reads R, k and π for every slot of one UK day with the
milestone 4.5 loaders. ``DayPriceInputs.prices`` is (PRICE): the Agile rate
in each slot when the fleet adds b GW.

See ``docs/formulation.md``, Anchoring and Fleet in the loop.
"""

from datetime import date
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    SkipValidation,
    field_validator,
    model_validator,
)

from fleet_sim.data.agile_formula import EPG_ADJUSTMENTS
from fleet_sim.data.agile_history import HistoricalAgileSource
from fleet_sim.data.fuel_cost import compute_fuel_cost
from fleet_sim.data.residual_load import load_residual_load
from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.data.wholesale import invert_rates
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.models.prices import (
    PriceSeries,
    london_day_bounds_utc,
    require_gsp_region,
)
from fleet_sim.prices.config import FuelCostConfig
from fleet_sim.prices.curves import FittedCurve
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.parameters import PriceModel
from fleet_sim.prices.response import price_response
from fleet_sim.prices.targets import Target

_EPG_START = min(e.start for e in EPG_ADJUSTMENTS)
_EPG_END = max(e.end for e in EPG_ADJUSTMENTS)


class DayPriceInputs(BaseModel):
    """What (PRICE) needs for one UK day in one region, slot by slot.

    ``wholesale_gbp_per_mwh`` is π_t, or its lower bound π_t⁻ when the slot is
    ``censored``; ``wholesale_upper_gbp_per_mwh`` is then π_t⁺, or ``None``
    when only a lower bound is known. ``historical`` is the Agile rate P_t(0).
    ``curve`` is h and ``target`` says how h becomes a price (k_t h for the
    fuel-adjusted target, h for a raw one). Any ``FittedCurve`` will do, so a
    test can pass a simple curve of its own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    region: str
    day: date
    residual_load_gw: list[float]
    fuel_cost_gbp_per_mwh: list[float]
    wholesale_gbp_per_mwh: list[float]
    censored: list[bool]
    wholesale_upper_gbp_per_mwh: list[float | None]
    historical: PriceSeries
    curve: SkipValidation[FittedCurve]
    target: SkipValidation[Target]

    @field_validator("region")
    @classmethod
    def region_is_a_gsp_letter(cls, value: str) -> str:
        return require_gsp_region(value)

    @model_validator(mode="after")
    def slots_cover_a_day(self) -> Self:
        for name in (
            "residual_load_gw",
            "fuel_cost_gbp_per_mwh",
            "wholesale_gbp_per_mwh",
            "censored",
            "wholesale_upper_gbp_per_mwh",
        ):
            length = len(getattr(self, name))
            if length != SLOTS_PER_DAY:
                raise ValueError(
                    f"{name} must contain {SLOTS_PER_DAY} half-hour values "
                    f"(got {length})"
                )
        if self.historical.day != self.day or self.historical.region != self.region:
            raise ValueError("historical must be the same day and region")
        return self

    def prices(self, added_load_gw: list[float]) -> PriceSeries:
        """The Agile rate in each slot when the fleet adds ``added_load_gw``.

        (PRICE), ``docs/formulation.md``, Price as a function of load:

            P_t(b) = A_t(π_t + k_t [h(R_t + b_t) − h(R_t)]),

        with the clipped anchor π̂_t in place of π_t in a censored slot.
        ``price_response`` does the anchoring and A_t.
        """
        if len(added_load_gw) != SLOTS_PER_DAY:
            raise ValueError(
                f"added_load_gw must contain {SLOTS_PER_DAY} half-hour values "
                f"(got {len(added_load_gw)})"
            )
        return price_response(
            self._slots(), self.curve, self.target, added_load_gw, region=self.region
        )

    def out_of_range_slots(
        self, added_load_gw: list[float], curve_range_gw: tuple[float, float]
    ) -> int:
        """How many slots have R_t + b_t outside ``curve_range_gw``.

        The ends of the range count as inside. ``docs/formulation.md``,
        Open choices, Range of the curve.
        """
        if len(added_load_gw) != SLOTS_PER_DAY:
            raise ValueError(
                f"added_load_gw must contain {SLOTS_PER_DAY} half-hour values "
                f"(got {len(added_load_gw)})"
            )
        low, high = curve_range_gw
        return sum(
            not low <= r + b <= high
            for r, b in zip(self.residual_load_gw, added_load_gw, strict=True)
        )

    def _slots(self) -> PriceDataset:
        """The day's slots as the observations ``price_response`` reads."""
        observations = [
            PriceObservation(
                settlement_start=stamp,
                wholesale_price_gbp_per_mwh=price,
                censored=censored,
                wholesale_upper_gbp_per_mwh=upper,
                residual_load_gw=load,
                fuel_cost_gbp_per_mwh=cost,
                year=stamp.year,
            )
            for stamp, price, censored, upper, load, cost in zip(
                self.historical.timestamps_utc,
                self.wholesale_gbp_per_mwh,
                self.censored,
                self.wholesale_upper_gbp_per_mwh,
                self.residual_load_gw,
                self.fuel_cost_gbp_per_mwh,
                strict=True,
            )
        ]
        return PriceDataset(observations=observations, drops=[])


def day_price_inputs(
    day: date,
    region: str,
    cache_dir: Path,
    *,
    model: PriceModel,
    fuel_cost: FuelCostConfig,
) -> DayPriceInputs:
    """R, k and π for each slot of ``day``, its historical rates and its curve.

    π comes from inverting the Agile rates (``invert_rates``), R from
    ``load_residual_load`` and k from ``compute_fuel_cost`` with
    ``fuel_cost``, all read through ``cache_dir``. A capped slot is kept as
    a censored one, with π as bounds, as in ``build_dataset``. The curve is
    ``model.curve_for(day.year)``.

    Raises ``ValueError`` naming the day for a day in the Energy Price
    Guarantee, whose rates can't be recomputed, and for a day missing any
    input in any slot. No day is skipped.
    """
    region_code = require_gsp_region(region)
    if _EPG_START <= day <= _EPG_END:
        raise ValueError(
            f"{day.isoformat()} is in the Energy Price Guarantee "
            f"({_EPG_START} to {_EPG_END}); its Agile rates can't be recomputed, "
            "so it can't be priced in the loop"
        )
    try:
        curve = model.curve_for(day.year)
    except KeyError as exc:
        raise ValueError(f"{day.isoformat()}: {exc.args[0]}") from exc

    period_from, period_to = london_day_bounds_utc(day)
    rates = {
        rate.settlement_start: rate
        for rate in invert_rates(
            region=region_code,
            period_from=period_from,
            period_to=period_to,
            cache_dir=cache_dir,
        )
    }
    loads = dict(
        load_residual_load(start_year=day.year, end_year=day.year, cache_dir=cache_dir)
    )
    costs = dict(
        compute_fuel_cost(
            start_year=day.year,
            end_year=day.year,
            heat_rate=fuel_cost.heat_rate,
            gas_carbon_intensity=fuel_cost.gas_carbon_intensity,
            include_carbon_price_support=fuel_cost.include_carbon_price_support,
            cache_dir=cache_dir,
        )
    )
    stamps = settlement_periods_utc(day)
    for name, found in (
        ("Agile rate", rates.keys()),
        ("residual load", loads.keys()),
        ("fuel cost", costs.keys()),
    ):
        missing = sum(stamp not in found for stamp in stamps)
        if missing:
            raise ValueError(
                f"{day.isoformat()} has no {name} for {missing} of "
                f"{len(stamps)} slots; every slot needs every input"
            )

    slot_rates = [rates[stamp] for stamp in stamps]
    return DayPriceInputs(
        region=region_code,
        day=day,
        residual_load_gw=[loads[stamp] for stamp in stamps],
        fuel_cost_gbp_per_mwh=[costs[stamp] for stamp in stamps],
        wholesale_gbp_per_mwh=[rate.wholesale_gbp_per_mwh for rate in slot_rates],
        censored=[rate.capped for rate in slot_rates],
        wholesale_upper_gbp_per_mwh=[
            rate.wholesale_upper_gbp_per_mwh for rate in slot_rates
        ],
        historical=HistoricalAgileSource(cache_dir=cache_dir).load(day, region_code),
        curve=curve,
        target=model.target,
    )
