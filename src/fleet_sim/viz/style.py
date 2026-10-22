"""Colours, fonts, and figure sizes for every plot.

Plots take these values from here. They do not choose their own.
"""

import matplotlib as mpl
from matplotlib.axes import Axes

INK = "#1f2933"
PAPER = "#ffffff"
GRIDLINE = "#e4e7eb"
PRICE = "#c2410c"
SOC = "#0f766e"
IMPORT_WITH_BATTERY = "#1d4e89"
IMPORT_WITHOUT_BATTERY = "#9aa5b1"
DIVERSE = "#1d4e89"
IDENTICAL = "#b45309"
BAND_ALPHA = 0.18

FONT_FAMILY = "DejaVu Sans"
FONT_SIZE = 11.0
LINE_WIDTH = 1.6
GRID_WIDTH = 0.6
PNG_DPI = 160
DAY_FIGURE_INCHES = (7.0, 6.2)
HERDING_FIGURE_INCHES = (7.2, 5.4)
PEAKS_FIGURE_INCHES = (7.2, 3.6)
PENETRATION_FIGURE_INCHES = (7.2, 3.6)
DIVERSITY_FIGURE_INCHES = (7.2, 3.8)


def apply_style() -> None:
    """Apply the house fonts and colours to matplotlib's global settings."""
    mpl.rcParams["font.family"] = "sans-serif"
    mpl.rcParams["font.sans-serif"] = [FONT_FAMILY]
    mpl.rcParams["font.size"] = FONT_SIZE
    mpl.rcParams["axes.labelsize"] = FONT_SIZE
    mpl.rcParams["axes.labelcolor"] = INK
    mpl.rcParams["axes.edgecolor"] = INK
    mpl.rcParams["axes.linewidth"] = 0.8
    mpl.rcParams["xtick.color"] = INK
    mpl.rcParams["ytick.color"] = INK
    mpl.rcParams["xtick.labelsize"] = FONT_SIZE
    mpl.rcParams["ytick.labelsize"] = FONT_SIZE
    mpl.rcParams["text.color"] = INK
    mpl.rcParams["figure.facecolor"] = PAPER
    mpl.rcParams["axes.facecolor"] = PAPER
    mpl.rcParams["savefig.facecolor"] = PAPER
    mpl.rcParams["legend.frameon"] = False
    mpl.rcParams["legend.fontsize"] = FONT_SIZE
    mpl.rcParams["svg.fonttype"] = "none"


def style_axes(ax: Axes) -> None:
    """Spines and grid for one panel, using the house colours."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(INK)
    ax.spines["bottom"].set_color(INK)
    ax.tick_params(colors=INK, width=0.8)
    ax.grid(True, color=GRIDLINE, linewidth=GRID_WIDTH)
