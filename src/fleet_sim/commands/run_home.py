"""One home, one day: prices, both strategies, and the day figure."""

import tomllib
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from fleet_sim.data.demand import HOURS_PER_SLOT, DemandProfile, FixedDemandProfile
from fleet_sim.data.source import PriceSource
from fleet_sim.models.home import HomeDay
from fleet_sim.models.results import ComparisonReport
from fleet_sim.models.scenario import RunHomeConfig
from fleet_sim.optimise.home import optimise_home
from fleet_sim.optimise.rule import compare_cheapest_slots
from fleet_sim.viz.day import plot_day
from fleet_sim.viz.save import save_figure


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
