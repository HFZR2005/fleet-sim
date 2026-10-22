"""What a scenario command returns to the report.

Both the diversity run and the network run build this. It lives here so
those commands can import it without importing each other.
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from fleet_sim.experiments.report import MetricEstimate, PairedDifference
from fleet_sim.experiments.sweep import LevelResult, PeakCrossing


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
