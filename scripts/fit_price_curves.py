"""Fit and compare price-curve models, or finalise the chosen models.

Loads the data and the fleet's charging, then runs ``compare`` or
``finalise`` from ``fleet_sim.prices.pipeline``.  Invoke with::

    uv run python scripts/fit_price_curves.py compare [TARGET/FAMILY ...]
    uv run python scripts/fit_price_curves.py finalise

``compare`` writes residuals, and plots them, for each model named after
it.  ``--config PATH`` reads another config than
``calibration/price_curves.toml``.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import date
from pathlib import Path

from fleet_sim.data.agile_history import HistoricalAgileSource
from fleet_sim.prices.config import CalibrationConfig, load_config
from fleet_sim.prices.dataset import (
    PriceDataset,
    build_dataset,
    final_test_split,
    selection_data,
    summarise,
)
from fleet_sim.prices.evaluation import EvaluationReport, comparison_table
from fleet_sim.prices.fleet_weights import (
    FleetCharging,
    fleet_charging,
    uncoordinated,
)
from fleet_sim.prices.parameters import Provenance
from fleet_sim.prices.pipeline import compare, finalise
from fleet_sim.stubs import StubActiveError, active_stubs, begin_stub_run

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG = _ROOT / "calibration" / "price_curves.toml"
_SCENARIOS = _ROOT / "scenarios"
_HOUSEHOLDS = _ROOT / ".cache" / "lcl" / "LCL-FullData.zip"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["compare", "finalise"])
    parser.add_argument(
        "models", nargs="*", help="compare only: models to write residuals for"
    )
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.mode == "compare":
        _compare(config, args.models)
    else:
        if args.models:
            parser.error("finalise takes no models")
        _finalise(config, args.config)


def _compare(config: CalibrationConfig, residual_models: list[str]) -> None:
    """Load the training years and run ``compare`` on them."""
    begin_stub_run()
    dataset = _load_dataset(config)
    charging = _fleet_charging(config, selection_data(dataset, config.splits))
    result = compare(config, dataset, charging, residual_models)
    print(result.table)
    for model_name, path in result.residual_paths.items():
        print(f"Residuals for {model_name} written to {path}")
    _print_stubs("Active stubs:")


def _finalise(config: CalibrationConfig, config_path: Path) -> None:
    """Load the data and run ``finalise``: the final-test year is read once."""
    begin_stub_run()
    dataset = _load_dataset(config)
    _train, test_data = final_test_split(dataset, config.splits)
    charging = _fleet_charging(config, test_data)
    try:
        parameters = finalise(
            config, dataset, charging, _provenance(config, config_path)
        )
    except StubActiveError:
        _print_stubs("Cannot write parameters while stubs are active:")
        raise
    results = [m.final_test for m in parameters.models]
    print(comparison_table(EvaluationReport(results=results)))
    print(f"\nParameters written to {config.output.parameters_file}")


def _print_stubs(heading: str) -> None:
    stubs = active_stubs()
    if stubs:
        print(f"\nSTUB  {heading}")
        for s in stubs:
            print(f"  STUB  {s}")


def _fleet_charging(config: CalibrationConfig, data: PriceDataset) -> FleetCharging:
    """The weighting scenario's net battery power over the years of ``data``.

    Runs from the first to the last day of ``data``, at the Agile prices
    of those days.  The run is cached under the data cache directory.
    """
    days = [obs.settlement_start.date() for obs in data.observations]
    start, end = max(min(days), config.data.start), max(days)
    cache_dir = Path(config.data.cache_dir)
    scenario = _SCENARIOS / f"{config.evaluation.weight_by_fleet_schedule}.toml"
    print(f"Fleet weights: {scenario.name}, {start} to {end}")
    charging = fleet_charging(
        scenario,
        start,
        end,
        price_source=HistoricalAgileSource(cache_dir=cache_dir),
        cache_dir=cache_dir,
        simulate=uncoordinated(_HOUSEHOLDS),
    )
    print(
        f"  {len(charging.slot_start_utc)} slots, "
        f"{len(charging.skipped_days)} days skipped\n"
    )
    return charging


def _provenance(config: CalibrationConfig, config_path: Path) -> Provenance:
    """The data, splits and fuel-cost settings, config hash and commit."""
    commit = _git("rev-parse", "HEAD")
    changed = _git("status", "--porcelain", "--untracked-files=no")
    return Provenance(
        data_start=config.data.start,
        data_end=config.data.end,
        agile_regions=config.data.agile_regions,
        splits=config.splits,
        fuel_cost=config.fuel_cost,
        config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        git_commit=commit,
        git_dirty=bool(changed),
        run_date=date.today(),
    )


def _git(*args: str) -> str:
    """Output of a git command in the repository, stripped."""
    return subprocess.run(
        ["git", *args], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _load_dataset(config: CalibrationConfig) -> PriceDataset:
    """Build and print the dataset.

    Censored slots stay in: fitting uses their price bounds.
    """
    dataset = build_dataset(config)
    _print_dataset(dataset)
    return dataset


def _print_dataset(dataset: PriceDataset) -> None:
    """Print slots dropped per rule, then rows and the range of π, R, k per year."""
    print(
        f"{'Year':<6} {'Expected':>9} {'No π':>6} "
        f"{'No R':>6} {'No k':>6} {'Kept':>7} {'Censored':>9}"
    )
    for d in dataset.drops:
        print(
            f"{d.year:<6} {d.expected_slots:>9} {d.missing_price:>6} "
            f"{d.missing_residual_load:>6} {d.missing_fuel_cost:>6} {d.kept:>7} "
            f"{d.censored:>9}"
        )
    print(
        f"\n{'Year':<6} {'Rows':>7} {'Censored':>9} "
        f"{'π mean [min, max] £/MWh':>28} "
        f"{'R mean [min, max] GW':>26} "
        f"{'k mean [min, max] £/MWh':>28}"
    )
    for s in summarise(dataset):
        price = _spread(
            s.price_mean_gbp_per_mwh, s.price_min_gbp_per_mwh, s.price_max_gbp_per_mwh
        )
        load = _spread(
            s.residual_load_mean_gw, s.residual_load_min_gw, s.residual_load_max_gw
        )
        cost = _spread(
            s.fuel_cost_mean_gbp_per_mwh,
            s.fuel_cost_min_gbp_per_mwh,
            s.fuel_cost_max_gbp_per_mwh,
        )
        print(
            f"{s.year:<6} {s.rows:>7} {s.censored_rows:>9} "
            f"{price:>28} {load:>26} {cost:>28}"
        )
    print()


def _spread(mean: float, low: float, high: float) -> str:
    return f"{mean:.1f} [{low:.1f}, {high:.1f}]"


if __name__ == "__main__":
    main()
