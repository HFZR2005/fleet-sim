"""Replication means and t-intervals. See ``docs/experiments.md``."""

from fleet_sim.experiments.report import replication_seed, run_experiment, t_interval
from fleet_sim.experiments.sweep import first_crossing, run_penetration_sweep
from fleet_sim.models.results import (
    ConfidenceInterval,
    ExperimentReport,
    LevelResult,
    MetricEstimate,
    PairedDifference,
    PeakCrossing,
    PenetrationSweep,
)

__all__ = [
    "ConfidenceInterval",
    "ExperimentReport",
    "LevelResult",
    "MetricEstimate",
    "PairedDifference",
    "PeakCrossing",
    "PenetrationSweep",
    "first_crossing",
    "replication_seed",
    "run_experiment",
    "run_penetration_sweep",
    "t_interval",
]
