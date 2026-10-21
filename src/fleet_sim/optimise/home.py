"""Optimal schedule for one home.

Implements the mixed-integer linear program in ``docs/formulation.md``.
The horizon is the length of the demand series. A ``HomeDay`` has 48 slots.
The worked example in that note is the same program with a horizon of 2.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp

from fleet_sim.models.home import HomeDay
from fleet_sim.models.schedule import Schedule

# (DT) in docs/formulation.md. Energy in a slot is power times this factor.
SLOT_HOURS = 0.5

# Values inside the solver's feasibility noise. A residual past _VIOLATION
# is a failed solve.
_SNAP = 1e-6
_VIOLATION = 1e-5


@dataclass(frozen=True)
class _Variables:
    """Column order: charge, discharge, grid import, soc, charge mode."""

    n_slots: int

    @property
    def count(self) -> int:
        return 5 * self.n_slots

    def charge(self, slot: int) -> int:
        return slot

    def discharge(self, slot: int) -> int:
        return self.n_slots + slot

    def grid_import(self, slot: int) -> int:
        return 2 * self.n_slots + slot

    def soc(self, slot: int) -> int:
        return 3 * self.n_slots + slot

    def charge_mode(self, slot: int) -> int:
        return 4 * self.n_slots + slot


def optimise_home(day: HomeDay) -> Schedule:
    """Return the schedule that minimises (COST) in ``docs/formulation.md``.

    Constraints are (SOC), (SOC-BOUNDS), (POWER-BOUNDS), (BALANCE),
    (TERMINAL), and (MODE). ``Delta`` is 0.5 hours.
    """
    variables = _Variables(_horizon(day))
    result = milp(
        _objective(day, variables),
        integrality=_integrality(variables),
        bounds=_bounds(day, variables),
        constraints=[
            _soc_constraint(day, variables),
            _balance_constraint(day, variables),
            _terminal_constraint(day, variables),
            _mode_constraint(day, variables),
        ],
        # HiGHS otherwise stops at a relative gap of 1e-4, which can return a
        # feasible point whose bill is above the no-battery bill.
        options={"mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"home schedule is not optimal ({result.message})")
    return _schedule(day, variables, np.asarray(result.x, dtype=np.float64))


def _horizon(day: HomeDay) -> int:
    n_demand = len(day.demand_kw)
    n_prices = len(day.price_p_per_kwh)
    if n_demand != n_prices:
        raise ValueError(
            "demand_kw and price_p_per_kwh must have the same length "
            f"(got {n_demand} and {n_prices})"
        )
    if n_demand == 0:
        raise ValueError("demand_kw must contain at least one slot")
    return n_demand


def _objective(day: HomeDay, variables: _Variables) -> NDArray[np.float64]:
    """Coefficients of (COST) in ``docs/formulation.md``.

    The bill is ``sum(price_p_per_kwh[t] * grid_import_kw[t] * 0.5)``.
    Only grid import has a nonzero coefficient.
    """
    cost = np.zeros(variables.count, dtype=np.float64)
    for slot, price in enumerate(day.price_p_per_kwh):
        cost[variables.grid_import(slot)] = price * SLOT_HOURS
    return cost


def _integrality(variables: _Variables) -> NDArray[np.int64]:
    """Mark ``charge_mode`` integer, the ``y_t in {0, 1}`` part of (MODE)."""
    kinds = np.zeros(variables.count, dtype=np.int64)
    for slot in range(variables.n_slots):
        kinds[variables.charge_mode(slot)] = 1
    return kinds


def _bounds(day: HomeDay, variables: _Variables) -> Bounds:
    """Variable limits from (POWER-BOUNDS), (SOC-BOUNDS), and (MODE).

    ``grid_import_kw`` has no upper bound. ``charge_mode`` lies in [0, 1].
    (MODE) tightens the charge and discharge limits with that binary.
    """
    battery = day.battery
    lower = np.zeros(variables.count, dtype=np.float64)
    upper = np.full(variables.count, np.inf, dtype=np.float64)
    for slot in range(variables.n_slots):
        upper[variables.charge(slot)] = battery.max_charge_kw
        upper[variables.discharge(slot)] = battery.max_discharge_kw
        upper[variables.soc(slot)] = 1.0
        upper[variables.charge_mode(slot)] = 1.0
    return Bounds(lower, upper)


def _soc_constraint(day: HomeDay, variables: _Variables) -> LinearConstraint:
    """Equalities (SOC) in ``docs/formulation.md``.

    ``soc[t] = soc_prev + (eta_charge * charge_kw[t] * 0.5
    - discharge_kw[t] * 0.5 / eta_discharge) / capacity_kwh``.
    ``soc_prev`` is ``soc_initial`` when ``t == 0``, and ``soc[t - 1]``
    otherwise.
    """
    battery = day.battery
    stored_per_charge_kw = SLOT_HOURS * battery.eta_charge / battery.capacity_kwh
    released_per_discharge_kw = SLOT_HOURS / (
        battery.eta_discharge * battery.capacity_kwh
    )
    rows: list[list[float]] = []
    rhs: list[float] = []
    for slot in range(variables.n_slots):
        row = _zero_row(variables)
        row[variables.soc(slot)] = 1.0
        row[variables.charge(slot)] = -stored_per_charge_kw
        row[variables.discharge(slot)] = released_per_discharge_kw
        if slot == 0:
            rhs.append(battery.soc_initial)
        else:
            row[variables.soc(slot - 1)] = -1.0
            rhs.append(0.0)
        rows.append(row)
    return _equalities(rows, rhs)


def _balance_constraint(day: HomeDay, variables: _Variables) -> LinearConstraint:
    """Equalities (BALANCE) in ``docs/formulation.md``.

    ``grid_import_kw[t] + discharge_kw[t] = demand_kw[t] + charge_kw[t]``.
    """
    rows: list[list[float]] = []
    rhs: list[float] = []
    for slot, demand in enumerate(day.demand_kw):
        row = _zero_row(variables)
        row[variables.grid_import(slot)] = 1.0
        row[variables.discharge(slot)] = 1.0
        row[variables.charge(slot)] = -1.0
        rows.append(row)
        rhs.append(demand)
    return _equalities(rows, rhs)


def _terminal_constraint(day: HomeDay, variables: _Variables) -> LinearConstraint:
    """Equality (TERMINAL) in ``docs/formulation.md``.

    ``soc[T - 1] == soc_initial``.
    """
    row = _zero_row(variables)
    row[variables.soc(variables.n_slots - 1)] = 1.0
    return _equalities([row], [day.battery.soc_initial])


def _mode_constraint(day: HomeDay, variables: _Variables) -> LinearConstraint:
    """Inequalities (MODE) in ``docs/formulation.md``.

    ``charge_kw[t] <= max_charge_kw * charge_mode[t]`` and
    ``discharge_kw[t] <= max_discharge_kw * (1 - charge_mode[t])``.
    Mode 1 allows charging. Mode 0 allows discharging.
    """
    battery = day.battery
    rows: list[list[float]] = []
    upper: list[float] = []
    for slot in range(variables.n_slots):
        charge_row = _zero_row(variables)
        charge_row[variables.charge(slot)] = 1.0
        charge_row[variables.charge_mode(slot)] = -battery.max_charge_kw
        rows.append(charge_row)
        upper.append(0.0)

        discharge_row = _zero_row(variables)
        discharge_row[variables.discharge(slot)] = 1.0
        discharge_row[variables.charge_mode(slot)] = battery.max_discharge_kw
        rows.append(discharge_row)
        upper.append(battery.max_discharge_kw)
    lower = [float("-inf")] * len(upper)
    return LinearConstraint(np.asarray(rows, dtype=np.float64), lower, upper)


def _equalities(rows: list[list[float]], rhs: list[float]) -> LinearConstraint:
    matrix = np.asarray(rows, dtype=np.float64)
    return LinearConstraint(matrix, rhs, rhs)


def _zero_row(variables: _Variables) -> list[float]:
    return [0.0] * variables.count


def _schedule(
    day: HomeDay, variables: _Variables, solution: NDArray[np.float64]
) -> Schedule:
    charge: list[float] = []
    discharge: list[float] = []
    grid_import: list[float] = []
    soc: list[float] = []
    mode: list[int] = []
    for slot in range(variables.n_slots):
        charge.append(
            _nonnegative(float(solution[variables.charge(slot)]), "charge_kw", slot)
        )
        discharge.append(
            _nonnegative(
                float(solution[variables.discharge(slot)]), "discharge_kw", slot
            )
        )
        grid_import.append(
            _nonnegative(
                float(solution[variables.grid_import(slot)]), "grid_import_kw", slot
            )
        )
        soc.append(_state_of_charge(float(solution[variables.soc(slot)]), slot))
        mode.append(_charge_mode(float(solution[variables.charge_mode(slot)]), slot))
        if mode[slot] == 1 and discharge[slot] > 0.0:
            raise RuntimeError(f"slot {slot} charges and discharges (mode 1)")
        if mode[slot] == 0 and charge[slot] > 0.0:
            raise RuntimeError(f"slot {slot} charges and discharges (mode 0)")
    return Schedule(
        charge_kw=charge,
        discharge_kw=discharge,
        grid_import_kw=grid_import,
        soc=soc,
        charge_mode=mode,
        cost_pence=_import_cost_pence(day.price_p_per_kwh, grid_import),
    )


def _import_cost_pence(
    price_p_per_kwh: list[float], grid_import_kw: list[float]
) -> float:
    """(COST) in ``docs/formulation.md``, in pence.

    ``sum(price_p_per_kwh[t] * grid_import_kw[t] * 0.5)``.
    """
    return sum(
        price * imported * SLOT_HOURS
        for price, imported in zip(price_p_per_kwh, grid_import_kw, strict=True)
    )


def _nonnegative(value: float, name: str, slot: int) -> float:
    if value < -_VIOLATION:
        raise RuntimeError(f"{name}[{slot}] is negative ({value})")
    if value <= _SNAP:
        return 0.0
    return value


def _state_of_charge(value: float, slot: int) -> float:
    if value < -_VIOLATION or value > 1.0 + _VIOLATION:
        raise RuntimeError(f"soc[{slot}] is outside [0, 1] ({value})")
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _charge_mode(value: float, slot: int) -> int:
    if value < -_VIOLATION or value > 1.0 + _VIOLATION:
        raise RuntimeError(f"charge_mode[{slot}] is outside {{0, 1}} ({value})")
    if value >= 0.5:
        return 1
    return 0
