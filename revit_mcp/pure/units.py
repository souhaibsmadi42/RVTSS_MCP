# -*- coding: utf-8 -*-
"""Unit conversion between user units and Revit internal units.

Revit stores lengths in decimal feet, areas in square feet, volumes in cubic
feet and angles in radians. Conversions here are exact (1 ft = 304.8 mm) so
they do not depend on the Revit API and can be unit-tested offline.
"""
import math

_FT_PER = {
    "mm": 1.0 / 304.8,
    "cm": 1.0 / 30.48,
    "m": 1.0 / 0.3048,
    "ft": 1.0,
    "in": 1.0 / 12.0,
}

# unit -> (kind, factor to internal)
UNITS = {}
for _u, _f in _FT_PER.items():
    UNITS[_u] = ("length", _f)
    UNITS[_u + "2"] = ("area", _f ** 2)
    UNITS[_u + "3"] = ("volume", _f ** 3)
UNITS["deg"] = ("angle", math.pi / 180.0)
UNITS["rad"] = ("angle", 1.0)
UNITS["internal"] = ("any", 1.0)

ALIASES = {
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "centimeter": "cm", "centimeters": "cm",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "feet": "ft", "foot": "ft", "'": "ft",
    "inch": "in", "inches": "in", '"': "in",
    "degree": "deg", "degrees": "deg", u"°": "deg",
    "radian": "rad", "radians": "rad",
    "sqm": "m2", "m^2": "m2", "sqft": "ft2", "ft^2": "ft2", "mm^2": "mm2",
    "m^3": "m3", "ft^3": "ft3", "cum": "m3",
}


class UnitError(ValueError):
    pass


def normalize_unit(unit):
    if unit is None:
        return None
    u = unit.strip().lower()
    u = ALIASES.get(u, u)
    if u not in UNITS:
        raise UnitError("Unknown unit '%s'. Supported: %s" % (unit, ", ".join(sorted(UNITS))))
    return u


def unit_kind(unit):
    return UNITS[normalize_unit(unit)][0]


def to_internal(value, unit):
    """Convert value expressed in `unit` to Revit internal units."""
    if unit is None:
        return float(value)
    return float(value) * UNITS[normalize_unit(unit)][1]


def from_internal(value, unit, ndigits=None):
    """Convert a Revit internal value to `unit`."""
    if value is None:
        return None
    if unit is None:
        out = float(value)
    else:
        out = float(value) / UNITS[normalize_unit(unit)][1]
    if ndigits is not None:
        out = round(out, ndigits)
    return out


def length_unit_for(kind, length_unit):
    """Return the matching area/volume unit for a length unit (e.g. mm -> mm2)."""
    base = normalize_unit(length_unit)
    if kind == "length":
        return base
    if kind == "area":
        return base + "2"
    if kind == "volume":
        return base + "3"
    if kind == "angle":
        return "deg"
    return None


def point_from(values, unit):
    """[x, y, z] in `unit` -> tuple of internal feet. Accepts 2D (z=0)."""
    vals = list(values)
    if len(vals) == 2:
        vals.append(0.0)
    if len(vals) != 3:
        raise UnitError("A point needs 2 or 3 coordinates, got %d" % len(vals))
    return tuple(to_internal(v, unit) for v in vals)


def point_to(xyz, unit, ndigits=3):
    return [from_internal(c, unit, ndigits) for c in xyz]
