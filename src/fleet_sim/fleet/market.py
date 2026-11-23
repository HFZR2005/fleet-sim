"""The fleet in the loop for one day: the equilibrium and its metrics.

Price inputs are in ``fleet/price_inputs.py``.

See ``docs/formulation.md``, Fleet in the loop.
"""

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import block_diag, coo_array, hstack, vstack

from fleet_sim.fleet.solve import solve_fleet
from fleet_sim.models.fleet import Fleet, SolvedHome
from fleet_sim.models.home import SLOTS_PER_DAY, HomeDay, Schedule
from fleet_sim.models.market import (
    EquilibriumDiagnostics,
    MarketDay,
    MarketMetrics,
    MarketSettings,
)
from fleet_sim.models.prices import PriceSeries, require_gsp_region
from fleet_sim.optimise.home import SLOT_HOURS, HomeProblem, build_home
from fleet_sim.stubs import stub

# A home-slot whose charge and discharge both exceed this charges and
# discharges together, against (MODE).
_MODE_BREAK_KW = 1e-6


class DayPricing(Protocol):
    """What the equilibrium needs from one day's price inputs.

    ``DayPriceInputs`` is the real one. A test can pass a simpler price.
    """

    def prices(self, added_load_gw: list[float]) -> PriceSeries:
        """(PRICE): the tariff in each slot when the fleet adds ``added_load_gw``."""
        ...

    def out_of_range_slots(
        self, added_load_gw: list[float], curve_range_gw: tuple[float, float]
    ) -> int:
        """How many slots have R_t + b_t outside ``curve_range_gw``."""
        ...


@dataclass(frozen=True)
class FleetProblem:
    """(JOINT) subject to (LINK) for one fleet-day, ready for ``milp``.

    Columns are each battery home's block from ``build_home``, side by side
    in the order of ``homes``, then one column per slot and segment.
    ``breakpoints_gw`` are β_0..β_K and ``slopes`` holds σ_tk, slot by
    segment. Segment columns hold u_tk / κ, in kW (see ``build_fleet``).
    """

    homes: list[HomeProblem]
    kappa_gw_per_kw: float
    breakpoints_gw: list[float]
    slopes: NDArray[np.float64]
    cost: NDArray[np.float64]
    bounds: Bounds
    constraints: LinearConstraint

    def added_load_gw(self, solution: NDArray[np.float64]) -> list[float]:
        """(LOAD): b_t = κ Σ_j (c_jt − d_jt) in each slot, in GW."""
        net_kw = np.zeros(SLOTS_PER_DAY, dtype=np.float64)
        for offset, home in zip(self._offsets(), self.homes, strict=True):
            columns = home.columns
            for slot in range(SLOTS_PER_DAY):
                net_kw[slot] += (
                    solution[offset + columns.charge(slot)]
                    - solution[offset + columns.discharge(slot)]
                )
        return [float(self.kappa_gw_per_kw * net) for net in net_kw]

    def schedules(
        self, solution: NDArray[np.float64], price_p_per_kwh: list[float]
    ) -> list[Schedule]:
        """Each battery home's schedule, billed at ``price_p_per_kwh``."""
        return [
            home.schedule(
                solution[offset : offset + home.columns.count], price_p_per_kwh
            )
            for offset, home in zip(self._offsets(), self.homes, strict=True)
        ]

    def segment_slope(self, slot: int, added_load_gw: float) -> float:
        """σ_tk* for the segment k* that holds ``added_load_gw`` in ``slot``.

        Segment k is (β_{k−1}, β_k], and b = β_0 belongs to segment 1. A value
        on a breakpoint therefore takes the segment below it.
        """
        low = self.breakpoints_gw[0]
        n_segments = len(self.breakpoints_gw) - 1
        width = (self.breakpoints_gw[-1] - low) / n_segments
        k = min(max(math.ceil((added_load_gw - low) / width), 1), n_segments)
        return float(self.slopes[slot, k - 1])

    def _offsets(self) -> list[int]:
        offsets: list[int] = []
        start = 0
        for home in self.homes:
            offsets.append(start)
            start += home.columns.count
        return offsets


def build_fleet(
    days: list[HomeDay], kappa: float, price: DayPricing, segments: int
) -> FleetProblem:
    """(JOINT) subject to (LINK), ``docs/formulation.md``, Computing it.

    ``days`` are the battery homes; their prices are not read. Each home's
    block is ``build_home(day, with_mode=False)``: (SOC), bounds, (BALANCE)
    and (TERMINAL). ``kappa`` is κ in GW per kW from (LOAD). The range of the
    added load is

        b^min = −κ Σ_j d̄_j,   b^max = κ Σ_j c̄_j,

    split into K = ``segments`` segments of width w = (b^max − b^min) / K,
    with breakpoints β_k = b^min + k w. On segment k (SEGMENT) gives

        σ_tk = ½ (P_t(β_{k−1}) + P_t(β_k)),

    with P from ``price.prices``. The program is

        minimise (Δ/κ) Σ_t Σ_k σ_tk u_tk                       (JOINT)
        subject to κ Σ_j (c_jt − d_jt) = b^min + Σ_k u_tk,     (LINK)
        0 ≤ u_tk ≤ w.

    Both are divided through by κ: the segment columns hold v_tk = u_tk / κ
    in kW, so (LINK) reads Σ_j (c_jt − d_jt) = −Σ_j d̄_j + Σ_k v_tk with
    0 ≤ v_tk ≤ w / κ, and (JOINT) is Δ Σ_t Σ_k σ_tk v_tk. The minimiser is
    the same, and the coefficients no longer depend on the size of κ.
    """
    if kappa <= 0:
        raise ValueError(f"kappa must be greater than 0 (got {kappa})")
    if segments < 1:
        raise ValueError(f"segments must be at least 1 (got {segments})")
    homes = [build_home(day, with_mode=False) for day in days]
    charge_kw = sum(day.battery.max_charge_kw for day in days)
    discharge_kw = sum(day.battery.max_discharge_kw for day in days)
    if charge_kw + discharge_kw <= 0:
        raise ValueError("the battery homes must be able to charge or discharge")
    width_kw = (charge_kw + discharge_kw) / segments
    breakpoints_gw = [
        kappa * (-discharge_kw + k * width_kw) for k in range(segments + 1)
    ]
    rates = np.array(
        [
            price.prices([beta] * SLOTS_PER_DAY).price_p_per_kwh
            for beta in breakpoints_gw
        ],
        dtype=np.float64,
    )
    # rates[k, t] is P_t(β_k); slopes[t, k − 1] is σ_tk.
    slopes = 0.5 * (rates[:-1, :] + rates[1:, :]).T

    home_columns = sum(home.columns.count for home in homes)
    segment_columns = SLOTS_PER_DAY * segments
    cost = np.zeros(home_columns + segment_columns, dtype=np.float64)
    cost[home_columns:] = SLOT_HOURS * slopes.reshape(-1)

    lower = np.concatenate(
        [*(home.bounds.lb for home in homes), np.zeros(segment_columns)]
    )
    upper = np.concatenate(
        [*(home.bounds.ub for home in homes), np.full(segment_columns, width_kw)]
    )

    blocks = block_diag(
        [
            coo_array(
                np.vstack([np.asarray(c.A, dtype=np.float64) for c in home.constraints])
            )
            for home in homes
        ]
    )
    home_lower = np.concatenate([c.lb for home in homes for c in home.constraints])
    home_upper = np.concatenate([c.ub for home in homes for c in home.constraints])
    link = _link_rows(homes, home_columns, segments)
    link_rhs = np.full(SLOTS_PER_DAY, -discharge_kw)
    # Segment columns appear only in (LINK), so they are empty in the blocks.
    segment_block = coo_array((blocks.shape[0], segment_columns))
    matrix = vstack([hstack([blocks, segment_block]), link], format="csr")
    return FleetProblem(
        homes=homes,
        kappa_gw_per_kw=kappa,
        breakpoints_gw=breakpoints_gw,
        slopes=slopes,
        cost=cost,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(
            matrix,
            np.concatenate([home_lower, link_rhs]),
            np.concatenate([home_upper, link_rhs]),
        ),
    )


def _link_rows(homes: list[HomeProblem], home_columns: int, segments: int) -> coo_array:
    """(LINK) divided by κ: Σ_j (c_jt − d_jt) − Σ_k v_tk, one row per slot."""
    rows: list[int] = []
    cols: list[int] = []
    values: list[float] = []
    offset = 0
    for home in homes:
        for slot in range(SLOTS_PER_DAY):
            rows += [slot, slot]
            cols += [
                offset + home.columns.charge(slot),
                offset + home.columns.discharge(slot),
            ]
            values += [1.0, -1.0]
        offset += home.columns.count
    for slot in range(SLOTS_PER_DAY):
        for k in range(segments):
            rows.append(slot)
            cols.append(home_columns + slot * segments + k)
            values.append(-1.0)
    return coo_array(
        (values, (rows, cols)),
        shape=(SLOTS_PER_DAY, home_columns + SLOTS_PER_DAY * segments),
    )


def solve_market_day(
    fleet: Fleet,
    inputs: DayPricing,
    national_batteries: float,
    settings: MarketSettings,
) -> MarketDay:
    """The equilibrium (EQ) of one fleet-day, by (JOINT) subject to (LINK).

    ``docs/formulation.md``, Fleet in the loop. κ = M / (N_b · 10⁶) GW per
    kW (LOAD), with M = ``national_batteries`` and N_b the homes with a
    battery. ``build_fleet`` gives the program; its solution gives
    b*_t = κ Σ_j (c_jt − d_jt) and the prices p*_t = P_t(b*_t) (PRICE).

    Two allocations of b* are returned. **Joint** is each battery home's
    schedule from the program. **Re-planned** is each battery home solved
    alone at p* by ``optimise_home``, (MODE) included. A home without a
    battery imports its demand in both. Both are billed at p*.

    With M = 0, no battery home, or batteries that can neither charge nor
    discharge, b = 0 and this is the historical-price run, ``solve_fleet``
    at P(0), with zero diagnostics apart from the out-of-range count.
    """
    historical = inputs.prices([0.0] * SLOTS_PER_DAY)
    days = [
        HomeDay(
            home_id=home.home_id,
            region=require_gsp_region(home.region),
            transformer_id=home.transformer_id,
            battery=home.battery,
            demand_kw=list(home.demand_kw),
            price_p_per_kwh=list(historical.price_p_per_kwh),
        )
        for home in fleet.homes
        if home.battery is not None
    ]
    power_kw = sum(d.battery.max_charge_kw + d.battery.max_discharge_kw for d in days)
    if national_batteries == 0 or power_kw == 0:
        return _historical_day(fleet, inputs, historical, settings)

    kappa = national_batteries / (len(days) * 1e6)
    problem = build_fleet(days, kappa, inputs, settings.segments)
    result = milp(
        problem.cost,
        integrality=np.zeros(problem.cost.size, dtype=np.int64),
        bounds=problem.bounds,
        constraints=problem.constraints,
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"fleet-day equilibrium is not optimal ({result.message})")
    solution = np.asarray(result.x, dtype=np.float64)

    added_load_gw = problem.added_load_gw(solution)
    prices = inputs.prices(added_load_gw)
    joint_schedules = dict(
        zip(
            (day.home_id for day in days),
            problem.schedules(solution, list(prices.price_p_per_kwh)),
            strict=True,
        )
    )
    replanned = solve_fleet(fleet, prices, None).homes
    joint = [
        home.model_copy(update={"schedule": joint_schedules[home.home_id]})
        if home.home_id in joint_schedules
        else home
        for home in replanned
    ]
    battery_ids = set(joint_schedules)
    diagnostics = _diagnostics(
        problem,
        added_load_gw,
        prices,
        [home for home in joint if home.home_id in battery_ids],
        [home for home in replanned if home.home_id in battery_ids],
        inputs.out_of_range_slots(added_load_gw, settings.curve_range_gw),
        settings.equilibrium_tolerance_p,
    )
    return MarketDay(
        day=prices.day,
        added_load_gw=added_load_gw,
        prices=prices,
        joint=joint,
        replanned=replanned,
        diagnostics=diagnostics,
    )


def _historical_day(
    fleet: Fleet,
    inputs: DayPricing,
    historical: PriceSeries,
    settings: MarketSettings,
) -> MarketDay:
    """b = 0: every home solved at the historical rates, as in milestone 4."""
    added_load_gw = [0.0] * SLOTS_PER_DAY
    homes = solve_fleet(fleet, historical, None).homes
    return MarketDay(
        day=historical.day,
        added_load_gw=added_load_gw,
        prices=historical,
        joint=homes,
        replanned=homes,
        diagnostics=EquilibriumDiagnostics(
            linearisation_error_p_per_kwh=0.0,
            mode_break_slots=0,
            max_replan_saving_p=0.0,
            total_replan_saving_p=0.0,
            exceeds_tolerance=False,
            replanned_load_difference_gw=0.0,
            out_of_range_slots=inputs.out_of_range_slots(
                added_load_gw, settings.curve_range_gw
            ),
        ),
    )


def _diagnostics(
    problem: FleetProblem,
    added_load_gw: list[float],
    prices: PriceSeries,
    joint: list[SolvedHome],
    replanned: list[SolvedHome],
    out_of_range_slots: int,
    tolerance_p: float,
) -> EquilibriumDiagnostics:
    """Linearisation error, (MODE) breaks, (CHECK), and the re-planned load.

    ``docs/formulation.md``, Computing it. ``joint`` and ``replanned`` are the
    battery homes in the same order, each billed at p*.

    - Linearisation error: max_t |P_t(b*_t) − σ_tk*|, k* the segment that
      holds b*_t (``FleetProblem.segment_slope``).
    - (MODE) breaks: home-slots of the joint schedule with c_jt and d_jt both
      above 1e-6 kW.
    - (CHECK): E_j = Δ Σ_t p*_t g*_jt − (re-solved bill at p*), which is the
      joint bill minus the re-planned bill. The largest and the sum are
      reported, and the run exceeds the tolerance when the largest does.
    - Re-planned load difference: max_t |κ Σ_j (c^re_jt − d^re_jt) − b*_t|,
      in GW, where c^re and d^re are the re-planned schedules (Open choices).
    """
    error = max(
        abs(rate - problem.segment_slope(slot, load))
        for slot, (rate, load) in enumerate(
            zip(prices.price_p_per_kwh, added_load_gw, strict=True)
        )
    )
    mode_breaks = sum(
        charge > _MODE_BREAK_KW and discharge > _MODE_BREAK_KW
        for home in joint
        for charge, discharge in zip(
            home.schedule.charge_kw, home.schedule.discharge_kw, strict=True
        )
    )
    savings = [
        together.schedule.cost_pence - alone.schedule.cost_pence
        for together, alone in zip(joint, replanned, strict=True)
    ]
    replanned_load = [
        problem.kappa_gw_per_kw
        * sum(
            home.schedule.charge_kw[slot] - home.schedule.discharge_kw[slot]
            for home in replanned
        )
        for slot in range(SLOTS_PER_DAY)
    ]
    largest = max(savings)
    return EquilibriumDiagnostics(
        linearisation_error_p_per_kwh=error,
        mode_break_slots=mode_breaks,
        max_replan_saving_p=largest,
        total_replan_saving_p=sum(savings),
        exceeds_tolerance=largest > tolerance_p,
        replanned_load_difference_gw=max(
            abs(again - load)
            for again, load in zip(replanned_load, added_load_gw, strict=True)
        ),
        out_of_range_slots=out_of_range_slots,
    )


@stub("returns zeros")
def market_metrics(days: list[MarketDay]) -> MarketMetrics:
    """National added load, bills and prices over one replication's days."""
    if len(days) == 0:
        raise ValueError("market metrics need at least one day")
    return MarketMetrics(
        peak_added_load_gw=0.0,
        peak_added_load_hour=0,
        saving_per_battery_home_p_per_day=0.0,
        non_battery_price_change_p_per_day=0.0,
        mean_charge_price_p_per_kwh=0.0,
        mean_discharge_price_p_per_kwh=0.0,
    )
