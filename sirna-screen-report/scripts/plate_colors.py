"""
Color/layout assignment logic for siRNA screen QC Fig 1 (representative plate map).

Why this is bundled instead of left as prose in SKILL.md: every past run re-derived
this from scratch in a fresh code cell, which is exactly the kind of repeated,
deterministic work that should be written once and reused. It also bakes in the
two recurring well-indexing gotchas (well_row is an int 1-8, not a letter; well_column
in confluence_data is int64) directly into the helper functions, so a future run can't
reintroduce that bug by accident.

This module has no third-party dependencies except matplotlib (only needed for the
10-pt DRC colormap lookup).

Usage pattern from the notebook:
    from plate_colors import (
        well_row_to_y, SINGLE_DOSE_COLORS, classify_dose_3pt,
        get_compound_color_3pt, get_10pt_shade, POSITIVE_CONTROL_COLOR_3PT,
        POSITIVE_CONTROL_COLOR_10PT, SIPPIB_COLOR_10PT,
    )
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared well-position helper (gotcha: well_row is int 1-8, not a letter)
# ---------------------------------------------------------------------------

def well_row_to_y(well_row) -> int:
    """Convert a 1-8 well_row (int or numeric string) to a plotting y-coordinate
    where row 1 (A) is drawn at the top of an 8-row plate.

    row_idx = int(well_row) - 1   # 0-based
    y = 7 - row_idx               # flip so row 1 is at the top
    """
    row_idx = int(well_row) - 1
    return 7 - row_idx


def well_column_to_x(well_column) -> int:
    """well_column in confluence_data is int64 -- always coerce with int() before
    using it as an index or comparing against a literal, never compare to a str."""
    return int(well_column) - 1


# ---------------------------------------------------------------------------
# Single-dose arrayed design
# ---------------------------------------------------------------------------

SINGLE_DOSE_COLORS = {
    "sample": "#4C9BE8",
    "positive_ctrl": "#E84C4C",
    "mock": "#A8D5A2",
    "empty": "#eeeeee",
}


# ---------------------------------------------------------------------------
# 3-pt DRC design (6 compounds x 3 doses)
# ---------------------------------------------------------------------------

# Darkest = highest dose. Slot index is 0-based, assigned in the order compounds
# are first encountered on the plate -- NOT tied to any specific gene/compound name.
COMPOUND_FAMILIES_3PT = [
    ("#4527A0", "#7E57C2", "#CE93D8"),  # slot 0 - purple
    ("#00695C", "#26A69A", "#80CBC4"),  # slot 1 - teal
    ("#BF360C", "#FF7043", "#FFAB91"),  # slot 2 - orange-red
    ("#880E4F", "#EC407A", "#F48FB1"),  # slot 3 - pink
    ("#4E342E", "#8D6E63", "#BCAAA4"),  # slot 4 - brown
    ("#B71C1C", "#EF5350", "#EF9A9A"),  # slot 5 - red
]

# siPPIB is the positive control on every screen -- fixed color, outside the rotation.
POSITIVE_CONTROL_COLOR_3PT = "#2E7D32"

# Dose-tier thresholds in uM. Confirm these against the actual screen's nominal
# doses before relying on them -- they were derived from a 20/2/0.2 nM 3-pt design.
DOSE_THRESHOLDS_3PT_UM = {"high": 0.015, "mid": 0.0015}


def classify_dose_3pt(conc_um: float) -> str:
    """Bucket a 3-pt DRC concentration (in uM) into 'high' / 'mid' / 'low'."""
    if conc_um >= DOSE_THRESHOLDS_3PT_UM["high"]:
        return "high"
    if conc_um >= DOSE_THRESHOLDS_3PT_UM["mid"]:
        return "mid"
    return "low"


_TIER_INDEX = {"high": 0, "mid": 1, "low": 2}


def get_compound_color_3pt(slot_index: int, dose_tier: str) -> str:
    """Look up the hex color for a generic-rotation compound.

    slot_index: 0-based index in the order this compound was first seen on the
        plate (excluding siPPIB and any one-off named-target override -- see below).
    dose_tier: 'high' / 'mid' / 'low', e.g. from classify_dose_3pt().
    """
    family = COMPOUND_FAMILIES_3PT[slot_index % len(COMPOUND_FAMILIES_3PT)]
    return family[_TIER_INDEX[dose_tier]]


def get_named_target_color(compound_name: str, screen_overrides: dict[str, str]) -> str:
    """If a screen includes a named-target SmartPool (a specific gene's pooled
    siRNA) that should visually stand out from the generic 6-family rotation,
    assign it a one-off color here -- per-screen, via `screen_overrides`
    ({"GENEX SmartPool": "#1565C0"}), not hardcoded into this module. Document
    the choice (and why) in that screen's notebook README cell.
    """
    if compound_name not in screen_overrides:
        raise KeyError(
            f"{compound_name!r} has no entry in screen_overrides -- assign it a "
            "color in the notebook before calling this function, don't guess."
        )
    return screen_overrides[compound_name]


# ---------------------------------------------------------------------------
# 10-pt DRC design (2 compounds x 10 doses, serial dilution)
# ---------------------------------------------------------------------------

POSITIVE_CONTROL_COLOR_10PT = "#1565C0"
SIPPIB_COLOR_10PT = "#2E7D32"

# Reversed so index 0 (highest concentration) renders darkest.
COMPOUND_COLORMAPS_10PT = {
    1: "PuBu_r",
    2: "BuGn_r",
}


def get_10pt_shade(conc_um: float, concentrations_desc: list[float], compound_slot: int):
    """Map a concentration to an RGBA color along a compound's colormap.

    concentrations_desc: this compound's distinct concentrations, sorted
        descending (index 0 = highest dose = darkest shade).
    compound_slot: 1 or 2, selects which colormap family per COMPOUND_COLORMAPS_10PT.
    """
    import matplotlib.cm as cm

    idx = concentrations_desc.index(conc_um)
    frac = idx / max(len(concentrations_desc) - 1, 1)
    cmap = cm.get_cmap(COMPOUND_COLORMAPS_10PT[compound_slot])
    return cmap(frac)
