"""Optimal schedule for one home.

Solves the linear program in ``docs/formulation.md`` first. A slot that
charges and discharges together while its effective price is negative is
solved again with (MODE). The horizon is the length of the demand series.
A ``HomeDay`` has 48 slots. The worked examples use a shorter horizon.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp

from fleet_sim.models.home import HomeDay, Schedule

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


def optimise_home(
    day: HomeDay,
    price_adjustment_p_per_kwh: Sequence[float] | None = None,
) -> Schedule:
    """Return the schedule that minimises (COST) in ``docs/formulation.md``.

    (COST) is the sum of ``(p_t + a_t) * g_t * 0.5``. ``p_t`` is the import
    tariff. The first solve uses (SOC), (SOC-BOUNDS), (POWER-BOUNDS),
    (BALANCE), and (TERMINAL). ``Delta`` is 0.5 hours. ``E`` in (SOC) is
    ``capacity_kwh``.

    If any slot has both powers above ``_SNAP``, the home is solved again
    with (MODE). The linear program was priced at ``p_t + a_t``, which is
    what makes that cycle profitable. ``solver`` on the result says which
    solve was returned.

    ``price_adjustment_p_per_kwh`` is ``a_t`` in (COST). ``None`` is a zero
    adjustment, one value per slot. ``cost_pence`` on the result is the
    tariff bill, which equals (COST) when every adjustment is zero.
    """
    adjustment = _price_adjustment(day, price_adjustment_p_per_kwh)
    relaxed = _solve(day, adjustment, with_mode=False)
    if _same_slot_cycle(relaxed):
        return _solve(day, adjustment, with_mode=True)
    return relaxed


def _solve(day: HomeDay, adjustment: Sequence[float], *, with_mode: bool) -> Schedule:
    variables = _Variables(_horizon(day))
    constraints = [
        _soc_constraint(day, variables),
        _balance_constraint(day, variables),
        _terminal_constraint(day, variables),
    ]
    integrality = np.zeros(variables.count, dtype=np.int64)
    if with_mode:
        constraints.append(_mode_constraint(day, variables))
        integrality = _integrality(variables)
    result = milp(
        _objective(day, variables, adjustment),
        integrality=integrality,
        bounds=_bounds(day, variables),
        constraints=constraints,
        # HiGHS otherwise stops at a relative gap of 1e-4, which can return a
        # feasible point whose bill is above the no-battery bill.
        options={"mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"home schedule is not optimal ({result.message})")
    solved_by: Literal["lp", "milp"] = "milp" if with_mode else "lp"
    return _schedule(
        day,
        variables,
        np.asarray(result.x, dtype=np.float64),
        solver=solved_by,
    )


def _same_slot_cycle(schedule: Schedule) -> bool:
    """True when any slot charges and discharges past ``_SNAP``.

    The linear program that produced ``schedule`` was priced at ``p_t + a_t``.
    Both powers are profitable only when that effective price is negative, so
    the tariff alone would miss a cycle that an adjustment pays for.
    """
    return any(
        charge > _SNAP and discharge > _SNAP
        for charge, discharge in zip(
            schedule.charge_kw, schedule.discharge_kw, strict=True
        )
    )


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


def _price_adjustment(
    day: HomeDay, price_adjustment_p_per_kwh: Sequence[float] | None
) -> list[float]:
    """``a_t`` in (COST). ``None`` is a zero for every slot of ``day``."""
    n_slots = _horizon(day)
    if price_adjustment_p_per_kwh is None:
        return [0.0] * n_slots
    adjustment = list(price_adjustment_p_per_kwh)
    if len(adjustment) != n_slots:
        raise ValueError(
            "price_adjustment_p_per_kwh must have one value per slot "
            f"(got {len(adjustment)} for {n_slots} slots)"
        )
    return adjustment


def _objective(
    day: HomeDay, variables: _Variables, adjustment: Sequence[float]
) -> NDArray[np.float64]:
    """Coefficients of (COST) in ``docs/formulation.md``.

    Slot ``t`` prices grid import at
    ``(price_p_per_kwh[t] + adjustment[t]) * 0.5``. Only grid import has a
    nonzero coefficient. The tariff bill leaves ``adjustment`` out.
    """
    cost = np.zeros(variables.count, dtype=np.float64)
    for slot, price in enumerate(day.price_p_per_kwh):
        cost[variables.grid_import(slot)] = (price + adjustment[slot]) * SLOT_HOURS
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
    day: HomeDay,
    variables: _Variables,
    solution: NDArray[np.float64],
    *,
    solver: Literal["lp", "milp"],
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
        if solver == "lp":
            mode.append(1 if charge[slot] > _SNAP else 0)
        else:
            mode.append(
                _charge_mode(float(solution[variables.charge_mode(slot)]), slot)
            )
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
        solver=solver,
    )


def _import_cost_pence(
    price_p_per_kwh: list[float], grid_import_kw: list[float]
) -> float:
    """Tariff bill in pence.

    ``sum(price_p_per_kwh[t] * grid_import_kw[t] * 0.5)``. This equals (COST)
    in ``docs/formulation.md`` when every price adjustment is zero.
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
