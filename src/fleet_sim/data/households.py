"""Half-hourly demand from the Low Carbon London household trial.

The official file is cached under ``.cache/lcl`` and is not part of the
repository. Tests read a small extract of that file.
"""

from __future__ import annotations

import csv
import subprocess
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from fleet_sim.data.demand import elexon_season
from fleet_sim.models.demand import (
    DemandFallback,
    DemandSeries,
    ElexonSeason,
    HouseholdLoad,
)
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.progress import RunProgress
from fleet_sim.random_streams import RandomStreams

_CACHE_DIR = Path(".cache") / "lcl"
_CACHE_NAME = "household_days.csv"
_HALF_HOUR = timedelta(minutes=30)
_COMMON_YEAR = 2001


class HouseholdDemandPool:
    """Complete household-days, keyed by household, season, and day type.

    A day type is a weekday or a weekend. Each home in a run is given one
    household for the whole run, drawn without replacement from the
    ``demand`` stream.
    """

    def __init__(self, days: list[_TrialDay]) -> None:
        if not days:
            raise ValueError("the household pool must contain at least one day")
        self._by_household: dict[str, list[_TrialDay]] = {}
        for trial_day in days:
            self._by_household.setdefault(trial_day.household_id, []).append(trial_day)
        for household_days in self._by_household.values():
            household_days.sort(key=lambda item: item.day)

    @classmethod
    def read(
        cls,
        path: Path,
        *,
        max_households: int | None = None,
        progress: RunProgress | None = None,
    ) -> HouseholdDemandPool:
        """Read complete days from an official Low Carbon London CSV or zip.

        ``max_households`` keeps that many households and then stops. The
        published file is ordered by household id, so this is the first
        households in the file, not a random sample.
        """
        if max_households is not None:
            if isinstance(max_households, bool) or not isinstance(max_households, int):
                raise TypeError(
                    f"max_households must be an int (got {max_households!r})"
                )
            if max_households < 1:
                raise ValueError(
                    f"max_households must be at least 1 (got {max_households})"
                )
        days: list[_TrialDay] = []
        seen: set[str] = set()
        if progress is not None:
            progress.task("Reading households", max_households)
        for trial_day in _all_days(path):
            if trial_day.household_id not in seen:
                if max_households is not None and len(seen) >= max_households:
                    break
                if seen and progress is not None:
                    progress.advance()
                seen.add(trial_day.household_id)
                if progress is not None:
                    progress.detail(
                        _household_detail(
                            len(seen), max_households, trial_day.household_id
                        )
                    )
            days.append(trial_day)
        if progress is not None and seen:
            progress.advance()
        return cls(days)

    def household_ids(self) -> list[str]:
        """Household identifiers, in a stable order."""
        return sorted(self._by_household)

    def assign(self, n_homes: int, streams: RandomStreams) -> list[str]:
        """Give each home one household, drawn without replacement.

        The draw uses the ``demand`` stream. The same seed assigns the same
        households. A fleet larger than the pool is rejected.
        """
        if isinstance(n_homes, bool) or not isinstance(n_homes, int):
            raise TypeError(f"n_homes must be an int (got {n_homes!r})")
        if n_homes < 1:
            raise ValueError(f"n_homes must be at least 1 (got {n_homes})")
        ids = self.household_ids()
        if n_homes > len(ids):
            raise ValueError(
                f"a fleet of {n_homes} homes needs {n_homes} households, "
                f"and the pool has {len(ids)}"
            )
        generator = streams.generator("demand")
        picked = generator.choice(len(ids), size=n_homes, replace=False)
        return [ids[int(index)] for index in np.asarray(picked).reshape(-1)]

    def load(self, household_id: str, day: date) -> HouseholdLoad:
        """Demand for ``day`` from ``household_id``'s matching trial day.

        The match is the household's day with the same Elexon season and the
        same weekday-or-weekend type, choosing the trial day whose position
        in the year is closest to ``day``. If that household has no such day,
        the closest trial day is used and the result records the fallback.
        """
        household_days = self._by_household.get(household_id)
        if household_days is None:
            raise ValueError(f"household {household_id} is not in the pool")
        season = elexon_season(day)
        weekend = _is_weekend(day)
        matched = [
            trial_day
            for trial_day in household_days
            if trial_day.season == season and trial_day.weekend is weekend
        ]
        if matched:
            trial_day = _nearest(day, matched)
            fallback = None
        else:
            trial_day = _nearest(day, household_days)
            fallback = DemandFallback(
                household_id=household_id,
                simulated_day=day,
                trial_day=trial_day.day,
                wanted_season=season,
                wanted_weekend=weekend,
            )
        return HouseholdLoad(
            series=DemandSeries(day=day, demand_kwh=list(trial_day.demand_kwh)),
            household_id=household_id,
            trial_day=trial_day.day,
            fallback=fallback,
        )


class _TrialDay:
    """One complete trial day. Not part of the public boundary."""

    def __init__(
        self,
        household_id: str,
        day: date,
        season: ElexonSeason,
        weekend: bool,
        demand_kwh: tuple[float, ...],
    ) -> None:
        self.household_id = household_id
        self.day = day
        self.season = season
        self.weekend = weekend
        self.demand_kwh = demand_kwh


def ingest_low_carbon_london(source: Path, *, cache_dir: Path | None = None) -> Path:
    """Copy complete household-days from ``source`` into the local cache.

    ``source`` is the official CSV, a zip that contains it, or a directory of
    the partitioned CSVs. The cache is ``.cache/lcl`` unless ``cache_dir`` is
    set. The official download is not written into the repository.
    """
    directory = _CACHE_DIR if cache_dir is None else cache_dir
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / _CACHE_NAME
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["household_id", "day", *[f"kwh_{slot}" for slot in range(SLOTS_PER_DAY)]]
        )
        for trial_day in _all_days(source):
            writer.writerow(
                [
                    trial_day.household_id,
                    trial_day.day.isoformat(),
                    *trial_day.demand_kwh,
                ]
            )
    return target


def _household_detail(index: int, total: int | None, household_id: str) -> str:
    if total is None:
        return f"household {index} {household_id}"
    return f"household {index}/{total} {household_id}"


def _all_days(path: Path) -> Iterator[_TrialDay]:
    if path.is_dir():
        files = sorted(item for item in path.iterdir() if item.suffix == ".csv")
        if not files:
            raise ValueError(f"{path} contains no CSV files")
        for csv_path in files:
            yield from _days_from_text(_text_lines(csv_path))
        return
    if path.suffix == ".zip":
        yield from _days_from_zip(path)
        return
    yield from _days_from_text(_text_lines(path))


def _days_from_zip(path: Path) -> Iterator[_TrialDay]:
    """Read every CSV in ``path``.

    The London Datastore zip uses Deflate64, which the standard library
    cannot inflate. That archive is streamed through ``unzip`` instead.
    """
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.endswith(".csv"))
        if not names:
            raise ValueError(f"{path} contains no CSV files")
        try:
            first = archive.open(names[0])
        except NotImplementedError:
            names_for_unzip = names
        else:
            with first:
                yield from _days_from_text(line.decode("utf-8") for line in first)
            for name in names[1:]:
                with archive.open(name) as handle:
                    yield from _days_from_text(line.decode("utf-8") for line in handle)
            return
    for name in names_for_unzip:
        yield from _days_from_text(_unzip_lines(path, name))


def _unzip_lines(path: Path, name: str) -> Iterator[str]:
    process = subprocess.Popen(
        ["unzip", "-p", str(path), name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    stdout = process.stdout
    if stdout is None:
        raise ValueError(f"could not read {name} from {path}")
    try:
        yield from stdout
    finally:
        stdout.close()
        code = process.wait()
    # 141 and -13 are SIGPIPE, which is what unzip gets when a caller stops
    # before the end of the archive.
    if code not in (0, 141, -13):
        raise ValueError(f"could not read {name} from {path} (unzip exited {code})")


def _days_from_text(lines: Iterator[str]) -> Iterator[_TrialDay]:
    stripped = _stripped(lines)
    try:
        header = next(stripped)
    except StopIteration as exc:
        raise ValueError("Low Carbon London file has no header") from exc
    names = [name.strip().lower() for name in next(csv.reader([header]))]
    body = _prepend(header, stripped)
    if "household_id" in names and "kwh_0" in names:
        yield from _cache_days(body)
        return
    yield from _complete_days(body)


def _prepend(header: str, rest: Iterator[str]) -> Iterator[str]:
    yield header
    yield from rest


def _cache_days(lines: Iterator[str]) -> Iterator[_TrialDay]:
    reader = csv.DictReader(lines)
    for row in reader:
        day = date.fromisoformat(row["day"])
        demand = tuple(float(row[f"kwh_{slot}"]) for slot in range(SLOTS_PER_DAY))
        yield _TrialDay(
            row["household_id"],
            day,
            elexon_season(day),
            _is_weekend(day),
            demand,
        )


def _text_lines(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        yield from handle


def _complete_days(lines: Iterator[str]) -> Iterator[_TrialDay]:
    reader = csv.DictReader(_stripped(lines))
    if reader.fieldnames is None:
        raise ValueError("Low Carbon London file has no header")
    columns = {_normalise(name): name for name in reader.fieldnames}
    household_column = columns.get("lclid")
    stamp_column = columns.get("datetime")
    energy_column = next(
        (original for key, original in columns.items() if key.startswith("kwh/hh")),
        None,
    )
    if household_column is None or stamp_column is None or energy_column is None:
        raise ValueError(
            "Low Carbon London file must have LCLid, DateTime, and KWH/hh columns"
        )
    current_id = ""
    current_day: date | None = None
    slots: dict[int, float] = {}
    invalid = False
    for row in reader:
        household_id = row[household_column].strip()
        if household_id == "":
            continue
        slot_start = _slot_start(row[stamp_column])
        day = slot_start.date()
        if household_id != current_id or day != current_day:
            if current_day is not None and current_id != "":
                finished = _finish(current_id, current_day, slots, invalid)
                if finished is not None:
                    yield finished
            current_id = household_id
            current_day = day
            slots = {}
            invalid = False
        index = slot_start.hour * 2 + slot_start.minute // 30
        energy = _energy(row[energy_column])
        if energy is None or not 0 <= index < SLOTS_PER_DAY or index in slots:
            invalid = True
        else:
            slots[index] = energy
    if current_day is not None and current_id != "":
        finished = _finish(current_id, current_day, slots, invalid)
        if finished is not None:
            yield finished


def _stripped(lines: Iterator[str]) -> Iterator[str]:
    for line in lines:
        stripped = line.strip()
        if stripped:
            yield stripped


def _finish(
    household_id: str, day: date, slots: dict[int, float], invalid: bool
) -> _TrialDay | None:
    if invalid or len(slots) != SLOTS_PER_DAY:
        return None
    demand = tuple(slots[index] for index in range(SLOTS_PER_DAY))
    return _TrialDay(
        household_id,
        day,
        elexon_season(day),
        _is_weekend(day),
        demand,
    )


def _slot_start(value: str) -> datetime:
    """The half hour that ends at ``value``.

    The published timestamp is the end of the half hour, in UK civil time
    with no timezone. Subtracting 30 minutes gives the slot start, and the
    civil date of that start is the day the energy belongs to.
    """
    text = value.strip()
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        stamp = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(
            f"DateTime {value!r} is not a Low Carbon London stamp"
        ) from exc
    return stamp - _HALF_HOUR


def _energy(value: str) -> float | None:
    text = value.strip()
    if text == "" or text.lower() == "null":
        return None
    try:
        energy = float(text)
    except ValueError as exc:
        raise ValueError(f"KWH/hh {value!r} is not a number") from exc
    if energy < 0:
        return None
    return energy


def _nearest(day: date, choices: list[_TrialDay]) -> _TrialDay:
    weekend = _is_weekend(day)
    return min(
        choices,
        key=lambda trial_day: (
            _year_distance(day, trial_day.day),
            trial_day.weekend is not weekend,
            trial_day.day.toordinal(),
        ),
    )


def _year_distance(left: date, right: date) -> int:
    """Circular distance between two dates, ignoring the year."""
    gap = abs(_common_ordinal(left) - _common_ordinal(right))
    return min(gap, 365 - gap)


def _common_ordinal(day: date) -> int:
    month = day.month
    day_number = day.day
    if month == 2 and day_number == 29:
        day_number = 28
    return date(_COMMON_YEAR, month, day_number).toordinal()


def _is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def _normalise(name: str) -> str:
    return name.strip().lower()
