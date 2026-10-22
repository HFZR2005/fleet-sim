"""Draw the milestone 3 figures from ``docs/results/milestone-3.json``.

Does not solve a fleet. From the repository root:

    uv run python scripts/render_milestone3.py
"""

from pathlib import Path

from fleet_sim.viz import plot_diversity_day, plot_penetration_curve, save_figure
from fleet_sim.viz.results import read_diversity_day, read_penetration_curve

_ROOT = Path(__file__).resolve().parents[1]
_RESULTS = _ROOT / "docs" / "results" / "milestone-3.json"


def main() -> None:
    penetrations, with_battery, without_battery = read_penetration_curve(_RESULTS)
    save_figure(
        plot_penetration_curve(penetrations, with_battery, without_battery),
        _ROOT / "docs" / "penetration",
    )
    diverse, identical, day, difference = read_diversity_day(_RESULTS)
    save_figure(
        plot_diversity_day(diverse, identical, day=day, peak_difference_kw=difference),
        _ROOT / "docs" / "diversity",
    )
    print("wrote docs/penetration.svg and docs/diversity.svg")


if __name__ == "__main__":
    main()
