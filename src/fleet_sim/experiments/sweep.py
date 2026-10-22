"""Peak, shape, and coincidence across a grid of battery penetrations.

One penetration is ``run_experiment``. This walks the list in a scenario
such as ``scenarios/penetration-sweep.toml``.
"""

from pydantic import BaseModel, ConfigDict

from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.data.source import PriceSource
from fleet_sim.experiments.report import (
    ConfidenceInterval,
    MetricEstimate,
    replication_seed,
    t_interval,
)
from fleet_sim.experiments.report import _means as _replication_means
from fleet_sim.models.scenario import Scenario

# A watt. Solver dust below this does not count as the battery peak exceeding
# the no-battery peak.
_EXCEED_KW = 1e-3
_LEVEL = 0.95
_METRICS = (
    "peak_demand_kw",
    "peak_to_average_ratio",
    "coincidence_factor",
)
_NO_BATTERY_PEAK = "peak_demand_without_battery_kw"


class LevelResult(BaseModel):
    """Intervals for one penetration, over the replications."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    penetration: float
    metrics: list[MetricEstimate]
    peak_without_battery: ConfidenceInterval
    peak_minus_no_battery: ConfidenceInterval


class PeakCrossing(BaseModel):
    """Where the with-battery peak first rises above the no-battery peak.

    ``per_replication`` is that penetration for each replication, or ``None``
    when that replication never crosses. ``lowest`` and ``highest`` are the
    range of the replications that do. ``interval_above_zero_from`` is the
    first grid level whose 95% interval for the peak difference lies wholly
    above zero.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    per_replication: list[float | None]
    lowest: float | None
    highest: float | None
    interval_above_zero_from: float | None


class PenetrationSweep(BaseModel):
    """The penetration grid, and the crossing of the no-battery peak."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    master_seed: int
    seeds: list[int]
    levels: list[LevelResult]
    crossing: PeakCrossing


def first_crossing(
    levels: list[float], peaks_kw: list[float], no_battery_peak_kw: float
) -> float | None:
    """The first ``levels`` entry whose peak exceeds ``no_battery_peak_kw``."""
    if len(levels) != len(peaks_kw):
        raise ValueError(
            f"levels and peaks must match (got {len(levels)} and {len(peaks_kw)})"
        )
    for level, peak in zip(levels, peaks_kw, strict=True):
        if peak > no_battery_peak_kw + _EXCEED_KW:
            return level
    return None


def run_penetration_sweep(
    scenario: Scenario,
    *,
    pool: HouseholdDemandPool,
    price_source: PriceSource,
    level: float = _LEVEL,
) -> PenetrationSweep:
    """Run every penetration in ``scenario`` for ``scenario.replications`` seeds.

    Each sample is the mean of that metric over the date range. The fleet
    mode is the scenario's. The no-battery peak is the peak of summed demand
    on that same run.
    """
    if scenario.replications < 2:
        raise ValueError(
            f"a t-interval needs at least 2 replications (got {scenario.replications})"
        )
    penetrations = scenario.penetration_levels()
    seeds = [
        replication_seed(scenario.seed, index) for index in range(scenario.replications)
    ]
    # samples[penetration][metric][replication]
    samples: dict[float, dict[str, list[float]]] = {
        penetration: {name: [] for name in (*_METRICS, _NO_BATTERY_PEAK)}
        for penetration in penetrations
    }
    for seed in seeds:
        for penetration in penetrations:
            means = _replication_means(
                scenario,
                pool,
                price_source,
                seed,
                penetration,
                scenario.mode,
            )
            for name in samples[penetration]:
                samples[penetration][name].append(means[name])
    levels = [
        _level_result(penetration, samples[penetration], level)
        for penetration in penetrations
    ]
    crossing = _crossing(penetrations, samples, levels)
    return PenetrationSweep(
        master_seed=scenario.seed,
        seeds=seeds,
        levels=levels,
        crossing=crossing,
    )


def _level_result(
    penetration: float, samples: dict[str, list[float]], level: float
) -> LevelResult:
    difference = [
        with_battery - without
        for with_battery, without in zip(
            samples["peak_demand_kw"], samples[_NO_BATTERY_PEAK], strict=True
        )
    ]
    return LevelResult(
        penetration=penetration,
        metrics=[
            MetricEstimate(metric=name, interval=t_interval(samples[name], level=level))
            for name in _METRICS
        ],
        peak_without_battery=t_interval(samples[_NO_BATTERY_PEAK], level=level),
        peak_minus_no_battery=t_interval(difference, level=level),
    )


def _crossing(
    penetrations: list[float],
    samples: dict[float, dict[str, list[float]]],
    levels: list[LevelResult],
) -> PeakCrossing:
    count = len(samples[penetrations[0]]["peak_demand_kw"])
    per_replication: list[float | None] = []
    for index in range(count):
        peaks = [
            samples[penetration]["peak_demand_kw"][index]
            for penetration in penetrations
        ]
        # Demand does not depend on penetration, so the no-battery peak is
        # the same at every level for this seed. The first level is enough.
        no_battery = samples[penetrations[0]][_NO_BATTERY_PEAK][index]
        per_replication.append(first_crossing(penetrations, peaks, no_battery))
    crossed = [level for level in per_replication if level is not None]
    above = next(
        (
            result.penetration
            for result in levels
            if result.peak_minus_no_battery.low > 0
        ),
        None,
    )
    return PeakCrossing(
        per_replication=per_replication,
        lowest=min(crossed) if crossed else None,
        highest=max(crossed) if crossed else None,
        interval_above_zero_from=above,
    )
