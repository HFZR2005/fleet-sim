"""Progress reports name the unit in progress and count the finished ones."""

import io
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import FixturePriceSource
from fleet_sim.experiments import run_experiment
from fleet_sim.fleet import Home, identical_homes, run_fleet_days
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.progress import RunProgress
from fleet_sim.render.progress import ConsoleProgress
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_DAY = date(2024, 6, 15)


class _Recording:
    def __init__(self) -> None:
        self.tasks: list[tuple[str, int | None]] = []
        self.details: list[str] = []
        self.advances = 0

    def task(self, description: str, total: int | None) -> None:
        self.tasks.append((description, total))

    def detail(self, text: str) -> None:
        self.details.append(text)

    def advance(self) -> None:
        self.advances += 1

    def close(self) -> None:
        return None


def test_an_experiment_reports_each_pass(tmp_path: Path) -> None:
    progress = _Recording()

    run_experiment(
        _scenario(tmp_path),
        pool=HouseholdDemandPool.read(_FIXTURE),
        price_source=_prices(),
        progress=progress,
    )

    assert progress.tasks == [("Solving", 6)]
    assert progress.advances == 6
    assert any(
        detail.startswith("replication 1/2, diverse") for detail in progress.details
    )
    assert any(
        detail.startswith("replication 2/2, no battery") for detail in progress.details
    )


def test_reading_households_counts_each_one() -> None:
    progress = _Recording()

    pool = HouseholdDemandPool.read(_FIXTURE, max_households=1, progress=progress)

    assert pool.household_ids() == ["MAC000002"]
    assert progress.tasks == [("Reading households", 1)]
    assert progress.details == ["household 1/1 MAC000002"]
    assert progress.advances == 1


def test_a_fleet_reports_each_day() -> None:
    progress = _Recording()
    home = Home(
        home_id="home",
        region="C",
        battery=None,
        demand_kw=[1.0] * 48,
    )

    run_fleet_days(
        identical_homes(home, 1),
        start=_DAY,
        end=_DAY,
        region="C",
        price_source=_prices(),
        progress=progress,
    )

    assert progress.tasks == [("Days", 1)]
    assert progress.details == [_DAY.isoformat()]
    assert progress.advances == 1


def test_a_plain_console_prints_each_unit_and_the_elapsed_time() -> None:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, highlight=False)
    progress: RunProgress = ConsoleProgress(console)

    progress.task("Solving", 2)
    progress.detail("replication 1/2, diverse, 2024-06-15")
    progress.advance()
    progress.close()

    text = buffer.getvalue()
    assert "Solving" in text
    assert "replication 1/2, diverse, 2024-06-15" in text
    assert "finished in" in text


def _prices() -> FixturePriceSource:
    start, _end = london_day_bounds_utc(_DAY)
    return FixturePriceSource(
        PriceSeries(
            region="C",
            day=_DAY,
            timestamps_utc=[
                start + timedelta(minutes=30) * index for index in range(48)
            ],
            price_p_per_kwh=[10.0] * 48,
        )
    )


def _scenario(directory: Path):
    text = (_ROOT / "scenarios" / "diverse.toml").read_text(encoding="utf-8")
    battery = text.split("[battery]", 1)[1]
    path = directory / "scenario.toml"
    path.write_text(
        "n_homes = 2\n"
        "penetration = 0.0\n"
        'mode = "diverse"\n'
        'region = "C"\n'
        f"start = {_DAY.isoformat()}\n"
        f"end = {_DAY.isoformat()}\n"
        "seed = 5\n"
        "replications = 2\n"
        "[battery]"
        f"{battery}",
        encoding="utf-8",
    )
    return load_scenario(path)
