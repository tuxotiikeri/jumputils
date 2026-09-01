"""Shared report colors, labels and axis formatting."""

from matplotlib.ticker import FuncFormatter


METROPOLIA_ORANGE = "#ff5000"
METROPOLIA_GREY = "#53565a"
METROPOLIA_DARK = "#363e3c"
LEFT_RED = "#d62839"
RIGHT_BLUE = "#2563eb"
BAR_GREY = "#636363"
GREY_DASH = "#8d9196"
LEFT_FILL = (214 / 255.0, 40 / 255.0, 57 / 255.0, 0.18)
RIGHT_FILL = (37 / 255.0, 99 / 255.0, 235 / 255.0, 0.18)

AXIS_LABEL_ANGLES = {
    "X": "EXT (-) / FLX (+)",
    "Y": "ABD (-) / ADD (+)",
    "Z": "EXT (-) / INT (+)",
}
AXIS_LABEL_MOMENT = {
    "X": "EXT (-) / FLX (+)",
    "Y": "ABD (-) / ADD (+)",
    "Z": "EXT (-) / INT (+)",
}
DECIMAL_FMT = FuncFormatter(lambda x, pos: f"{x:g}".replace(".", ","))
