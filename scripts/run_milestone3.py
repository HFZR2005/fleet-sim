"""Run the milestone 3 diversity comparison and penetration sweep.

Not collected by pytest. From the repository root, with the Low Carbon
London zip in ``.cache/lcl`` and a network connection for Agile prices:

    uv run python scripts/run_milestone3.py

Writes ``docs/results/milestone-3.json``. The pool is the first 100
households in the published file.
"""

import json
from datetime import date
from pathlib import Path

from fleet_sim.data import AgilePriceSource
from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.experiments import (
    replication_seed,
    run_experiment,
    run_penetration_sweep,
)
from fleet_sim.fleet.network import ROOT_NODE_ID
from fleet_sim.models.frames import Frame
from fleet_sim.models.scenario import Scenario
from fleet_sim.scenario import collect_days, load_scenario

_ROOT = Path(__file__).resolve().parents[1]
_ZIP = _ROOT / ".cache" / "lcl" / "LCL-FullData.zip"
_POOL_HOUSEHOLDS = 100
_OUTPUT = _ROOT / "docs" / "results" / "milestone-3.json"
_REPRESENTATIVE_DAY = date(2026, 1, 8)


def main() -> None:
    pool = HouseholdDemandPool.read(_ZIP, max_households=_POOL_HOUSEHOLDS)
    prices = AgilePriceSource()
    diverse = load_scenario(_ROOT / "scenarios" / "diverse.toml")
    diversity = run_experiment(diverse, pool=pool, price_source=prices)
    sweep = run_penetration_sweep(
        load_scenario(_ROOT / "scenarios" / "penetration-sweep.toml"),
        pool=pool,
        price_source=prices,
    )
    payload = {
        "pool_households": _POOL_HOUSEHOLDS,
        "pool_note": (
            "First 100 households in LCL-FullData.zip file order, "
            "not a random sample of all 5,567."
        ),
        "diversity_scenario": "scenarios/diverse.toml",
        "identical_scenario": "scenarios/identical.toml",
        "sweep_scenario": "scenarios/penetration-sweep.toml",
        "diversity": diversity.model_dump(mode="json"),
        "sweep": sweep.model_dump(mode="json"),
        "representative_day": _representative_day(diverse, pool, prices),
    }
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_OUTPUT}")


def _representative_day(
    scenario: Scenario,
    pool: HouseholdDemandPool,
    prices: AgilePriceSource,
) -> dict[str, object]:
    """One day of fleet import for replication 0, diverse and identical.

    The chart annotates the replication interval, not this day's peak.
    """
    day = _REPRESENTATIVE_DAY
    one_day = scenario.model_copy(update={"start": day, "end": day})
    seed = replication_seed(scenario.seed, 0)
    return {
        "day": day.isoformat(),
        "replication_index": 0,
        "seed": seed,
        "diverse_import_kw": _import_kw(
            collect_days(
                one_day,
                pool=pool,
                price_source=prices,
                seed=seed,
                penetration=1.0,
                mode="diverse",
            )[2]
        ),
        "identical_import_kw": _import_kw(
            collect_days(
                one_day,
                pool=pool,
                price_source=prices,
                seed=seed,
                penetration=1.0,
                mode="identical",
            )[2]
        ),
    }


def _import_kw(frames: list[Frame]) -> list[float]:
    return [_root_flow(frame) for frame in frames]


def _root_flow(frame: Frame) -> float:
    for node in frame.nodes:
        if node.node_id == ROOT_NODE_ID:
            return node.flow_kw
    raise ValueError(f"frame at {frame.slot_start.isoformat()} has no root node")


if __name__ == "__main__":
    main()
