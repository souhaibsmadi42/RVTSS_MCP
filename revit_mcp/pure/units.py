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


def length_unit_for(kind, unit):
    """Adapt a unit to a quantity kind: mm -> mm2 for area, m2 stays m2, any -> deg for angles.

    A unit that already matches the kind is returned unchanged; an area/volume
    unit is reduced to its length base first (m2 -> m3 for volumes). An angle
    unit given for a dimensional kind falls back to millimetres.
    """
    if kind == "angle":
        u = normalize_unit(unit) if unit else "deg"
        return u if UNITS[u][0] == "angle" else "deg"
    if kind not in ("length", "area", "volume"):
        return None
    u = normalize_unit(unit) if unit else "mm"
    uk = UNITS[u][0]
    if uk == kind or uk == "any":
        return u
    if uk == "angle":
        base = "mm"
    elif uk in ("area", "volume"):
        base = u[:-1]
    else:
        base = u
    return {"length": base, "area": base + "2", "volume": base + "3"}[kind]


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
