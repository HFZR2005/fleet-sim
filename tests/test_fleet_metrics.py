"""Fleet measures on a two-home day small enough to add by hand."""

import pytest

from fleet_sim.fleet import FleetDay, SolvedHome, fleet_metrics
from fleet_sim.fleet.network import NodeFeedback
from fleet_sim.models import Schedule


def _schedule(imported: list[float], cost_pence: float) -> Schedule:
    zeros = [0.0] * len(imported)
    return Schedule(
        charge_kw=zeros,
        discharge_kw=zeros,
        grid_import_kw=imported,
        soc=[0.5] * len(imported),
        charge_mode=[0] * len(imported),
        cost_pence=cost_pence,
    )


def test_metrics_on_a_two_home_day() -> None:
    # Two slots, prices 2 then 10 p/kWh. Energy in a slot is power times 0.5.
    #
    # Home A demands [2, 2] kW. No battery: 2*2*0.5 + 2*10*0.5 = 12 pence.
    # Its import is [1, 4] kW and its tariff bill is 1*2*0.5 + 4*10*0.5 = 21,
    # so it saves 12 - 21 = -9 pence. Its own peak is 4 kW.
    #
    # Home B demands [1, 1] kW. No battery: 1*2*0.5 + 1*10*0.5 = 6 pence.
    # Its import is [3, 0] kW and its bill is 3*2*0.5 = 3, so it saves 3.
    # Its own peak is 3 kW.
    #
    # Root flow is [4, 4] kW. The peak is 4 kW in slot 0, the earlier tie.
    # The mean is 4, so the peak-to-average ratio is 1.
    # Coincidence is 4 / (4 + 3) = 4/7.
    # Without batteries the flow is [3, 3], peak 3 kW in slot 0.
    # Total saving is -6 pence, which is -3 pence per home.
    day = FleetDay(
        homes=[
            SolvedHome(
                home_id="a",
                transformer_id=None,
                demand_kw=[2.0, 2.0],
                schedule=_schedule([1.0, 4.0], 21.0),
            ),
            SolvedHome(
                home_id="b",
                transformer_id=None,
                demand_kw=[1.0, 1.0],
                schedule=_schedule([3.0, 0.0], 3.0),
            ),
        ],
        nodes=[
            NodeFeedback(
                node_id="root",
                flow_kw=[4.0, 4.0],
                limit_kw=None,
                overload_kw=[0.0, 0.0],
            )
        ],
    )

    metrics = fleet_metrics(day, [2.0, 10.0])

    assert metrics.peak_demand_kw == pytest.approx(4.0)
    assert metrics.peak_slot == 0
    assert metrics.peak_demand_without_battery_kw == pytest.approx(3.0)
    assert metrics.peak_slot_without_battery == 0
    assert metrics.peak_to_average_ratio == pytest.approx(1.0)
    assert metrics.coincidence_factor == pytest.approx(4.0 / 7.0)
    assert metrics.total_savings_pence == pytest.approx(-6.0)
    assert metrics.savings_per_home_pence == pytest.approx(-3.0)


def test_a_fleet_that_imports_nothing_has_zero_ratios() -> None:
    day = FleetDay(
        homes=[
            SolvedHome(
                home_id="a",
                transformer_id=None,
                demand_kw=[0.0, 0.0],
                schedule=_schedule([0.0, 0.0], 0.0),
            )
        ],
        nodes=[
            NodeFeedback(
                node_id="root",
                flow_kw=[0.0, 0.0],
                limit_kw=None,
                overload_kw=[0.0, 0.0],
            )
        ],
    )

    metrics = fleet_metrics(day, [10.0, 10.0])

    assert metrics.peak_to_average_ratio == 0.0
    assert metrics.coincidence_factor == 0.0
    assert metrics.total_savings_pence == pytest.approx(0.0)
