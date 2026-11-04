"""Overload metrics computed from hand-worked cases.

Each test builds ``NodeFeedback`` directly and checks the metrics against
values worked out below. The slot length is 0.5 hours (DT).
"""

from datetime import date

import pytest

from fleet_sim.fleet.overload import day_overload, summarise_replication
from fleet_sim.models.network import NodeFeedback


def _node(
    node_id: str,
    flow_kw: list[float],
    limit_kw: float,
) -> NodeFeedback:
    overload_kw = [max(0.0, f - limit_kw) for f in flow_kw]
    return NodeFeedback(
        node_id=node_id,
        flow_kw=flow_kw,
        limit_kw=limit_kw,
        overload_kw=overload_kw,
    )


def _root(flow_kw: list[float]) -> NodeFeedback:
    return NodeFeedback(
        node_id="root",
        flow_kw=flow_kw,
        limit_kw=None,
        overload_kw=[0.0] * len(flow_kw),
    )


# --- Hand-worked case ---
#
# Two transformers, two slots.
#
#   Transformer A: limit = 10 kW, flow = [12, 8]
#     slot 0: overload = 2 kW, slot 1: overload = 0
#     peak utilisation = 12 / 10 = 1.2
#     overload energy = 2 × 0.5 = 1.0 kWh
#     overloaded slots = 1
#
#   Transformer B: limit = 5 kW, flow = [4, 6]
#     slot 0: overload = 0, slot 1: overload = 1 kW
#     peak utilisation = 6 / 5 = 1.2
#     overload energy = 1 × 0.5 = 0.5 kWh
#     overloaded slots = 1
#
#   Root: flow = [16, 14], no limit
#
#   Hidden overloads:
#     sum of limits = 10 + 5 = 15
#     slot 0: total flow = 16 > 15, A is over → not hidden (fleet total over)
#     slot 1: total flow = 14 ≤ 15, B is over → hidden
#     hidden share = 1 / 2 = 0.5
#
#   Slot overload counts: [1, 1]
#     slot 0: A is over (1 transformer)
#     slot 1: B is over (1 transformer)


_DAY = date(2024, 6, 15)
_NODES_TWO_SLOTS = [
    _root([16.0, 14.0]),
    _node("tx-A", [12.0, 8.0], 10.0),
    _node("tx-B", [4.0, 6.0], 5.0),
]


class TestDayOverloadHandWorked:
    def test_peak_utilisation(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        by_id = {t.node_id: t for t in result.transformers}
        assert by_id["tx-A"].peak_utilisation == pytest.approx(1.2)
        assert by_id["tx-B"].peak_utilisation == pytest.approx(1.2)

    def test_overload_energy(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        by_id = {t.node_id: t for t in result.transformers}
        # A: 2 kW × 0.5 h = 1.0 kWh
        assert by_id["tx-A"].overload_energy_kwh == pytest.approx(1.0)
        # B: 1 kW × 0.5 h = 0.5 kWh
        assert by_id["tx-B"].overload_energy_kwh == pytest.approx(0.5)

    def test_overloaded_slots(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        by_id = {t.node_id: t for t in result.transformers}
        assert by_id["tx-A"].overloaded_slots == 1
        assert by_id["tx-B"].overloaded_slots == 1

    def test_hidden_overload_share(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        assert result.hidden_overload_share == pytest.approx(0.5)

    def test_slot_overload_counts(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        assert result.slot_overload_counts == [1, 1]

    def test_root_is_excluded(self) -> None:
        result = day_overload(_DAY, _NODES_TWO_SLOTS)
        ids = {t.node_id for t in result.transformers}
        assert "root" not in ids


class TestDayOverloadNoOverload:
    """When every transformer is within its limit."""

    def test_all_zeros(self) -> None:
        nodes = [
            _root([5.0, 5.0]),
            _node("tx-A", [3.0, 4.0], 10.0),
            _node("tx-B", [2.0, 1.0], 5.0),
        ]
        result = day_overload(_DAY, nodes)
        for t in result.transformers:
            assert t.overloaded_slots == 0
            assert t.overload_energy_kwh == 0.0
        assert result.hidden_overload_share == 0.0

    def test_utilisation_below_one(self) -> None:
        nodes = [
            _root([5.0]),
            _node("tx-A", [5.0], 10.0),
        ]
        result = day_overload(_DAY, nodes)
        assert result.transformers[0].peak_utilisation == pytest.approx(0.5)


# --- Hand-worked replication case ---
#
# One transformer, two days.
#
#   Day 1: limit = 10, flow = [12, 8]
#     peak_utilisation = 1.2, overload_energy = 1.0, overloaded_slots = 1
#     slot_overload_counts = [1, 0]
#
#   Day 2: limit = 10, flow = [9, 11]
#     peak_utilisation = 1.1, overload_energy = 0.5, overloaded_slots = 1
#     slot_overload_counts = [0, 1]
#
#   Replication:
#     share overloaded = 1/1 = 1.0 (the one transformer is overloaded on both days)
#     mean utilisation = (1.2 + 1.1) / 2 = 1.15
#     worst utilisation = 1.2
#     total energy = 1.0 + 0.5 = 1.5
#     hidden share = (0.0 + 0.0) / 2 = 0.0 (only one transformer, never hidden)
#     overload hour:
#       day 1 slot 0 → hour 0, count 1
#       day 2 slot 1 → hour 0, count 1  (slot 1 is also hour 0)
#       hour 0 total = 2 → overload_hour = 0


class TestSummariseReplicationHandWorked:
    def _two_days(self) -> list[object]:
        day1_nodes = [
            _root([12.0, 8.0]),
            _node("tx-A", [12.0, 8.0], 10.0),
        ]
        day2_nodes = [
            _root([9.0, 11.0]),
            _node("tx-A", [9.0, 11.0], 10.0),
        ]
        d1 = day_overload(date(2024, 6, 15), day1_nodes)
        d2 = day_overload(date(2024, 6, 16), day2_nodes)
        return [d1, d2]

    def test_share_overloaded(self) -> None:
        result = summarise_replication(self._two_days())
        assert result.transformers_overloaded_share == pytest.approx(1.0)

    def test_mean_utilisation(self) -> None:
        result = summarise_replication(self._two_days())
        assert result.mean_peak_utilisation == pytest.approx(1.15)

    def test_worst_utilisation(self) -> None:
        result = summarise_replication(self._two_days())
        assert result.worst_peak_utilisation == pytest.approx(1.2)

    def test_total_energy(self) -> None:
        result = summarise_replication(self._two_days())
        assert result.total_overload_energy_kwh == pytest.approx(1.5)

    def test_overload_hour(self) -> None:
        result = summarise_replication(self._two_days())
        # Both overloaded slots fall in hour 0 (slots 0 and 1)
        assert result.overload_hour == 0

    def test_hidden_share(self) -> None:
        result = summarise_replication(self._two_days())
        assert result.hidden_overload_share == pytest.approx(0.0)


class TestOverloadHour:
    def test_none_when_no_overload(self) -> None:
        nodes = [_root([5.0, 5.0]), _node("tx-A", [3.0, 4.0], 10.0)]
        d = day_overload(_DAY, nodes)
        result = summarise_replication([d])
        assert result.overload_hour is None

    def test_peak_hour_with_multiple_slots(self) -> None:
        """Four slots: hours 0 and 1. Overload in slots 2 and 3 (hour 1)
        and slot 0 (hour 0). Hour 1 has more overload → picked.

        Slot 0 (hour 0): flow 12, limit 10 → overload 2 (1 transformer)
        Slot 1 (hour 0): flow 8, limit 10 → no overload
        Slot 2 (hour 1): flow 15, limit 10 → overload 5 (1 transformer)
        Slot 3 (hour 1): flow 11, limit 10 → overload 1 (1 transformer)
        Hour 0 count: 1, Hour 1 count: 2 → hour 1.
        """
        nodes = [
            _root([12.0, 8.0, 15.0, 11.0]),
            _node("tx-A", [12.0, 8.0, 15.0, 11.0], 10.0),
        ]
        d = day_overload(_DAY, nodes)
        result = summarise_replication([d])
        assert result.overload_hour == 1

    def test_tie_goes_to_earliest_hour(self) -> None:
        """Two slots in different hours, each overloaded once. Hour 0 wins."""
        nodes = [
            _root([12.0, 8.0, 12.0, 8.0]),
            _node("tx-A", [12.0, 8.0, 12.0, 8.0], 10.0),
        ]
        d = day_overload(_DAY, nodes)
        result = summarise_replication([d])
        # slot 0 → hour 0 (count 1), slot 2 → hour 1 (count 1), tie → hour 0
        assert result.overload_hour == 0


class TestSummariseReplicationEdgeCases:
    def test_empty_days_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one day"):
            summarise_replication([])

    def test_no_transformers_raises(self) -> None:
        d = day_overload(_DAY, [_root([5.0])])
        with pytest.raises(ValueError, match="at least one transformer"):
            summarise_replication([d])
