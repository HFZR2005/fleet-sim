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
from fleet_sim.prices.curves import FAMILIES, FittedCurve
from fleet_sim.prices.dataset import (
    PriceDataset,
    SplitSpec,
    load_and_align,
    split_dataset,
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
    """Run all (family, target) models and print a comparison."""
    begin_stub_run()
    dataset = load_and_align(config)

    results: list[FitResult] = []
    for family_name in config.models.families:
        family = FAMILIES[family_name]
        for target_name in config.models.targets:
            target = TARGETS[target_name]
            model_name = f"{target_name}/{family_name}"
            fit_result, fitted = _fit_and_evaluate(
                dataset, config, family_name, target_name, family, target, model_name
            )
            results.append(fit_result)

            output_dir = Path(config.output.results_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            fig = plot_price_vs_residual(dataset, fitted, target, title=model_name)
            save_figure(fig, output_dir / f"scatter_{model_name.replace('/', '_')}")

    report = EvaluationReport(results=results)
    output_dir = Path(config.output.results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_figure(plot_evaluation_summary(report), output_dir / "comparison")

    _print_report(report)

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
    dataset = load_and_align(config)

    chosen = config.chosen.main
    parts = chosen.split("/")
    if len(parts) != 2:
        raise ValueError(f"[chosen] main must be 'target/family' (got {chosen!r})")
    target_name, family_name = parts
    family = FAMILIES[family_name]
    target = TARGETS[target_name]

    fit_result, _fitted = _fit_and_evaluate(
        dataset,
        config,
        family_name,
        target_name,
        family,
        target,
        chosen,
        include_final_test=True,
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
    dataset: PriceDataset,
    config: CalibrationConfig,
    family_name: str,
    target_name: str,
    family: object,
    target: Target,
    model_name: str,
    *,
    include_final_test: bool = False,
) -> tuple[FitResult, FittedCurve]:
    """Transform, split, fit, and evaluate one model."""
    from fleet_sim.prices.curves import PriceCurve

    curve: PriceCurve = family  # type: ignore[assignment]

    if include_final_test:
        test_years = [config.splits.final_test_year]
        train_years = list(config.splits.training_years)
    else:
        test_years = _leave_one_out_years(config.splits.training_years)
        train_years = [y for y in config.splits.training_years if y not in test_years]

    spec = SplitSpec(
        train_years=train_years,
        test_years=test_years,
        final_test_year=config.splits.final_test_year,
    )
    train_data, test_data = split_dataset(dataset, spec)

    r_train = [obs.residual_load_gw for obs in train_data.observations]
    y_train = [target.to_target(obs) for obs in train_data.observations]
    fitted = curve.fit(r_train, y_train)

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


def _leave_one_out_years(training_years: list[int]) -> list[int]:
    """Stub split: use the last training year as the test year."""
    if len(training_years) < 2:
        raise ValueError("need at least 2 training years for leave-one-out")
    return [training_years[-1]]


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
