"""Evaluation figures from a saved report fixture."""

from pathlib import Path

from fleet_sim.prices.figures import EVALUATION_FIGURES, load_evaluation
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
