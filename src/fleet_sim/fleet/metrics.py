"""How a fleet's demand and bill change once the batteries have a schedule.

The definitions are the fleet measures in ``docs/formulation.md``. They read
a solved day. They do not solve one.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from fleet_sim.fleet.network import ROOT_NODE_ID
from fleet_sim.fleet.solve import FleetDay

# (DT) in docs/formulation.md.
_HOURS_PER_SLOT = 0.5


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


def fleet_metrics(day: FleetDay, price_p_per_kwh: Sequence[float]) -> FleetMetrics:
    """Measures for one solved fleet day.

    Peak demand is the root-node flow. The without-battery peak is the sum
    of the homes' demand. Savings are the tariff bills avoided, in pence.
    """
    if len(day.homes) == 0:
        raise ValueError("a fleet day must contain at least one home")
    flow = _root_flow(day)
    n_slots = len(flow)
    without = [0.0] * n_slots
    home_peaks: list[float] = []
    total_savings = 0.0
    for home in day.homes:
        if len(home.demand_kw) != n_slots:
            raise ValueError(
                f"home {home.home_id} demand must cover the root flow "
                f"(got {len(home.demand_kw)} for {n_slots} slots)"
            )
        if len(home.schedule.grid_import_kw) != n_slots:
            raise ValueError(
                f"home {home.home_id} import must cover the root flow "
                f"(got {len(home.schedule.grid_import_kw)} for {n_slots} slots)"
            )
        for slot, demand in enumerate(home.demand_kw):
            without[slot] += demand
        home_peaks.append(max(home.schedule.grid_import_kw))
        total_savings += _saving_pence(
            home.demand_kw, price_p_per_kwh, home.schedule.cost_pence
        )
    peak_kw, peak_slot = _peak(flow)
    without_kw, without_slot = _peak(without)
    return FleetMetrics(
        peak_demand_kw=peak_kw,
        peak_slot=peak_slot,
        peak_demand_without_battery_kw=without_kw,
        peak_slot_without_battery=without_slot,
        peak_to_average_ratio=_peak_to_average(peak_kw, flow),
        coincidence_factor=_coincidence(peak_kw, home_peaks),
        total_savings_pence=total_savings,
        savings_per_home_pence=total_savings / len(day.homes),
    )


def _root_flow(day: FleetDay) -> list[float]:
    for node in day.nodes:
        if node.node_id == ROOT_NODE_ID:
            return list(node.flow_kw)
    raise ValueError(f"fleet day has no {ROOT_NODE_ID} node")


def _peak(values: Sequence[float]) -> tuple[float, int]:
    """The greatest value and the earliest slot that attains it."""
    peak = max(values)
    return peak, list(values).index(peak)


def _peak_to_average(peak: float, values: Sequence[float]) -> float:
    average = sum(values) / len(values)
    if average == 0.0:
        return 0.0
    return peak / average


def _coincidence(fleet_peak: float, home_peaks: Sequence[float]) -> float:
    total = sum(home_peaks)
    if total == 0.0:
        return 0.0
    return fleet_peak / total


def _saving_pence(
    demand_kw: Sequence[float], price_p_per_kwh: Sequence[float], cost_pence: float
) -> float:
    no_battery = sum(
        price * demand * _HOURS_PER_SLOT
        for price, demand in zip(price_p_per_kwh, demand_kw, strict=True)
    )
    return no_battery - cost_pence
