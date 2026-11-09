"""Fit and compare price-curve models, or finalise the chosen model.

Not run in CI.  Invoke with::

    uv run python scripts/fit_price_curves.py compare
    uv run python scripts/fit_price_curves.py finalise
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fleet_sim.data.agile_history import HistoricalAgileSource
from fleet_sim.prices.config import CalibrationConfig, load_config
from fleet_sim.prices.curves import FAMILIES, FittedCurve, PriceCurve
from fleet_sim.prices.dataset import (
    Fold,
    PriceDataset,
    build_dataset,
    final_test_split,
    selection_data,
    selection_folds,
    summarise,
)
from fleet_sim.prices.evaluation import (
    Bracket,
    EvaluationReport,
    FitResult,
    ResidualSeries,
    Split,
    bracket,
    comparison_table,
    evaluate,
    residuals,
)
from fleet_sim.prices.figures import (
    EVALUATION_FIGURES,
    load_evaluation,
    plot_price_vs_residual,
)
from fleet_sim.prices.fleet_weights import (
    FleetCharging,
    fleet_charging,
    uncoordinated,
)
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
_SCENARIOS = _ROOT / "scenarios"
_HOUSEHOLDS = _ROOT / ".cache" / "lcl" / "LCL-FullData.zip"


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
    """Fit and score every (family, target) model on the training years.

    Pooled targets are fitted on all but one year and scored on that
    year (leave-one-year-out).  Per-year targets are fitted to each year
    on its own and scored on the same year: a curve for one year has no
    other year to predict.  Only the training years are read; the
    final-test year is left out.
    """
    begin_stub_run()
    dataset = _load_dataset(config)
    selection = selection_data(dataset, config.splits)
    folds = selection_folds(dataset, config.splits)
    charging = _fleet_charging(config, selection)

    output_dir = Path(config.output.results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[FitResult] = []
    for family_name in config.models.families:
        family = FAMILIES[family_name]
        for target_name in config.models.targets:
            target = TARGETS[target_name]
            model_name = f"{target_name}/{family_name}"
            for train, test, split in _splits(target, folds):
                fit_result, _fitted = _fit_and_evaluate(
                    train,
                    test,
                    family_name,
                    target_name,
                    family,
                    target,
                    model_name,
                    charging,
                    split,
                )
                all_results.append(fit_result)

            fitted = _fit(family, target, selection)
            fig = plot_price_vs_residual(selection, fitted, target, title=model_name)
            save_figure(fig, output_dir / f"scatter_{model_name.replace('/', '_')}")

    report = EvaluationReport(results=all_results, brackets=_brackets(config, folds))
    report_path = output_dir / "evaluation.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    saved = load_evaluation(report_path)
    for stem, plot in EVALUATION_FIGURES.items():
        save_figure(plot(saved), output_dir / stem)
    table = comparison_table(report)
    (output_dir / "comparison.md").write_text(table, encoding="utf-8")
    print(table)
    _write_residuals(config, selection, folds, output_dir)

    stubs = active_stubs()
    if stubs:
        print("\nSTUB  Active stubs:")
        for s in stubs:
            print(f"  STUB  {s}")


def _brackets(config: CalibrationConfig, folds: list[Fold]) -> list[Bracket]:
    """Each family fitted to each training year alone, three ways.

    A year fitted alone doesn't depend on pooling, so a target is skipped
    when an earlier one uses the same transform (``raw_per_year`` after
    ``raw_pooled``); rows carry the first target's name.
    """
    brackets: list[Bracket] = []
    transforms: set[type] = set()
    for target_name in config.models.targets:
        target = TARGETS[target_name]
        if type(target) in transforms:
            continue
        transforms.add(type(target))
        for family_name in config.models.families:
            for fold in folds:
                brackets += bracket(
                    FAMILIES[family_name],
                    fold.test,
                    target,
                    model_name=f"{target_name}/{family_name}",
                    curve_family=family_name,
                    target_name=target_name,
                )
    return brackets


def _splits(
    target: Target, folds: list[Fold]
) -> list[tuple[PriceDataset, PriceDataset, Split]]:
    """``(train, test, split)`` for each year a target is scored on."""
    if target.per_year:
        return [(fold.test, fold.test, "in-sample") for fold in folds]
    return [(fold.train, fold.test, "held-out") for fold in folds]


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


def _write_residuals(
    config: CalibrationConfig,
    selection: PriceDataset,
    folds: list[Fold],
    output_dir: Path,
) -> None:
    """Residuals on the training years for each model named in ``[chosen]``.

    A per-year model is fitted to each year and its residuals joined.
    """
    chosen = [m for m in (config.chosen.main, config.chosen.robustness) if m]
    if not chosen:
        print("\nNo model in [chosen] yet, so no residuals written.")
        return
    for model_name in chosen:
        target_name, family_name = _parse_model(model_name)
        target = TARGETS[target_name]
        family = FAMILIES[family_name]
        years = [fold.test for fold in folds] if target.per_year else [selection]
        slots = [
            slot
            for data in years
            for slot in residuals(_fit(family, target, data), data, target)
        ]
        path = output_dir / f"residuals_{target_name}_{family_name}.json"
        path.write_text(
            ResidualSeries(model_name=model_name, slots=slots).model_dump_json() + "\n",
            encoding="utf-8",
        )
        print(f"Residuals for {model_name} written to {path}")


def _finalise(config: CalibrationConfig) -> None:
    """Fit the chosen model on all training data and write parameters."""
    if not config.chosen.main:
        raise ValueError("[chosen] main is empty — run compare first and pick a model")
    begin_stub_run()
    dataset = _load_dataset(config)
    train_data, test_data = final_test_split(dataset, config.splits)

    chosen = config.chosen.main
    target_name, family_name = _parse_model(chosen)
    family = FAMILIES[family_name]
    target = TARGETS[target_name]

    fit_result, _fitted = _fit_and_evaluate(
        train_data,
        test_data,
        family_name,
        target_name,
        family,
        target,
        chosen,
        _fleet_charging(config, test_data),
        "held-out",
    )

    print(comparison_table(EvaluationReport(results=[fit_result])))

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


def _parse_model(model_name: str) -> tuple[str, str]:
    """``(target, family)`` from a ``target/family`` model name."""
    parts = model_name.split("/")
    if len(parts) != 2:
        raise ValueError(f"model must be 'target/family' (got {model_name!r})")
    return parts[0], parts[1]


def _load_dataset(config: CalibrationConfig) -> PriceDataset:
    """Build and print the dataset.

    Censored slots stay in: fitting uses their price bounds.
    """
    dataset = build_dataset(config)
    _print_dataset(dataset)
    return dataset


def _fit_and_evaluate(
    train_data: PriceDataset,
    test_data: PriceDataset,
    family_name: str,
    target_name: str,
    family: PriceCurve,
    target: Target,
    model_name: str,
    charging: FleetCharging,
    split: Split,
) -> tuple[FitResult, FittedCurve]:
    """Fit one model on ``train_data`` and score it on ``test_data``."""
    fitted = _fit(family, target, train_data)
    result = evaluate(
        fitted,
        train_data,
        test_data,
        target,
        charging,
        model_name=model_name,
        curve_family=family_name,
        target_name=target_name,
        split=split,
    )
    return result, fitted


def _fit(family: PriceCurve, target: Target, data: PriceDataset) -> FittedCurve:
    """Fit ``family`` to residual load and bounds on ``y`` from ``data``."""
    r = [obs.residual_load_gw for obs in data.observations]
    bounds = [target.to_target_bounds(obs) for obs in data.observations]
    return family.fit(r, [b[0] for b in bounds], [b[1] for b in bounds])


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
