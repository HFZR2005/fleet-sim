"""Network flow summed from the leaves upward."""

import pytest

from fleet_sim.fleet.network import Network
from fleet_sim.models.network import HomeProfile, NetworkNode, NetworkSpec


def test_a_three_level_tree_matches_a_hand_sum() -> None:
    """Two slots, worked by hand.

    tx-1 has limit 3 kW and home h1 imports [2, 4].
    tx-2 has limit 2 kW and home h2 imports [1, 3].
    Both sit under mid, limit 6 kW, which sits under an unconstrained root.

    tx-1 flow [2, 4], overload [0, 1] because 4 - 3 = 1.
    tx-2 flow [1, 3], overload [0, 1] because 3 - 2 = 1.
    mid flow [3, 7], overload [0, 1] because 7 - 6 = 1.
    root flow [3, 7], overload [0, 0], equal to h1 + h2 in each slot.
    """
    spec = NetworkSpec(
        nodes=[
            NetworkNode(node_id="root", parent_id=None),
            NetworkNode(node_id="mid", parent_id="root", limit_kw=6),
            NetworkNode(node_id="tx-1", parent_id="mid", limit_kw=3),
            NetworkNode(node_id="tx-2", parent_id="mid", limit_kw=2),
        ],
        home_transformer={"h1": "tx-1", "h2": "tx-2"},
    )
    feedback = Network(spec=spec).evaluate(
        [
            HomeProfile(home_id="h1", grid_import_kw=[2.0, 4.0]),
            HomeProfile(home_id="h2", grid_import_kw=[1.0, 3.0]),
        ]
    )
    by_id = {node.node_id: node for node in feedback}

    assert by_id["tx-1"].flow_kw == [2.0, 4.0]
    assert by_id["tx-1"].overload_kw == [0.0, 1.0]
    assert by_id["tx-2"].flow_kw == [1.0, 3.0]
    assert by_id["tx-2"].overload_kw == [0.0, 1.0]
    assert by_id["mid"].flow_kw == [3.0, 7.0]
    assert by_id["mid"].overload_kw == [0.0, 1.0]
    assert by_id["mid"].limit_kw == 6
    assert by_id["root"].flow_kw == [3.0, 7.0]
    assert by_id["root"].overload_kw == [0.0, 0.0]
    assert by_id["root"].limit_kw is None


def test_a_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        NetworkNode(node_id="tx", parent_id="root", limit_kw=0)
