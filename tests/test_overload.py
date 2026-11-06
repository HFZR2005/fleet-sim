"""Overload metrics computed from hand-worked cases.

Each test builds ``NodeFeedback`` directly and checks the metrics against
values worked out below. The slot length is 0.5 hours (DT).
"""

from datetime import date

import pytest

from fleet_sim.fleet.overload import day_overload, summarise_replication
from fleet_sim.models.network import DayOverload, NodeFeedback

_DAY = date(2024, 6, 15)


def _node(node_id: str, flow_kw: list[float], limit_kw: float) -> NodeFeedback:
    return NodeFeedback(
        node_id=node_id,
        flow_kw=flow_kw,
        limit_kw=limit_kw,
        overload_kw=[max(0.0, f - limit_kw) for f in flow_kw],
    )


def _root(flow_kw: list[float]) -> NodeFeedback:
    return NodeFeedback(
        node_id="root",
        flow_kw=flow_kw,
        limit_kw=None,
        overload_kw=[0.0] * len(flow_kw),
    )


def _one_transformer_day(day: date, flow_kw: list[float]) -> DayOverload:
    return day_overload(day, [_root(flow_kw), _node("tx-A", flow_kw, 10.0)])


def test_day_overload_hand_worked() -> None:
    """Two transformers, two slots.

    A: limit 10 kW, flow [12, 8]
       peak utilisation 12 / 10 = 1.2, overload energy 2 × 0.5 = 1.0 kWh, 1 slot
    B: limit 5 kW, flow [4, 6]
       peak utilisation 6 / 5 = 1.2, overload energy 1 × 0.5 = 0.5 kWh, 1 slot
    Root: flow [16, 14], no limit, excluded from transformer metrics.

    Hidden overloads (sum of limits = 15):
      slot 0: total 16 > 15, A over → not hidden
      slot 1: total 14 ≤ 15, B over → hidden
      share = 1 / 2 = 0.5
    Slot overload counts: [1, 1].
    """
    result = day_overload(
        _DAY,
        [
            _root([16.0, 14.0]),
            _node("tx-A", [12.0, 8.0], 10.0),
            _node("tx-B", [4.0, 6.0], 5.0),
        ],
    )
    by_id = {t.node_id: t for t in result.transformers}

    assert set(by_id) == {"tx-A", "tx-B"}
    assert by_id["tx-A"].peak_utilisation == pytest.approx(1.2)
    assert by_id["tx-B"].peak_utilisation == pytest.approx(1.2)
    assert by_id["tx-A"].overload_energy_kwh == pytest.approx(1.0)
    assert by_id["tx-B"].overload_energy_kwh == pytest.approx(0.5)
    assert by_id["tx-A"].overloaded_slots == 1
    assert by_id["tx-B"].overloaded_slots == 1
    assert result.hidden_overload_share == pytest.approx(0.5)
    assert result.slot_overload_counts == [1, 1]


def test_day_within_limits_has_no_overload() -> None:
    """A: peak 4 / 10 = 0.4. B: peak 2 / 5 = 0.4."""
    result = day_overload(
        _DAY,
        [
            _root([5.0, 5.0]),
            _node("tx-A", [3.0, 4.0], 10.0),
            _node("tx-B", [2.0, 1.0], 5.0),
        ],
    )
    for t in result.transformers:
        assert t.peak_utilisation == pytest.approx(0.4)
        assert t.overloaded_slots == 0
        assert t.overload_energy_kwh == 0.0
    assert result.hidden_overload_share == 0.0


def test_summarise_replication_hand_worked() -> None:
    """One transformer (limit 10 kW), two days.

    Day 1: flow [12, 8]  → peak 1.2, energy 2 × 0.5 = 1.0 kWh
    Day 2: flow [9, 11]  → peak 1.1, energy 1 × 0.5 = 0.5 kWh

    share overloaded = 1 / 1 = 1.0
    mean utilisation = (1.2 + 1.1) / 2 = 1.15, worst = 1.2
    total energy = 1.0 + 0.5 = 1.5 kWh
    hidden share = 0 (a single transformer is never hidden)
    overload hour: day 1 slot 0 and day 2 slot 1 are both hour 0.
    """
    result = summarise_replication(
        [
            _one_transformer_day(date(2024, 6, 15), [12.0, 8.0]),
            _one_transformer_day(date(2024, 6, 16), [9.0, 11.0]),
        ]
    )
    assert result.transformers_overloaded_share == pytest.approx(1.0)
    assert result.mean_peak_utilisation == pytest.approx(1.15)
    assert result.worst_peak_utilisation == pytest.approx(1.2)
    assert result.total_overload_energy_kwh == pytest.approx(1.5)
    assert result.hidden_overload_share == pytest.approx(0.0)
    assert result.overload_hour == 0


@pytest.mark.parametrize(
    ("flow_kw", "expected_hour"),
    [
        # Nothing over the 10 kW limit.
        ([3.0, 4.0], None),
        # Hour 0 has one overloaded slot (0), hour 1 has two (2, 3).
        ([12.0, 8.0, 15.0, 11.0], 1),
        # One overloaded slot in each hour: the tie goes to the earliest.
        ([12.0, 8.0, 12.0, 8.0], 0),
    ],
)
def test_overload_hour_has_the_most_overloaded_slots(
    flow_kw: list[float], expected_hour: int | None
) -> None:
    result = summarise_replication([_one_transformer_day(_DAY, flow_kw)])
    assert result.overload_hour == expected_hour


@pytest.mark.parametrize(
    ("days", "message"),
    [
        ([], "at least one day"),
        ([day_overload(_DAY, [_root([5.0])])], "at least one transformer"),
    ],
)
def test_summarise_replication_rejects_empty_input(
    days: list[DayOverload], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        summarise_replication(days)
