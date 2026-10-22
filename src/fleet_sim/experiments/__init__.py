"""Replication means and t-intervals. See ``docs/experiments.md``."""

from fleet_sim.experiments.report import (
    ConfidenceInterval,
    ExperimentReport,
    MetricEstimate,
    PairedDifference,
    replication_seed,
    run_experiment,
    t_interval,
)

__all__ = [
    "ConfidenceInterval",
    "ExperimentReport",
    "MetricEstimate",
    "PairedDifference",
    "replication_seed",
    "run_experiment",
    "t_interval",
]
