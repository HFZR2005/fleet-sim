"""Write a figure as SVG and PNG."""

from pathlib import Path

from matplotlib.figure import Figure

from fleet_sim.viz.style import PNG_DPI


def save_figure(figure: Figure, stem: Path) -> tuple[Path, Path]:
    """Save ``stem`` as an SVG and a PNG.

    The suffix of ``stem`` is replaced, so ``figures/day`` and
    ``figures/day.png`` both write ``day.svg`` and ``day.png``.
    """
    svg_path = stem.with_suffix(".svg")
    png_path = stem.with_suffix(".png")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(svg_path, format="svg")
    figure.savefig(png_path, format="png", dpi=PNG_DPI)
    return svg_path, png_path
