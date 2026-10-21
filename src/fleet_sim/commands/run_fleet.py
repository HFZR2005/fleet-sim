"""A fleet of identical homes across a date range.

The command solves each day, writes one frame file, and saves the herding
figure and the daily-peak figure. It does not coordinate the homes.
"""

from datetime import date
from pathlib import Path

from fleet_sim.commands.run_home import load_run_home_config
from fleet_sim.data.source import PriceSource
from fleet_sim.fleet.frames import frames_for_day, write_frames
from fleet_sim.fleet.homes import Home, identical_homes
from fleet_sim.fleet.range import FleetRange, run_fleet_days
from fleet_sim.models.frames import Frame
from fleet_sim.viz.herding import plot_daily_peaks, plot_herding
from fleet_sim.viz.save import save_figure


def run_fleet(
    *,
    n_homes: int,
    start: date,
    end: date,
    region: str,
    config_path: Path,
    frames_path: Path,
    herding_output: Path,
    peaks_output: Path,
    price_source: PriceSource,
) -> tuple[FleetRange, date]:
    """Solve ``n_homes`` copies of the config from ``start`` through ``end``.

    The copies take ``region`` as their tariff region, which is the region
    the prices were loaded for. The herding figure is the day with the
    highest with-battery peak, and the earliest such day when several tie.
    Prices are loaded again to stamp each frame; a cached source does not
    fetch them a second time, and the days are not solved again.
    """
    config = load_run_home_config(config_path)
    homes = identical_homes(
        Home(
            home_id=config.home_id,
            region=region,
            transformer_id=config.transformer_id,
            battery=config.battery,
            demand_kw=config.demand_kw,
        ),
        n_homes,
    )
    report = run_fleet_days(
        homes,
        start=start,
        end=end,
        region=region,
        price_source=price_source,
    )
    by_day: list[tuple[date, list[Frame]]] = []
    for day_report in report.days:
        prices = price_source.load(day_report.day, region)
        by_day.append((day_report.day, frames_for_day(prices, day_report.solution)))
    frames = [frame for _day, day_frames in by_day for frame in day_frames]
    write_frames(frames_path, frames)
    herding_day = _herding_day(report)
    herding_frames = next(
        day_frames for day, day_frames in by_day if day == herding_day
    )
    save_figure(plot_herding(herding_frames), herding_output)
    save_figure(plot_daily_peaks(by_day), peaks_output)
    return report, herding_day


def _herding_day(report: FleetRange) -> date:
    chosen = min(
        report.days,
        key=lambda item: (-item.metrics.peak_demand_kw, item.day.toordinal()),
    )
    return chosen.day
