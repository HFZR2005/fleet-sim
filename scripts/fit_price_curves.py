"""Fit and compare price-curve models, or finalise the chosen model.

Not run in CI.  Invoke with::

    uv run python scripts/fit_price_curves.py compare
    uv run python scripts/fit_price_curves.py finalise
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fleet_sim.prices.config import CalibrationConfig, load_config
from fleet_sim.prices.curves import FAMILIES, FittedCurve, PriceCurve
from fleet_sim.prices.dataset import (
    PriceDataset,
    build_dataset,
    final_test_split,
    selection_data,
    selection_folds,
    summarise,
)
from fleet_sim.prices.evaluation import EvaluationReport, FitResult, evaluate
from fleet_sim.prices.figures import plot_evaluation_summary, plot_price_vs_residual
from fleet_sim.prices.targets import TARGETS, Target
from fleet_sim.stubs import (
    StubActiveError,
    active_stubs,
    begin_stub_run,
    require_no_stubs,
)
from fleet_sim.viz.save import save_figure

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG = _ROOT / "calibration" / "price_curves.toml"


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("compare", "finalise"):
        print("Usage: python scripts/fit_price_curves.py {compare|finalise}")
        sys.exit(1)
    mode = sys.argv[1]
    config = load_config(_DEFAULT_CONFIG)
    if mode == "compare":
        _compare(config)
    else:
        _finalise(config)


def _compare(config: CalibrationConfig) -> None:
    """Fit every (family, target) model on each leave-one-year-out fold.

    Only the training years are read; the final-test year is left out.
    """
    begin_stub_run()
    dataset = build_dataset(config)
    _print_dataset(dataset)
    selection = selection_data(dataset, config.splits)
    folds = selection_folds(dataset, config.splits)

    output_dir = Path(config.output.results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results_by_year: dict[int, list[FitResult]] = {f.held_out_year: [] for f in folds}
    all_results: list[FitResult] = []
    for family_name in config.models.families:
        family = FAMILIES[family_name]
        for target_name in config.models.targets:
            target = TARGETS[target_name]
            model_name = f"{target_name}/{family_name}"
            for fold in folds:
                fit_result, _fitted = _fit_and_evaluate(
                    fold.train,
                    fold.test,
                    family_name,
                    target_name,
                    family,
                    target,
                    model_name,
                )
                results_by_year[fold.held_out_year].append(fit_result)
                all_results.append(fit_result)

            fitted = _fit(family, target, selection)
            fig = plot_price_vs_residual(selection, fitted, target, title=model_name)
            save_figure(fig, output_dir / f"scatter_{model_name.replace('/', '_')}")

    save_figure(
        plot_evaluation_summary(EvaluationReport(results=all_results)),
        output_dir / "comparison",
    )

    for year, results in results_by_year.items():
        print(f"\nHeld out {year}")
        _print_report(EvaluationReport(results=results))

    stubs = active_stubs()
    if stubs:
        print("\nSTUB  Active stubs:")
        for s in stubs:
            print(f"  STUB  {s}")


def _finalise(config: CalibrationConfig) -> None:
    """Fit the chosen model on all training data and write parameters."""
    if not config.chosen.main:
        raise ValueError("[chosen] main is empty — run compare first and pick a model")
    begin_stub_run()
    dataset = build_dataset(config)
    _print_dataset(dataset)
    train_data, test_data = final_test_split(dataset, config.splits)

    chosen = config.chosen.main
    parts = chosen.split("/")
    if len(parts) != 2:
        raise ValueError(f"[chosen] main must be 'target/family' (got {chosen!r})")
    target_name, family_name = parts
    family = FAMILIES[family_name]
    target = TARGETS[target_name]

    fit_result, _fitted = _fit_and_evaluate(
        train_data, test_data, family_name, target_name, family, target, chosen
    )

    _print_report(EvaluationReport(results=[fit_result]))

    try:
        require_no_stubs()
    except StubActiveError:
        stubs = active_stubs()
        print("\nSTUB  Cannot write parameters while stubs are active:")
        for s in stubs:
            print(f"  STUB  {s}")
        raise

    params_path = Path(config.output.parameters_file)
    params_path.parent.mkdir(parents=True, exist_ok=True)
    params_path.write_text(
        json.dumps(fit_result.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nParameters written to {params_path}")


def _fit_and_evaluate(
    train_data: PriceDataset,
    test_data: PriceDataset,
    family_name: str,
    target_name: str,
    family: PriceCurve,
    target: Target,
    model_name: str,
) -> tuple[FitResult, FittedCurve]:
    """Fit one model on ``train_data`` and score it on ``test_data``."""
    fitted = _fit(family, target, train_data)
    result = evaluate(
        fitted,
        train_data,
        test_data,
        target,
        model_name=model_name,
        curve_family=family_name,
        target_name=target_name,
    )
    return result, fitted


def _fit(family: PriceCurve, target: Target, data: PriceDataset) -> FittedCurve:
    """Fit ``family`` to ``(R, y)`` pairs taken from ``data``."""
    r = [obs.residual_load_gw for obs in data.observations]
    y = [target.to_target(obs) for obs in data.observations]
    return family.fit(r, y)


def _print_dataset(dataset: PriceDataset) -> None:
    """Print slots dropped per rule, then rows and the range of π, R, k per year."""
    print(
        f"{'Year':<6} {'Expected':>9} {'Capped':>7} {'No π':>6} "
        f"{'No R':>6} {'No k':>6} {'Kept':>7}"
    )
    for d in dataset.drops:
        print(
            f"{d.year:<6} {d.expected_slots:>9} {d.capped:>7} {d.missing_price:>6} "
            f"{d.missing_residual_load:>6} {d.missing_fuel_cost:>6} {d.kept:>7}"
        )
    print(
        f"\n{'Year':<6} {'Rows':>7} "
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
        print(f"{s.year:<6} {s.rows:>7} {price:>28} {load:>26} {cost:>28}")
    print()


def _spread(mean: float, low: float, high: float) -> str:
    return f"{mean:.1f} [{low:.1f}, {high:.1f}]"


def _print_report(report: EvaluationReport) -> None:
    """Print the evaluation report as a simple table."""
    header = f"{'Model':<30} {'Train RMSE':>12} {'Test RMSE':>12} {'Train R²':>10} {'Test R²':>10}"
    print(header)
    print("-" * len(header))
    for r in report.results:
        print(
            f"{r.model_name:<30} {r.train_rmse:>12.4f} {r.test_rmse:>12.4f} "
            f"{r.train_r2:>10.4f} {r.test_r2:>10.4f}"
        )


if __name__ == "__main__":
    main()
