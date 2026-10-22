"""Run the milestone 3 diversity comparison and penetration sweep.

Not collected by pytest. From the repository root, with the Low Carbon
London zip in ``.cache/lcl`` and a network connection for Agile prices:

    uv run python scripts/run_milestone3.py

Writes ``docs/results/milestone-3.json``. The pool is the first 100
households in the published file.
"""

import json
from pathlib import Path

from fleet_sim.data import AgilePriceSource
from fleet_sim.data.households import HouseholdDemandPool
from fleet_sim.experiments import run_experiment, run_penetration_sweep
from fleet_sim.scenario import load_scenario

_ROOT = Path(__file__).resolve().parents[1]
_ZIP = _ROOT / ".cache" / "lcl" / "LCL-FullData.zip"
_POOL_HOUSEHOLDS = 100
_OUTPUT = _ROOT / "docs" / "results" / "milestone-3.json"


def main() -> None:
    pool = HouseholdDemandPool.read(_ZIP, max_households=_POOL_HOUSEHOLDS)
    prices = AgilePriceSource()
    diversity = run_experiment(
        load_scenario(_ROOT / "scenarios" / "diverse.toml"),
        pool=pool,
        price_source=prices,
    )
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
    }
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_OUTPUT}")


if __name__ == "__main__":
    main()
