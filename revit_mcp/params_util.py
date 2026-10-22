# -*- coding: UTF-8 -*-
"""Parameter lookup, reading and writing with explicit unit handling.

Writing rules (set_value):
  * String parameters: value is converted to text.
  * Integer parameters: ints, booleans and "yes"/"no" for Yes/No parameters.
  * Double parameters with a measurable spec (length, area, angle...):
      - number + unit ("mm", "m", "ft", "deg"...) -> converted exactly, or
      - string with units ("900 mm", "3'-0\"") -> Parameter.SetValueString,
      - a bare number without unit is REJECTED (prevents 900 being read as 900 ft).
    unit="internal" passes Revit internal units through unchanged.
  * Double parameters without units (Number): numbers are set directly.
  * ElementId parameters: an element id, or a name for material/level parameters.
"""
import re

from pyrevit import DB
import System

from .compat import (make_id, id_int, text_type, definition_spec, definition_group,
                     is_valid_id)
from .core import RvtssError, to_text
from .pure import units as U
from .utils import normalize_string, get_element_name

try:
    basestring  # noqa: F821
except NameError:
    basestring = str

_GUID_RX = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def lookup(element, name):
    """Parameter by name, BuiltInParameter name (e.g. 'ALL_MODEL_MARK') or shared GUID."""
    if element is None or not name:
        return None
    if isinstance(name, basestring):
        n = name.strip()
        if _GUID_RX.match(n):
            try:
                return element.get_Parameter(System.Guid(n))
            except Exception:
                return None
        if n.isupper() and "_" in n:
            bip = getattr(DB.BuiltInParameter, n, None)
            if bip is not None:
                p = element.get_Parameter(bip)
                if p is not None:
                    return p
        p = element.LookupParameter(n)
        if p is not None:
            return p
        # case-insensitive fallback
        low = n.lower()
        for q in element.Parameters:
            if normalize_string(q.Definition.Name).lower() == low:
                return q
    return None


def find(doc, element, name, allow_type=True):
    """Return (parameter, owner) where owner is 'instance' or 'type'."""
    p = lookup(element, name)
    if p is not None:
        return p, ("type" if isinstance(element, DB.ElementType) else "instance")
    if allow_type and not isinstance(element, DB.ElementType):
        try:
            tid = element.GetTypeId()
            if is_valid_id(tid):
                t = doc.GetElement(tid)
                p = lookup(t, name)
                if p is not None:
                    return p, "type"
        except Exception:
            pass
    return None, None


def _is_yesno(p):
    spec, _ = definition_spec(p.Definition)
    return spec == "yesno"


def raw_value(p, unit=None):
    """Comparable value: text, int/bool, float (converted to unit when measurable), id."""
    st = p.StorageType
    if st == DB.StorageType.String:
        return to_text(p.AsString())
    if st == DB.StorageType.Integer:
        v = p.AsInteger()
        return bool(v) if _is_yesno(p) else v
    if st == DB.StorageType.Double:
        v = p.AsDouble()
        spec, kind = definition_spec(p.Definition)
        if kind in ("length", "area", "volume", "angle") and unit:
            target = U.length_unit_for(kind, unit)
            return U.from_internal(v, target, 6)
        return v
    if st == DB.StorageType.ElementId:
        return id_int(p.AsElementId())
    return None


def read(doc, p, unit="mm", meta=False):
    d = p.Definition
    spec, kind = definition_spec(d)
    info = {"name": normalize_string(d.Name)}
    try:
        info["value"] = raw_value(p, unit)
    except Exception:
        info["value"] = None
    if p.StorageType == DB.StorageType.Double and kind in ("length", "area", "volume", "angle"):
        info["unit"] = U.length_unit_for(kind, unit)
    elif p.StorageType == DB.StorageType.Double and kind == "measurable":
        info["unit"] = "internal"
    try:
        vs = p.AsValueString()
        if vs is not None and vs != info.get("value"):
            info["display"] = to_text(vs)
    except Exception:
        pass
    if p.StorageType == DB.StorageType.ElementId:
        try:
            ref = doc.GetElement(p.AsElementId())
            if ref is not None:
                info["display"] = normalize_string(get_element_name(ref))
        except Exception:
            pass
    if meta:
        info.update({
            "storage": str(p.StorageType),
            "spec": spec,
            "group": definition_group(d),
            "read_only": p.IsReadOnly,
            "shared": p.IsShared,
            "has_value": p.HasValue,
        })
        if p.IsShared:
            try:
                info["guid"] = str(p.GUID)
            except Exception:
                pass
        try:
            bip = d.BuiltInParameter
            if bip != DB.BuiltInParameter.INVALID:
                info["builtin"] = str(bip)
        except Exception:
            pass
    return info


def read_all(doc, element, unit="mm", names=None, meta=False, include_empty=False):
    out = []
    if names:
        for n in names:
            p = lookup(element, n)
            if p is None:
                out.append({"name": n, "missing": True})
            else:
                out.append(read(doc, p, unit, meta))
        return out
    for p in element.Parameters:
        try:
            if not include_empty and not p.HasValue and p.StorageType != DB.StorageType.Integer:
                continue
            out.append(read(doc, p, unit, meta))
        except Exception:
            continue
    out.sort(key=lambda x: x["name"].lower())
    return out


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = text_type(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on", "checked"):
        return True
    if s in ("0", "false", "no", "n", "off", "unchecked", ""):
        return False
    raise RvtssError("Cannot interpret '{}' as Yes/No".format(value))


def _resolve_id_value(doc, p, value):
    if value is None or value == "" or value == -1:
        return DB.ElementId.InvalidElementId
    if isinstance(value, int) or (isinstance(value, basestring) and value.lstrip("-").isdigit()):
        return make_id(int(value))
    name = text_type(value).strip().lower()
    spec, _ = definition_spec(p.Definition)
    classes = [DB.Material] if spec == "material" else [DB.Level, DB.Material, DB.Phase]
    for cls in classes:
        for e in DB.FilteredElementCollector(doc).OfClass(cls):
            if normalize_string(e.Name).lower() == name:
                return e.Id
    raise RvtssError("No element named '{}' found for parameter '{}'".format(value, p.Definition.Name),
                     status=404, hint="Pass an element id instead.")


def set_value(doc, p, value, unit=None):
    """Set a parameter value (inside a transaction). Returns the new read() dict."""
    name = normalize_string(p.Definition.Name)
    if p.IsReadOnly:
        raise RvtssError("Parameter '{}' is read-only".format(name), status=409,
                         hint="It may be computed by Revit, driven by a formula, or a type parameter "
                              "locked by the family.")
    st = p.StorageType
    if st == DB.StorageType.String:
        ok = p.Set("" if value is None else text_type(value))
    elif st == DB.StorageType.Integer:
        if _is_yesno(p):
            ok = p.Set(1 if _parse_bool(value) else 0)
        else:
            try:
                ok = p.Set(int(value))
            except (TypeError, ValueError):
                raise RvtssError("Parameter '{}' needs an integer, got '{}'".format(name, value))
    elif st == DB.StorageType.Double:
        spec, kind = definition_spec(p.Definition)
        measurable = kind in ("length", "area", "volume", "angle", "measurable")
        if isinstance(value, basestring) and not unit:
            s = value.strip()
            try:
                num = float(s)
            except ValueError:
                num = None
            if num is not None and not measurable:
                ok = p.Set(num)
            elif num is not None:
                raise RvtssError(
                    "Parameter '{}' has units ({}); '{}' has none".format(name, spec, value),
                    hint="Pass unit (e.g. 'mm') or a string with units such as '{} mm'.".format(s))
            else:
                ok = p.SetValueString(s)
                if not ok:
                    raise RvtssError("Revit could not parse '{}' for '{}'".format(s, name),
                                     hint="Use project display units syntax, e.g. '900 mm' or 3'-0\"")
        else:
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise RvtssError("Parameter '{}' needs a number, got '{}'".format(name, value))
            if measurable and not unit:
                raise RvtssError(
                    "Parameter '{}' has units ({}) but no unit was given for {}".format(name, spec, value),
                    hint="Add unit='mm' (or m, cm, ft, in, deg, m2, m3, internal).")
            if unit and measurable and kind != "measurable":
                u = U.normalize_unit(unit)
                if U.unit_kind(u) not in (kind, "any"):
                    raise RvtssError("Unit '{}' does not fit parameter '{}' ({})".format(unit, name, kind))
                num = U.to_internal(num, u)
            elif unit and kind == "measurable" and U.normalize_unit(unit) != "internal":
                raise RvtssError("Parameter '{}' uses spec {}; pass unit='internal' or a string with units"
                                 .format(name, spec))
            ok = p.Set(num)
    elif st == DB.StorageType.ElementId:
        ok = p.Set(_resolve_id_value(doc, p, value))
    else:
        raise RvtssError("Parameter '{}' has no settable storage type".format(name))
    if ok is False:
        raise RvtssError("Revit refused value '{}' for '{}'".format(value, name), status=409)
    return read(doc, p, unit or "mm")


def family_type_value(fm, ftype, fp, unit="mm"):
    """Value of a FamilyParameter in a FamilyType, converted like raw_value()."""
    if not ftype.HasValue(fp):
        return None
    st = fp.StorageType
    if st == DB.StorageType.String:
        return to_text(ftype.AsString(fp))
    if st == DB.StorageType.Integer:
        v = ftype.AsInteger(fp)
        spec, _ = definition_spec(fp.Definition)
        return bool(v) if spec == "yesno" else v
    if st == DB.StorageType.Double:
        v = ftype.AsDouble(fp)
        spec, kind = definition_spec(fp.Definition)
        if kind in ("length", "area", "volume"):
            return U.from_internal(v, U.length_unit_for(kind, unit), 6)
        if kind == "angle":
            return U.from_internal(v, "deg", 6)
        return v
    if st == DB.StorageType.ElementId:
        return id_int(ftype.AsElementId(fp))
    return None


def set_family_value(doc, fm, fp, value, unit=None):
    """FamilyManager.Set for the current type, with the same unit rules as set_value."""
    name = normalize_string(fp.Definition.Name)
    if fp.IsDeterminedByFormula:
        raise RvtssError("'{}' is driven by formula '{}'".format(name, fp.Formula), status=409,
                         hint="Change the formula (family_set_formulas) or remove it first.")
    st = fp.StorageType
    if st == DB.StorageType.String:
        fm.Set(fp, "" if value is None else text_type(value))
    elif st == DB.StorageType.Integer:
        spec, _ = definition_spec(fp.Definition)
        fm.Set(fp, (1 if _parse_bool(value) else 0) if spec == "yesno" else int(value))
    elif st == DB.StorageType.Double:
        spec, kind = definition_spec(fp.Definition)
        measurable = kind in ("length", "area", "volume", "angle", "measurable")
        if isinstance(value, basestring) and not unit:
            try:
                num = float(value)
            except ValueError:
                fm.SetValueString(fp, value)
                return
            if measurable:
                raise RvtssError("'{}' has units ({}); pass unit or a string like '{} mm'".format(name, spec, value))
            fm.Set(fp, num)
        else:
            num = float(value)
            if measurable and not unit:
                raise RvtssError("'{}' has units ({}) but no unit was given".format(name, spec),
                                 hint="Add unit='mm' (or m, cm, ft, in, deg).")
            if unit and kind in ("length", "area", "volume", "angle"):
                # the default unit is a length unit (ctx.unit): adapt it to the parameter's
                # kind (mm -> mm2 for areas, -> deg for angles) instead of applying a length
                # factor to an angle or area
                num = U.to_internal(num, U.length_unit_for(kind, unit))
            elif unit and kind == "measurable" and U.normalize_unit(unit) != "internal":
                raise RvtssError("'{}' uses spec {}; pass unit='internal' or a string with units".format(name, spec))
            fm.Set(fp, num)
    elif st == DB.StorageType.ElementId:
        fm.Set(fp, _resolve_id_value(doc, fp, value))


def family_parameter(fm, name):
    for fp in fm.Parameters:
        if normalize_string(fp.Definition.Name) == name:
            return fp
    low = (name or "").lower()
    for fp in fm.Parameters:
        if normalize_string(fp.Definition.Name).lower() == low:
            return fp
    return None


def require_family_parameter(fm, name):
    fp = family_parameter(fm, name)
    if fp is None:
        from .core import not_found

        raise not_found("Family parameter", name, [p.Definition.Name for p in fm.Parameters])
    return fp
