"""Compare price-curve models, and finalise the chosen ones.

The two modes of ``scripts/fit_price_curves.py``, without the data
loading: the caller builds the dataset, the fleet's charging and the
provenance, and starts the stub run.  ``compare`` fits and scores every
(family, target) model on the training years and never reads the
final-test year.  ``finalise`` refits the ``[chosen]`` models, scores
them once on the final-test year, and writes the parameters file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from fleet_sim.prices.config import CalibrationConfig
from fleet_sim.prices.curves import FAMILIES, FittedCurve, PriceCurve
from fleet_sim.prices.dataset import (
    Fold,
    PriceDataset,
    final_test_split,
    selection_data,
    selection_folds,
)
from fleet_sim.prices.evaluation import (
    Bracket,
    EvaluationReport,
    FitResult,
    ResidualSeries,
    SlotResidual,
    Split,
    bracket,
    comparison_table,
    evaluate,
    residuals,
)
from fleet_sim.prices.figures import (
    EVALUATION_FIGURES,
    load_evaluation,
    plot_anchoring,
    plot_fits,
    plot_fuel_adjustment,
    plot_residuals,
    plot_slopes,
)
from fleet_sim.prices.fleet_weights import FleetCharging
from fleet_sim.prices.parameters import (
    CurveParameters,
    PriceParameters,
    Provenance,
    SavedModel,
    saved_curve,
)
from fleet_sim.prices.targets import TARGETS, Target
from fleet_sim.stubs import require_no_stubs
from fleet_sim.viz.save import save_figure

_LONDON = ZoneInfo("Europe/London")
# The anchoring example: a winter weekday outside the Energy Price
# Guarantee, with 2 GW added overnight (00:00 to 05:00 UK time).
_ANCHOR_DAY = date(2024, 1, 17)
_ANCHOR_ADDED_GW = 2.0
_ANCHOR_UNTIL_HOUR = 5


class CompareResult(BaseModel):
    """What ``compare`` wrote: the report, its table, and residual files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report: EvaluationReport
    table: str
    residual_paths: dict[str, Path]


def compare(
    config: CalibrationConfig,
    dataset: PriceDataset,
    charging: FleetCharging,
    residual_models: list[str],
) -> CompareResult:
    """Fit and score every (family, target) model on the training years.

    Pooled targets are fitted on all but one year and scored on that
    year (leave-one-year-out).  Per-year targets are fitted to each year
    on its own and scored on the same year: a curve for one year has no
    other year to predict.  Only the training years are read; the
    final-test year is left out.  ``charging`` is the fleet's net battery
    power over the training years.  Writes ``evaluation.json``,
    ``comparison.md``, the figures, and residuals for each of
    ``residual_models`` to ``config.output.results_dir``.
    """
    selection = selection_data(dataset, config.splits)
    folds = selection_folds(dataset, config.splits)
    output_dir = Path(config.output.results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[FitResult] = []
    fits: dict[str, dict[str, FittedCurve]] = {}
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

            if not target.per_year:
                fits.setdefault(target_name, {})[family_name] = _fit(
                    family, target, selection
                )

    report = EvaluationReport(results=all_results, brackets=_brackets(config, folds))
    report_path = output_dir / "evaluation.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    saved = load_evaluation(report_path)
    for stem, plot in EVALUATION_FIGURES.items():
        save_figure(plot(saved), output_dir / stem)
    table = comparison_table(report)
    (output_dir / "comparison.md").write_text(table, encoding="utf-8")

    save_figure(plot_fuel_adjustment(selection), output_dir / "fuel_adjustment")
    save_figure(plot_fits(selection, fits), output_dir / "fits")
    save_figure(plot_slopes(selection, fits, charging), output_dir / "slopes")
    if "fuel_adjusted" in fits:
        day = _anchor_day(selection)
        added = [
            _ANCHOR_ADDED_GW
            if o.settlement_start.astimezone(_LONDON).hour < _ANCHOR_UNTIL_HOUR
            else 0.0
            for o in day.observations
        ]
        figure = plot_anchoring(
            day,
            fits["fuel_adjusted"],
            "fuel_adjusted",
            added,
            region=config.data.agile_regions[0],
        )
        save_figure(figure, output_dir / "anchoring")
    model_residuals, residual_paths = _write_residuals(
        residual_models, selection, folds, output_dir
    )
    if model_residuals:
        save_figure(
            plot_residuals(selection, model_residuals), output_dir / "residuals"
        )
    return CompareResult(report=report, table=table, residual_paths=residual_paths)


def finalise(
    config: CalibrationConfig,
    dataset: PriceDataset,
    charging: FleetCharging,
    provenance: Provenance,
) -> PriceParameters:
    """Refit the chosen models and score them on the final-test year, once.

    A pooled model is fitted on all training years and scored on the
    final-test year.  A per-year model is fitted to each training year
    and to the final-test year, and scored in-sample on the final-test
    year, as ``compare`` scores it.  ``charging`` is the fleet's net
    battery power over the final-test year.

    Refuses to run if the parameters file exists: the final-test year is
    read once, and rerunning means deleting that file on purpose.  Raises
    ``StubActiveError``, and writes nothing, if a stub ran since the
    caller began the stub run.
    """
    if not config.chosen.main:
        raise ValueError("[chosen] main is empty — run compare first and pick a model")
    chosen = [config.chosen.main, *config.chosen.robustness]
    params_path = Path(config.output.parameters_file)
    if params_path.exists():
        raise FileExistsError(
            f"{params_path} exists, so the final test has been run; "
            "delete it to run again"
        )

    train_data, test_data = final_test_split(dataset, config.splits)
    final_year = config.splits.final_test_year

    models: list[SavedModel] = []
    for model_name in chosen:
        target_name, family_name = parse_model(model_name)
        family = FAMILIES[family_name]
        target = TARGETS[target_name]
        split: Split
        curve: CurveParameters | None
        curves_by_year: dict[int, CurveParameters] | None
        if target.per_year:
            by_year = {
                fold.held_out_year: _fit(family, target, fold.test)
                for fold in selection_folds(dataset, config.splits)
            }
            by_year[final_year] = _fit(family, target, test_data)
            fitted = by_year[final_year]
            fit_train, split = test_data, "in-sample"
            curve = None
            curves_by_year = {y: saved_curve(c) for y, c in by_year.items()}
        else:
            fitted = _fit(family, target, train_data)
            fit_train, split = train_data, "held-out"
            curve = saved_curve(fitted)
            curves_by_year = None
        result = evaluate(
            fitted,
            fit_train,
            test_data,
            target,
            charging,
            model_name=model_name,
            curve_family=family_name,
            target_name=target_name,
            split=split,
        )
        models.append(
            SavedModel(
                name=model_name,
                target=target_name,
                family=family_name,
                curve=curve,
                curves_by_year=curves_by_year,
                final_test=result,
            )
        )

    require_no_stubs()
    parameters = PriceParameters(provenance=provenance, models=models)
    params_path.parent.mkdir(parents=True, exist_ok=True)
    params_path.write_text(
        parameters.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return parameters


def parse_model(model_name: str) -> tuple[str, str]:
    """``(target, family)`` from a ``target/family`` model name."""
    parts = model_name.split("/")
    if len(parts) != 2:
        raise ValueError(f"model must be 'target/family' (got {model_name!r})")
    return parts[0], parts[1]


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


def _anchor_day(selection: PriceDataset) -> PriceDataset:
    """The slots of ``_ANCHOR_DAY``, a UK day, from ``selection``."""
    return PriceDataset(
        observations=[
            o
            for o in selection.observations
            if o.settlement_start.astimezone(_LONDON).date() == _ANCHOR_DAY
        ],
        drops=[],
    )


def _write_residuals(
    models: list[str],
    selection: PriceDataset,
    folds: list[Fold],
    output_dir: Path,
) -> tuple[dict[str, list[SlotResidual]], dict[str, Path]]:
    """Residuals on the training years for each of ``models``, and their files.

    A per-year model is fitted to each year and its residuals joined.
    """
    written: dict[str, list[SlotResidual]] = {}
    paths: dict[str, Path] = {}
    for model_name in models:
        target_name, family_name = parse_model(model_name)
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
        written[model_name] = slots
        paths[model_name] = path
    return written, paths


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
