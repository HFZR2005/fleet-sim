"""Means and 95% t-intervals over independent replications.

A replication is one pass over the scenario's date range, from its own
master seed. The seed is derived from the scenario seed, and the same
derived seed is used for every condition in that replication. See
``docs/experiments.md``.
"""

import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.stats import t

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.models.scenario import Scenario
from fleet_sim.progress import NullProgress, RunProgress
from fleet_sim.scenario import DayMetrics, collect_days

_LEVEL = 0.95
_METRICS = (
    "peak_demand_kw",
    "peak_demand_without_battery_kw",
    "peak_to_average_ratio",
    "coincidence_factor",
    "total_savings_pence",
    "savings_per_home_pence",
)
ComparisonName = Literal["with_batteries", "without_batteries", "diverse", "identical"]


class ConfidenceInterval(BaseModel):
    """A t-interval for the mean of independent replications.

    ``low`` and ``high`` are the ends of the interval at ``level``. With
    the usual 0.95, they are mean ± t * s / sqrt(R), and t is the 0.975
    quantile of a t distribution with R - 1 degrees of freedom.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: float
    mean: float
    low: float
    high: float
    replications: int


class MetricEstimate(BaseModel):
    """One metric of the scenario as it was written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    interval: ConfidenceInterval


class PairedDifference(BaseModel):
    """The interval for the mean of ``left - right``, paired by seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    left: ComparisonName
    right: ComparisonName
    interval: ConfidenceInterval


class ExperimentReport(BaseModel):
    """Replication means for the scenario, and the two paired comparisons.

    ``battery`` is with batteries minus without, in the scenario's mode.
    ``diversity`` is diverse minus identical, at the scenario's penetration.
    ``without_batteries`` is the penetration-0 pass in the scenario's mode.
    ``seeds[i]`` is the master seed of replication ``i``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    master_seed: int
    seeds: list[int]
    metrics: list[MetricEstimate]
    without_batteries: list[MetricEstimate]
    battery: list[PairedDifference]
    diversity: list[PairedDifference]


def replication_seed(master: int, index: int) -> int:
    """Master seed for replication ``index``, derived from ``master``.

    Replication 0 is not the scenario seed itself. Every replication,
    including the first, is a fresh seed, so none of them is a special case.
    """
    if isinstance(master, bool) or not isinstance(master, int):
        raise TypeError(f"master must be an int (got {master!r})")
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f"index must be an int (got {index!r})")
    if master < 0:
        raise ValueError(f"master must be at least 0 (got {master})")
    if index < 0:
        raise ValueError(f"index must be at least 0 (got {index})")
    word = np.random.SeedSequence([master, index]).generate_state(1, dtype=np.uint32)
    return int(word[0])


def t_interval(
    samples: Sequence[float], *, level: float = _LEVEL
) -> ConfidenceInterval:
    """Student's t-interval for the mean of ``samples``.

    The half-width is t * s / sqrt(R). s is the sample standard deviation
    with R - 1 in the divisor. t is the upper quantile of the t
    distribution on R - 1 degrees of freedom. See ``docs/experiments.md``.
    """
    if not 0 < level < 1:
        raise ValueError(f"level must be in (0, 1) (got {level})")
    count = len(samples)
    if count < 2:
        raise ValueError(f"a t-interval needs at least 2 samples (got {count})")
    mean = math.fsum(samples) / count
    variance = math.fsum((sample - mean) ** 2 for sample in samples) / (count - 1)
    half = float(t.ppf((1.0 + level) / 2.0, count - 1)) * math.sqrt(variance / count)
    return ConfidenceInterval(
        level=level,
        mean=mean,
        low=mean - half,
        high=mean + half,
        replications=count,
    )


def run_experiment(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    level: float = _LEVEL,
    progress: RunProgress | None = None,
) -> ExperimentReport:
    """Run ``scenario.replications`` paired passes and report t-intervals.

    Each replication's sample is the mean of that metric over the date
    range. Those means are the independent samples.
    """
    if scenario.replications < 2:
        raise ValueError(
            f"a t-interval needs at least 2 replications (got {scenario.replications})"
        )
    levels = scenario.penetration_levels()
    if len(levels) != 1:
        raise ValueError(
            "this experiment takes one penetration; "
            f"a sweep over {len(levels)} values is a later step"
        )
    penetration = levels[0]
    seeds = [
        replication_seed(scenario.seed, index) for index in range(scenario.replications)
    ]
    as_written: dict[str, list[float]] = {name: [] for name in _METRICS}
    with_battery: dict[str, list[float]] = {name: [] for name in _METRICS}
    without_battery: dict[str, list[float]] = {name: [] for name in _METRICS}
    diverse: dict[str, list[float]] = {name: [] for name in _METRICS}
    identical: dict[str, list[float]] = {name: [] for name in _METRICS}
    other_mode = "identical" if scenario.mode == "diverse" else "diverse"
    reporter = progress if progress is not None else NullProgress()
    n_days = (scenario.end - scenario.start).days + 1
    reporter.task("Solving", scenario.replications * 3 * n_days)
    for index, seed in enumerate(seeds, start=1):
        # Three passes share this seed. The battery comparison keeps the
        # scenario's mode and changes only penetration. The diversity
        # comparison keeps the penetration and changes only the mode.
        label = f"replication {index}/{scenario.replications}"
        written = _means(
            scenario,
            pool,
            price_source,
            seed,
            penetration,
            scenario.mode,
            reporter,
            f"{label}, {scenario.mode}",
        )
        other = _means(
            scenario,
            pool,
            price_source,
            seed,
            penetration,
            other_mode,
            reporter,
            f"{label}, {other_mode}",
        )
        no_battery = _means(
            scenario,
            pool,
            price_source,
            seed,
            0.0,
            scenario.mode,
            reporter,
            f"{label}, no battery",
        )
        for name in _METRICS:
            as_written[name].append(written[name])
            with_battery[name].append(written[name])
            without_battery[name].append(no_battery[name])
            if scenario.mode == "diverse":
                diverse[name].append(written[name])
                identical[name].append(other[name])
            else:
                diverse[name].append(other[name])
                identical[name].append(written[name])
    return ExperimentReport(
        master_seed=scenario.seed,
        seeds=seeds,
        metrics=[
            MetricEstimate(
                metric=name, interval=t_interval(as_written[name], level=level)
            )
            for name in _METRICS
        ],
        without_batteries=[
            MetricEstimate(
                metric=name, interval=t_interval(without_battery[name], level=level)
            )
            for name in _METRICS
        ],
        battery=[
            PairedDifference(
                metric=name,
                left="with_batteries",
                right="without_batteries",
                interval=t_interval(
                    [
                        left - right
                        for left, right in zip(
                            with_battery[name], without_battery[name], strict=True
                        )
                    ],
                    level=level,
                ),
            )
            for name in _METRICS
        ],
        diversity=[
            PairedDifference(
                metric=name,
                left="diverse",
                right="identical",
                interval=t_interval(
                    [
                        left - right
                        for left, right in zip(
                            diverse[name], identical[name], strict=True
                        )
                    ],
                    level=level,
                ),
            )
            for name in _METRICS
        ],
    )


def _means(
    scenario: Scenario,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    seed: int,
    penetration: float,
    mode: str,
    progress: RunProgress,
    label: str,
) -> dict[str, float]:
    days, _fallbacks, _frames = collect_days(
        scenario,
        pool=pool,
        price_source=price_source,
        seed=seed,
        penetration=penetration,
        mode=mode,
        progress=progress,
        label=label,
    )
    return {name: _mean_over_days(days, name) for name in _METRICS}


def _mean_over_days(days: list[DayMetrics], metric: str) -> float:
    values = [float(getattr(day.metrics, metric)) for day in days]
    return math.fsum(values) / len(values)
