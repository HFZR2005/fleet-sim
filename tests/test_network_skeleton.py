"""The network skeleton runs, lists its stubs, and refuses --release."""

import json
from pathlib import Path

import pytest

from fleet_sim.cli import main
from fleet_sim.fleet.topology import build_topology
from fleet_sim.models.network import NetworkNode, NetworkSettings, NetworkSpec

_ROOT = Path(__file__).parents[1]
_PRICES = _ROOT / "tests" / "fixtures" / "agile_import_c_2024-06-15.json"
_HOUSEHOLDS = _ROOT / "tests" / "fixtures" / "lcl_household_days.csv"
_SCENARIO = _ROOT / "scenarios" / "smoke-network.toml"


def test_the_smoke_scenario_runs_and_lists_its_stubs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    code = main(
        _argv(output, tmp_path / "cache"), opener=lambda _url: _PRICES.read_bytes()
    )

    assert code == 0
    text = capsys.readouterr().out
    assert text.startswith("STUB ") or "STUB " in text
    assert "build_topology" in text
    assert "day_overload" in text
    assert "_evaluate_transformers" not in text
    assert "plot_network_overload" in text
    frames = json.loads((output / "frames.json").read_text(encoding="utf-8"))
    nodes = frames["frames"][0]["nodes"]
    by_id = {node["node_id"]: node for node in nodes}
    assert set(by_id) == {"root", "transformer-1", "transformer-2"}
    transformer = by_id["transformer-1"]
    assert transformer["flow_kw"] > transformer["limit_kw"]
    assert transformer["overload_kw"] == pytest.approx(
        transformer["flow_kw"] - transformer["limit_kw"]
    )
    assert by_id["root"]["flow_kw"] == pytest.approx(
        by_id["transformer-1"]["flow_kw"] + by_id["transformer-2"]["flow_kw"]
    )
    homes = frames["frames"][0]["homes"]
    assert {home["transformer_id"] for home in homes} == {
        "transformer-1",
        "transformer-2",
    }
    svg = (output / "overload.svg").read_text(encoding="utf-8")
    assert "STUB" in svg


def test_release_fails_while_stubs_are_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [*_argv(tmp_path / "out", tmp_path / "cache"), "--release"],
        opener=lambda _url: _PRICES.read_bytes(),
    )

    assert code == 1
    error = capsys.readouterr().err
    assert "STUB" in error
    assert "build_topology" in error
    assert not (tmp_path / "out" / "frames.json").exists()


def test_a_cycle_is_not_a_tree() -> None:
    with pytest.raises(ValueError, match="cycle"):
        NetworkSpec(
            nodes=[
                NetworkNode(node_id="root", parent_id=None),
                NetworkNode(node_id="a", parent_id="b"),
                NetworkNode(node_id="b", parent_id="a"),
            ],
            home_transformer={"home-1": "a"},
        )


def test_two_roots_and_a_home_on_the_root_are_rejected() -> None:
    with pytest.raises(ValueError, match="one root"):
        NetworkSpec(
            nodes=[
                NetworkNode(node_id="root", parent_id=None),
                NetworkNode(node_id="other", parent_id=None),
            ],
            home_transformer={"home-1": "root"},
        )
    with pytest.raises(ValueError, match="placed on the root"):
        NetworkSpec(
            nodes=[NetworkNode(node_id="root", parent_id=None)],
            home_transformer={"home-1": "root"},
        )


def test_homes_must_split_equally() -> None:
    settings = NetworkSettings(n_transformers=2, limit_kw=1.0)
    with pytest.raises(ValueError, match="do not split equally"):
        build_topology(["home-1", "home-2", "home-3"], settings)


def _argv(output: Path, cache: Path) -> list[str]:
    return [
        "run-scenario",
        str(_SCENARIO),
        "--households",
        str(_HOUSEHOLDS),
        "--output",
        str(output),
        "--max-households",
        "2",
        "--cache-dir",
        str(cache),
    ]
