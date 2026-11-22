"""Types for the fleet in the loop: the tariff depends on the fleet's load.

See ``docs/formulation.md``, Fleet in the loop, and ``docs/architecture.md``.
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from fleet_sim.models.fleet import SolvedHome
from fleet_sim.models.home import SLOTS_PER_DAY
from fleet_sim.models.prices import PriceSeries


class MarketSettings(BaseModel):
    """The ``[market]`` section of a scenario.

    ``national_batteries`` is M in (LOAD): one value, or a list for the
    sweep. ``price_model`` names a ``target/family`` in
    ``price_parameters_file``; whether that model exists is checked when it
    is loaded. ``segments`` is K in (SEGMENT).
    ``equilibrium_tolerance_p`` flags a run whose largest re-plan saving
    (CHECK) exceeds it, in pence per home per day. ``curve_range_gw`` is the
    range of R + b the curve was fitted on; slots outside it are counted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    national_batteries: float | list[float]
    price_model: str = "fuel_adjusted/exponential"
    price_parameters_file: Path = Path("calibration/price_curves.json")
    segments: int = 40
    equilibrium_tolerance_p: float = 1.0
    curve_range_gw: tuple[float, float] = (-0.5, 42.0)

    @field_validator("national_batteries", mode="before")
    @classmethod
    def batteries_are_non_negative(cls, value: object) -> float | list[float]:
        levels = value if isinstance(value, list) else [value]
        if len(levels) == 0:
            raise ValueError("national_batteries must contain at least one value")
        checked: list[float] = []
        for level in levels:
            if isinstance(level, bool) or not isinstance(level, int | float):
                raise TypeError(f"national_batteries must be a number (got {level!r})")
            if level < 0:
                raise ValueError(f"national_batteries must be at least 0 (got {level})")
            checked.append(float(level))
        if isinstance(value, list):
            return checked
        return checked[0]

    @field_validator("price_model")
    @classmethod
    def model_is_a_target_and_family(cls, value: str) -> str:
        target, slash, family = value.partition("/")
        if not slash or not target or not family or "/" in family:
            raise ValueError(f"price_model must be target/family (got {value!r})")
        return value

    @field_validator("segments")
    @classmethod
    def segments_are_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"segments must be at least 1 (got {value})")
        return value

    @field_validator("equilibrium_tolerance_p")
    @classmethod
    def tolerance_is_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError(
                f"equilibrium_tolerance_p must be at least 0 (got {value})"
            )
        return value

    @field_validator("curve_range_gw")
    @classmethod
    def range_runs_upward(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = value
        if not low < high:
            raise ValueError(f"curve_range_gw must have low < high (got {low}, {high})")
        return value

    def national_battery_levels(self) -> list[float]:
        """Every M this section names, as a list."""
        if isinstance(self.national_batteries, list):
            return list(self.national_batteries)
        return [self.national_batteries]


class EquilibriumDiagnostics(BaseModel):
    """How far one fleet-day's solve is from an exact equilibrium.

    See ``docs/formulation.md``, Computing it. ``linearisation_error_p_per_kwh``
    is max_t |P_t(b*_t) − σ_tk*|. ``mode_break_slots`` counts home-slots that
    charge and discharge together past 1e-6 kW. The re-plan savings are
    (CHECK), in pence, and ``exceeds_tolerance`` is set when the largest is
    above ``MarketSettings.equilibrium_tolerance_p``.
    ``replanned_load_difference_gw`` is max_t of |national load of the
    re-planned allocation − b*_t| (Open choices). ``out_of_range_slots``
    counts slots where R_t + b*_t leaves ``curve_range_gw``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    linearisation_error_p_per_kwh: float
    mode_break_slots: int
    max_replan_saving_p: float
    total_replan_saving_p: float
    exceeds_tolerance: bool
    replanned_load_difference_gw: float
    out_of_range_slots: int


class MarketDay(BaseModel):
    """One fleet-day solved in the loop.

    ``added_load_gw`` is b* per slot and ``prices`` is P(b*). ``joint`` and
    ``replanned`` are the two allocations of b* across homes (Open choices).
    Both list every home, so the network can evaluate either; a home without
    a battery is the same in both.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    added_load_gw: list[float]
    prices: PriceSeries
    joint: list[SolvedHome]
    replanned: list[SolvedHome]
    diagnostics: EquilibriumDiagnostics

    @field_validator("added_load_gw")
    @classmethod
    def load_covers_a_day(cls, value: list[float]) -> list[float]:
        if len(value) != SLOTS_PER_DAY:
            raise ValueError(
                f"added_load_gw must contain {SLOTS_PER_DAY} half-hour values "
                f"(got {len(value)})"
            )
        return value


class MarketMetrics(BaseModel):
    """National and bill measures for one replication's days in the loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    peak_added_load_gw: float
    peak_added_load_hour: int
    saving_per_battery_home_p_per_day: float
    non_battery_price_change_p_per_day: float
    mean_charge_price_p_per_kwh: float
    mean_discharge_price_p_per_kwh: float
