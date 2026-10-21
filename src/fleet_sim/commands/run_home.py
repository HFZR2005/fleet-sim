"""One home, one day: prices, both strategies, and the day figure."""

import tomllib
from datetime import date
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from fleet_sim.data.demand import HOURS_PER_SLOT, DemandProfile, FixedDemandProfile
from fleet_sim.data.source import PriceSource
from fleet_sim.models.comparison import ComparisonReport
from fleet_sim.models.home import SLOTS_PER_DAY, BatterySpec, HomeDay
from fleet_sim.optimise.home import optimise_home
from fleet_sim.optimise.rule import compare_cheapest_slots
from fleet_sim.viz.day import plot_day
from fleet_sim.viz.save import save_figure


class RunHomeConfig(BaseModel):
    """Battery, demand, and rule width for one ``run-home`` invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_id: str = "home"
    region: str = "C"
    transformer_id: str | None = None
    n: int
    battery: BatterySpec
    demand_kw: list[float]

    @field_validator("home_id", "region")
    @classmethod
    def identity_is_present(cls, value: str, info: ValidationInfo) -> str:
        if value == "":
            name = "value" if info.field_name is None else info.field_name
            raise ValueError(f"{name} must not be empty")
        return value

    @field_validator("n")
    @classmethod
    def n_is_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"n must be at least 0 (got {value})")
        return value

    @field_validator("demand_kw")
    @classmethod
    def demand_is_a_day_of_non_negative_power(cls, value: list[float]) -> list[float]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                f"demand_kw must contain {SLOTS_PER_DAY} half-hour values "
                f"(got {len(value)})"
            )
        for item in value:
            if item < 0:
                raise ValueError(
                    f"demand_kw must be at least 0 in every slot (got {item})"
                )
        return value


def load_run_home_config(path: Path) -> RunHomeConfig:
    """Read the home config. Raises ``FileNotFoundError`` if ``path`` is missing."""
    if not path.is_file():
        raise FileNotFoundError(f"home config not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"home config {path} is not valid TOML") from exc
    try:
        return RunHomeConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"home config {path} is invalid\n{exc}") from exc


def run_home(
    day: date,
    region: str,
    *,
    config_path: Path,
    output: Path,
    price_source: PriceSource,
    demand_profile: DemandProfile | None = None,
) -> tuple[ComparisonReport, int]:
    """Load ``day`` in ``region``, compare both strategies, and save the figure.

    Prices come from ``price_source``. Demand comes from ``demand_profile``,
    or from the config's kW list wrapped as a profile. The figure is the
    optimal schedule. ``grid_import_without_battery_kw`` is that demand, not
    a value derived while drawing.
    """
    config = load_run_home_config(config_path)
    prices = price_source.load(day, region)
    profile = (
        FixedDemandProfile(config.demand_kw)
        if demand_profile is None
        else demand_profile
    )
    demand_kw = [
        slot_kwh / HOURS_PER_SLOT for slot_kwh in profile.demand(day).demand_kwh
    ]
    home = HomeDay(
        home_id=config.home_id,
        region=config.region,
        transformer_id=config.transformer_id,
        battery=config.battery,
        demand_kw=demand_kw,
        price_p_per_kwh=prices.price_p_per_kwh,
    )
    report = compare_cheapest_slots(home, config.n)
    schedule = optimise_home(home)
    figure = plot_day(
        schedule,
        price_p_per_kwh=prices.price_p_per_kwh,
        grid_import_without_battery_kw=demand_kw,
    )
    save_figure(figure, output)
    return report, config.n
