# -*- coding: utf-8 -*-
"""Revit-independent helpers for rooms / spaces / areas (RVTSS v2.2)."""

# Warning texts Revit raises for spatial elements (English UI); used to split
# "placed with zero area" into not enclosed vs redundant. Localised Revit builds
# fall back to the generic "not_enclosed_or_redundant".
NOT_ENCLOSED_MARKERS = ("not in a properly enclosed region", "not enclosed")
REDUNDANT_MARKERS = ("same enclosed region", "redundant")


def classify_warning(text):
    t = (text or "").lower()
    if any(m in t for m in REDUNDANT_MARKERS):
        return "redundant"
    if any(m in t for m in NOT_ENCLOSED_MARKERS):
        return "not_enclosed"
    return None


def spatial_status(placed, area, warning_kind=None):
    """placed | unplaced | not_enclosed | redundant | not_enclosed_or_redundant."""
    if not placed:
        return "unplaced"
    if area and area > 1e-9:
        return "placed"
    return warning_kind or "not_enclosed_or_redundant"


def wall_finish(segment_length, height, openings=()):
    """Net wall area of one boundary segment: length x height minus openings (width x height).

    Inputs in any consistent unit; openings that do not fit are clamped so the
    net area is never negative. Returns (gross, openings_area, net).
    """
    gross = max(0.0, float(segment_length or 0.0)) * max(0.0, float(height or 0.0))
    holes = 0.0
    for w, h in openings or ():
        holes += max(0.0, float(w or 0.0)) * max(0.0, float(h or 0.0))
    holes = min(holes, gross)
    return gross, holes, gross - holes


def summarize_by(items, key, value_keys=("area",)):
    """Group dict items by key with counts and sums of value_keys (rounded to 3 decimals)."""
    out = {}
    for it in items:
        k = it.get(key)
        k = "(none)" if k in (None, "") else k
        g = out.setdefault(k, {"count": 0})
        g["count"] += 1
        for vk in value_keys:
            v = it.get(vk)
            if isinstance(v, (int, float)):
                g[vk] = round(g.get(vk, 0.0) + v, 3)
    return out
