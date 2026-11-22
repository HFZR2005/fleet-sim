"""Price inputs for one day in the loop, and the price as a function of load."""

from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest

from fleet_sim.data.agile_history import HistoricalAgileSource
from fleet_sim.fleet.price_inputs import DayPriceInputs, day_price_inputs
from fleet_sim.prices.config import load_config
from fleet_sim.prices.parameters import load_price_model

_ROOT = Path(__file__).parents[1]
_DAY = date(2024, 6, 15)


def _inputs(cache: Path, day: date = _DAY) -> DayPriceInputs:
    """``day`` in region C under the main model and the calibration fuel cost."""
    model = load_price_model(
        _ROOT / "calibration" / "price_curves.json", "fuel_adjusted/exponential"
    )
    config = load_config(_ROOT / "calibration" / "price_curves.toml")
    return day_price_inputs(day, "C", cache, model=model, fuel_cost=config.fuel_cost)


def test_no_added_load_gives_the_historical_rates(price_cache: Path) -> None:
    inputs = _inputs(price_cache)
    historical = HistoricalAgileSource(cache_dir=price_cache).load(_DAY, "C")

    prices = inputs.prices([0.0] * 48)

    assert prices.timestamps_utc == historical.timestamps_utc
    assert prices.price_p_per_kwh == pytest.approx(historical.price_p_per_kwh)


def test_the_price_never_falls_as_load_is_added(price_cache: Path) -> None:
    # b from −10 to +10 GW in 0.5 GW steps, the same in every slot. The
    # exponential's slope β·e^{γR} is positive and the day's rates are far
    # below the cap, so every slot must also rise strictly end to end.
    inputs = _inputs(price_cache)
    grid = [-10.0 + 0.5 * i for i in range(41)]
    rates = [inputs.prices([b] * 48).price_p_per_kwh for b in grid]

    for lower, higher in pairwise(rates):
        assert all(h >= lo for lo, h in zip(lower, higher, strict=True))
    assert all(h > lo for lo, h in zip(rates[0], rates[-1], strict=True))


def test_slots_outside_the_curve_range_are_counted(price_cache: Path) -> None:
    # R = 20 GW everywhere, range −0.5 to 42 GW. R + b is 42.0 (the edge,
    # inside), 42.1 (outside) and −0.6 (outside) in the last three slots,
    # 20 in the rest: two slots are out of range.
    inputs = _inputs(price_cache).model_copy(update={"residual_load_gw": [20.0] * 48})
    added = [0.0] * 45 + [22.0, 22.1, -20.6]

    assert inputs.out_of_range_slots(added, (-0.5, 42.0)) == 2


@pytest.mark.parametrize(
    ("day", "message"),
    [
        (date(2022, 11, 15), "2022-11-15 is in the Energy Price Guarantee"),
        (date(2024, 6, 16), "2024-06-16 has no residual load for 48 of 48 slots"),
    ],
)
def test_days_that_cannot_be_priced_fail(
    price_cache: Path, day: date, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _inputs(price_cache, day)
