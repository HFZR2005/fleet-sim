"""Price-curve figures: from a saved report fixture, and from a small dataset."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.prices.curves import CubicFit, CubicOffsetFit, FittedCurve
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.evaluation import residuals
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
from fleet_sim.prices.targets import TARGETS
from fleet_sim.stubs import active_stubs, begin_stub_run
from fleet_sim.viz.save import save_figure

_FIXTURE = Path(__file__).parent / "fixtures" / "price_evaluation.json"


def test_evaluation_figures_render_without_stubs(tmp_path: Path) -> None:
    report = load_evaluation(_FIXTURE)
    begin_stub_run()

    for stem, plot in EVALUATION_FIGURES.items():
        svg_path, png_path = save_figure(plot(report), tmp_path / stem)
        assert "STUB" not in svg_path.read_text(encoding="utf-8")
        assert png_path.read_bytes().startswith(b"\x89PNG")

    assert active_stubs() == []


def test_dataset_figures_render_without_stubs(tmp_path: Path) -> None:
    # Twenty January days in each of two years, outside the Energy Price
    # Guarantee, with π = k·(0.5 + 0.001·R²) plus noise and a different k
    # each year.  Some 2021 slots are censored; the anchoring day is not.
    rng = np.random.default_rng(72)
    observations = []
    for year, cost in ((2021, 40.0), (2024, 60.0)):
        for d in range(20):
            for stamp in settlement_periods_utc(date(year, 1, 5) + timedelta(d)):
                load = float(rng.uniform(15.0, 35.0))
                price = cost * (0.5 + 0.001 * load**2) + float(rng.normal(0.0, 5.0))
                censored = year == 2021 and load > 33.0
                observations.append(
                    PriceObservation(
                        settlement_start=stamp,
                        wholesale_price_gbp_per_mwh=price,
                        censored=censored,
                        wholesale_upper_gbp_per_mwh=None,
                        residual_load_gw=load,
                        fuel_cost_gbp_per_mwh=cost,
                        year=year,
                    )
                )
    dataset = PriceDataset(observations=observations, drops=[])
    curves: dict[str, FittedCurve] = {
        "cubic": CubicFit(a=0.00003, sigma=0.1),
        "cubic_offset": CubicOffsetFit(a0=0.3, a1=0.02, a3=0.00002, sigma=0.1),
    }
    fits = {"raw_pooled": curves, "fuel_adjusted": curves}
    stamps = [o.settlement_start for o in observations]
    charging = FleetCharging(
        scenario="test",
        start=stamps[0].date(),
        end=stamps[-1].date(),
        slot_start_utc=stamps,
        net_battery_kw=[float(x) for x in rng.normal(0.0, 100.0, len(stamps))],
        skipped_days=[],
    )
    day = PriceDataset(observations=observations[-48:], drops=[])
    target = TARGETS["fuel_adjusted"]
    begin_stub_run()

    figures: dict[str, Figure] = {
        "fuel_adjustment": plot_fuel_adjustment(dataset),
        "fits": plot_fits(dataset, fits),
        "slopes": plot_slopes(dataset, fits, charging),
        "residuals": plot_residuals(
            dataset,
            {"fuel_adjusted/cubic": residuals(curves["cubic"], dataset, target)},
        ),
        "anchoring": plot_anchoring(
            day, curves, "fuel_adjusted", [2.0] * 10 + [0.0] * 38, region="C"
        ),
    }
    for stem, figure in figures.items():
        _, png_path = save_figure(figure, tmp_path / stem)
        assert png_path.read_bytes().startswith(b"\x89PNG")

    assert active_stubs() == []
