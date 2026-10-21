"""Charge the cheapest slots and discharge the dearest.

The schedule stays inside the one-home constraints in ``docs/formulation.md``:
(SOC), (SOC-BOUNDS), (POWER-BOUNDS), (BALANCE), (TERMINAL), and (MODE).
"""

from fleet_sim.models.comparison import ComparisonReport
from fleet_sim.models.home import BatterySpec, HomeDay
from fleet_sim.models.schedule import Schedule
from fleet_sim.optimise.home import SLOT_HOURS, optimise_home

# Bills within this many pence are the same saving. Flat prices make the
# optimiser's saving zero, and the share would otherwise divide by zero.
_SAVINGS_TOLERANCE_PENCE = 1e-6


def charge_cheapest_slots(day: HomeDay, n: int) -> Schedule:
    """Charge the ``n`` cheapest slots and discharge the ``n`` dearest.

    Ties break towards an earlier slot being cheaper and a later slot being
    dearer. A slot that falls in both groups is left idle: (MODE) allows
    charge or discharge, not both. In a chosen slot the power is as large as
    the inverter limit, the state-of-charge bounds, the no-export limit, and
    (TERMINAL) allow. The day is walked in time order.
    """
    count = _require_count(n)
    horizon = _horizon(day)
    charge_at, discharge_at = _slot_roles(day.price_p_per_kwh, count)
    battery = day.battery
    charge_room = _future_charge_kwh(day, charge_at)
    discharge_room = _future_discharge_kwh(day, discharge_at)

    charge_kw = [0.0] * horizon
    discharge_kw = [0.0] * horizon
    mode = [0] * horizon
    soc = battery.soc_initial
    soc_end: list[float] = []
    for slot in range(horizon):
        if slot in charge_at:
            charge_kw[slot] = _charge_kw(battery, soc, discharge_room[slot + 1])
            if charge_kw[slot] > 0.0:
                mode[slot] = 1
        elif slot in discharge_at:
            discharge_kw[slot] = _discharge_kw(
                battery,
                soc,
                day.demand_kw[slot],
                charge_room[slot + 1],
            )
        soc = _next_soc(battery, soc, charge_kw[slot], discharge_kw[slot])
        soc_end.append(soc)

    if abs(soc - battery.soc_initial) > 1e-6:
        raise RuntimeError(
            "cheapest-slot rule finished at state of charge "
            f"{soc}, not {battery.soc_initial}"
        )
    grid_import_kw = [
        day.demand_kw[slot] + charge_kw[slot] - discharge_kw[slot]
        for slot in range(horizon)
    ]
    return Schedule(
        charge_kw=charge_kw,
        discharge_kw=discharge_kw,
        grid_import_kw=grid_import_kw,
        soc=soc_end,
        charge_mode=mode,
        cost_pence=_bill_pence(day.price_p_per_kwh, grid_import_kw),
    )


def compare_cheapest_slots(day: HomeDay, n: int) -> ComparisonReport:
    """Bill the day with no battery, with the cheapest-slot rule, and optimally.

    ``rule_savings_share`` is the fraction of (COST) saved by the optimiser
    that the rule also saves. See ``ComparisonReport``.
    """
    rule = charge_cheapest_slots(day, n)
    optimal = optimise_home(day)
    no_battery = _bill_pence(day.price_p_per_kwh, day.demand_kw)
    return ComparisonReport(
        no_battery_cost_pence=no_battery,
        rule_cost_pence=rule.cost_pence,
        optimiser_cost_pence=optimal.cost_pence,
        rule_savings_share=_savings_share(
            no_battery, rule.cost_pence, optimal.cost_pence
        ),
    )


def _require_count(n: int) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int (got {n!r})")
    if n < 0:
        raise ValueError(f"n must be at least 0 (got {n})")
    return n


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


def _slot_roles(prices: list[float], n: int) -> tuple[set[int], set[int]]:
    cheapest = sorted(range(len(prices)), key=lambda slot: (prices[slot], slot))
    dearest = sorted(range(len(prices)), key=lambda slot: (-prices[slot], -slot))
    charge_at = set(cheapest[:n])
    discharge_at = set(dearest[:n])
    both = charge_at & discharge_at
    return charge_at - both, discharge_at - both


def _future_charge_kwh(day: HomeDay, charge_at: set[int]) -> list[float]:
    """Store energy, in kWh, that later charge slots can still add."""
    battery = day.battery
    per_slot = battery.eta_charge * battery.max_charge_kw * SLOT_HOURS
    room = [0.0] * (len(day.demand_kw) + 1)
    for slot in range(len(day.demand_kw) - 1, -1, -1):
        room[slot] = room[slot + 1]
        if slot in charge_at:
            room[slot] += per_slot
    return room


def _future_discharge_kwh(day: HomeDay, discharge_at: set[int]) -> list[float]:
    """Store energy, in kWh, that later discharge slots can still remove.

    (POWER-BOUNDS) and (BALANCE) give ``discharge_kw <= demand_kw`` when the
    slot is not charging, because export is not allowed.
    """
    battery = day.battery
    room = [0.0] * (len(day.demand_kw) + 1)
    for slot in range(len(day.demand_kw) - 1, -1, -1):
        room[slot] = room[slot + 1]
        if slot in discharge_at:
            power_kw = min(battery.max_discharge_kw, day.demand_kw[slot])
            room[slot] += power_kw * SLOT_HOURS / battery.eta_discharge
    return room


def _charge_kw(battery: BatterySpec, soc: float, later_discharge_kwh: float) -> float:
    """Charge power that keeps (SOC-BOUNDS) and (TERMINAL) feasible.

    Energy added to the store is ``eta_charge * charge_kw * 0.5``. It cannot
    exceed the empty headroom, or the energy later discharge slots can remove
    on top of any stored energy already above ``soc_initial``.
    """
    surplus_kwh = (soc - battery.soc_initial) * battery.capacity_kwh
    room_kwh = later_discharge_kwh - surplus_kwh
    if room_kwh <= 0.0:
        return 0.0
    per_kw = battery.eta_charge * SLOT_HOURS
    headroom_kw = (1.0 - soc) * battery.capacity_kwh / per_kw
    terminal_kw = room_kwh / per_kw
    return max(0.0, min(battery.max_charge_kw, headroom_kw, terminal_kw))


def _discharge_kw(
    battery: BatterySpec,
    soc: float,
    demand_kw: float,
    later_charge_kwh: float,
) -> float:
    """Discharge power that keeps (SOC-BOUNDS), (POWER-BOUNDS), and (TERMINAL).

    ``discharge_kw <= demand_kw`` is the no-export limit. Energy removed from
    the store is ``discharge_kw * 0.5 / eta_discharge``. Later charge slots
    must be able to put that energy back.
    """
    surplus_kwh = (soc - battery.soc_initial) * battery.capacity_kwh
    removable_kwh = surplus_kwh + later_charge_kwh
    if removable_kwh <= 0.0:
        return 0.0
    stored_per_kw = SLOT_HOURS / battery.eta_discharge
    available_kw = soc * battery.capacity_kwh / stored_per_kw
    terminal_kw = removable_kwh / stored_per_kw
    power_kw = min(battery.max_discharge_kw, demand_kw)
    return max(0.0, min(power_kw, available_kw, terminal_kw))


def _next_soc(
    battery: BatterySpec, soc: float, charge_kw: float, discharge_kw: float
) -> float:
    """One step of (SOC) in ``docs/formulation.md``.

    ``soc + (eta_charge * charge_kw * 0.5 - discharge_kw * 0.5 / eta_discharge)
    / capacity_kwh``.
    """
    updated = (
        soc
        + (
            battery.eta_charge * charge_kw * SLOT_HOURS
            - discharge_kw * SLOT_HOURS / battery.eta_discharge
        )
        / battery.capacity_kwh
    )
    if -1e-9 < updated < 0.0:
        return 0.0
    if 1.0 < updated < 1.0 + 1e-9:
        return 1.0
    return updated


def _bill_pence(price_p_per_kwh: list[float], grid_import_kw: list[float]) -> float:
    """(COST) in ``docs/formulation.md``.

    With no battery, ``grid_import_kw`` is ``demand_kw``.
    """
    return sum(
        price * imported * SLOT_HOURS
        for price, imported in zip(price_p_per_kwh, grid_import_kw, strict=True)
    )


def _savings_share(no_battery: float, rule_cost: float, optimiser_cost: float) -> float:
    optimiser_savings = no_battery - optimiser_cost
    rule_savings = no_battery - rule_cost
    if optimiser_savings <= _SAVINGS_TOLERANCE_PENCE:
        if rule_savings >= -_SAVINGS_TOLERANCE_PENCE:
            return 1.0
        return 0.0
    return rule_savings / optimiser_savings
