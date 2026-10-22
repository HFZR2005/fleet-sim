"""Numbers reduced from one or more solved days."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fleet_sim.models.demand import DemandFallback
from fleet_sim.models.fleet import FleetDay
from fleet_sim.models.scenario import RunMetadata

ComparisonName = Literal["with_batteries", "without_batteries", "diverse", "identical"]


class FleetMetrics(BaseModel):
    """Peak, shape, and savings for one solved day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    peak_demand_kw: float
    peak_slot: int
    peak_demand_without_battery_kw: float
    peak_slot_without_battery: int
    peak_to_average_ratio: float
    coincidence_factor: float
    total_savings_pence: float
    savings_per_home_pence: float


class DayMetrics(BaseModel):
    """One civil day's fleet measures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    metrics: FleetMetrics


class Spread(BaseModel):
    """Median and the lowest and highest value across the days."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    median: float
    minimum: float
    maximum: float


class DayReport(BaseModel):
    """One civil day's solve and its measures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    metrics: FleetMetrics
    solution: FleetDay


class FleetRange(BaseModel):
    """Per-day measures, plus the spread of each measure across the days."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    days: list[DayReport]
    peak_demand_kw: Spread
    peak_slot: Spread
    peak_demand_without_battery_kw: Spread
    peak_slot_without_battery: Spread
    peak_to_average_ratio: Spread
    coincidence_factor: Spread
    total_savings_pence: Spread
    savings_per_home_pence: Spread


class ComparisonReport(BaseModel):
    """How much of the optimiser's saving a simpler rule keeps.

    Savings are the no-battery bill minus that schedule's bill, in pence.
    ``rule_savings_share`` is the rule's saving divided by the optimiser's.
    A share of 1 means the rule matched the optimal bill. When the optimiser
    saves nothing, the share is 1 if the rule matches that bill and 0 if the
    rule costs more.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    no_battery_cost_pence: float
    rule_cost_pence: float
    optimiser_cost_pence: float
    rule_savings_share: float


class ScenarioResult(BaseModel):
    """The master-seed pass, and the trial days that had to fall back."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: RunMetadata
    days: list[DayMetrics]
    fallbacks: list[DemandFallback]


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


class ScenarioRun(BaseModel):
    """What ``run-scenario`` printed and where it wrote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_homes: int
    region: str
    start: date
    end: date
    replications: int
    mode: str
    penetration: float
    metrics: list[MetricEstimate]
    without_batteries: list[MetricEstimate]
    diversity: list[PairedDifference]
    battery: list[PairedDifference]
    levels: list[LevelResult]
    crossing: PeakCrossing | None
    frames_path: Path
    metadata_path: Path
    metrics_path: Path
    diversity_figure: Path | None = None
    penetration_figure: Path | None = None
    overload_figure: Path | None = None
    stubs: list[str] = Field(default_factory=list)
