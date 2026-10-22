# -*- coding: UTF-8 -*-
"""Revit API version shims (Revit 2021 - 2027).

Differences handled here:
  * ElementId: Int32 constructor + IntegerValue (<=2023) vs Int64 + Value (2024+,
    IntegerValue removed in 2026).
  * Parameter data types: ParameterType (<=2022, removed 2023) vs ForgeTypeId
    SpecTypeId (2021.1+).
  * Parameter groups: BuiltInParameterGroup (removed 2024) vs GroupTypeId (2022+).
  * Shared parameter creation / bindings / FamilyManager.AddParameter overloads.

Revit 2027 (API 27.0, .NET 10) needs no extra shim: the BuiltInParameters,
ImageFileType and GlobalParameter members RVTSS uses are unchanged in the 2027
API reference, and pyRevit's develop branch ships a Revit 2027 runtime
(pyRevitLabs.PyRevit.Runtime.2027). Not yet run in a live Revit 2027 session.
"""
from pyrevit import DB
import System

from .utils import element_id_value

try:
    from pyrevit import HOST_APP

    REVIT_YEAR = int(str(HOST_APP.version)[:4])
except Exception:  # pragma: no cover - outside Revit
    REVIT_YEAR = 0

try:
    text_type = unicode  # noqa: F821  IronPython 2
except NameError:
    text_type = str

HAS_FORGE = hasattr(DB, "SpecTypeId") and hasattr(DB, "GroupTypeId")


def make_id(value):
    """int -> ElementId on every supported Revit version."""
    if isinstance(value, DB.ElementId):
        return value
    v = int(value)
    try:
        return DB.ElementId(System.Int64(v))
    except Exception:
        return DB.ElementId(System.Int32(v))


def id_int(element_or_id):
    if element_or_id is None:
        return None
    if isinstance(element_or_id, DB.ElementId):
        return element_id_value(element_or_id)
    return element_id_value(element_or_id.Id)


INVALID_ID = DB.ElementId.InvalidElementId


def is_valid_id(eid):
    return eid is not None and eid != DB.ElementId.InvalidElementId


# --------------------------------------------------------------------------- specs
# friendly name -> (SpecTypeId attribute path, legacy ParameterType name, unit kind)
SPECS = {
    "length": ("Length", "Length", "length"),
    "area": ("Area", "Area", "area"),
    "volume": ("Volume", "Volume", "volume"),
    "angle": ("Angle", "Angle", "angle"),
    "slope": ("Slope", "Slope", None),
    "number": ("Number", "Number", None),
    "integer": ("Int.Integer", "Integer", None),
    "text": ("String.Text", "Text", None),
    "multiline_text": ("String.MultilineText", "MultilineText", None),
    "url": ("String.Url", "URL", None),
    "yesno": ("Boolean.YesNo", "YesNo", None),
    "material": ("Reference.Material", "Material", None),
    "image": ("Reference.Image", "Image", None),
    "currency": ("Currency", "Currency", None),
    "mass": ("Mass", "Mass", None),
    "force": ("Force", "Force", None),
}
SPEC_ALIASES = {
    "string": "text", "bool": "yesno", "boolean": "yesno", "yes/no": "yesno", "yes_no": "yesno",
    "int": "integer", "double": "number", "float": "number", "distance": "length",
    "dimension": "length", "multiline": "multiline_text",
}


def spec_names():
    return sorted(SPECS)


def _resolve_path(root, path):
    obj = root
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def spec_id(name):
    """Friendly spec name -> ForgeTypeId (or legacy ParameterType on old Revit)."""
    key = SPEC_ALIASES.get((name or "").lower(), (name or "").lower())
    if key not in SPECS:
        raise ValueError("Unknown parameter type '{}'. Use one of: {}".format(name, ", ".join(spec_names())))
    forge_path, legacy, _ = SPECS[key]
    # Specs and groups must come from the same API generation: Revit 2021 has
    # SpecTypeId but its AddParameter / binding / creation overloads still take
    # ParameterType + BuiltInParameterGroup.
    if HAS_FORGE:
        try:
            return _resolve_path(DB.SpecTypeId, forge_path)
        except AttributeError:
            pass
    return getattr(DB.ParameterType, legacy)


def spec_kind(name):
    key = SPEC_ALIASES.get((name or "").lower(), (name or "").lower())
    return SPECS.get(key, (None, None, None))[2]


def definition_spec(definition):
    """Definition -> (friendly name or raw type id, unit kind or None)."""
    try:
        dt = definition.GetDataType()  # 2022+
        for name, (forge_path, _l, kind) in SPECS.items():
            try:
                if dt == _resolve_path(DB.SpecTypeId, forge_path):
                    return name, kind
            except AttributeError:
                continue
        try:
            if DB.UnitUtils.IsMeasurableSpec(dt):
                return dt.TypeId, "measurable"
        except Exception:
            pass
        return (dt.TypeId if dt else None), None
    except AttributeError:
        pass
    try:
        pt = definition.ParameterType  # <= 2022
        for name, (_f, legacy, kind) in SPECS.items():
            if str(pt) == legacy:
                return name, kind
        return str(pt), None
    except Exception:
        return None, None


def is_measurable(definition):
    name, kind = definition_spec(definition)
    return kind in ("length", "area", "volume", "angle", "measurable")


# -------------------------------------------------------------------------- groups
# friendly name -> (GroupTypeId attribute, legacy BuiltInParameterGroup)
GROUPS = {
    "dimensions": ("Geometry", "PG_GEOMETRY"),
    "constraints": ("Constraints", "PG_CONSTRAINTS"),
    "construction": ("Construction", "PG_CONSTRUCTION"),
    "data": ("Data", "PG_DATA"),
    "identity_data": ("IdentityData", "PG_IDENTITY_DATA"),
    "materials": ("Materials", "PG_MATERIALS"),
    "graphics": ("Graphics", "PG_GRAPHICS"),
    "text": ("Text", "PG_TEXT"),
    "general": ("General", "PG_GENERAL"),
    "phasing": ("Phasing", "PG_PHASING"),
    "visibility": ("Visibility", "PG_VISIBILITY"),
    "fire_protection": ("FireProtection", "PG_FIRE_PROTECTION"),
    "structural": ("Structural", "PG_STRUCTURAL"),
    "mechanical": ("Mechanical", "PG_MECHANICAL"),
    "electrical": ("Electrical", "PG_ELECTRICAL"),
    "plumbing": ("Plumbing", "PG_PLUMBING"),
    "energy_analysis": ("EnergyAnalysis", "PG_ENERGY_ANALYSIS"),
    "ifc": ("Ifc", "PG_IFC"),
    "other": (None, "INVALID"),
}
GROUP_ALIASES = {"geometry": "dimensions", "identity": "identity_data", "identitydata": "identity_data",
                 "material": "materials", "fire": "fire_protection"}


def group_names():
    return sorted(GROUPS)


def group_id(name):
    key = GROUP_ALIASES.get((name or "other").lower(), (name or "other").lower().replace(" ", "_"))
    if key not in GROUPS:
        raise ValueError("Unknown parameter group '{}'. Use one of: {}".format(name, ", ".join(group_names())))
    forge, legacy = GROUPS[key]
    if hasattr(DB, "GroupTypeId"):
        if forge is None:
            return DB.ForgeTypeId("")
        try:
            return getattr(DB.GroupTypeId, forge)
        except AttributeError:
            pass
    return getattr(DB.BuiltInParameterGroup, legacy)


def definition_group(definition):
    try:
        gid = definition.GetGroupTypeId()
        try:
            label = DB.LabelUtils.GetLabelForGroup(gid)
        except Exception:
            label = gid.TypeId
        return label or "Other"
    except AttributeError:
        try:
            return str(definition.ParameterGroup)
        except Exception:
            return None


# ---------------------------------------------------------------- family manager
def add_family_parameter(fm, name, spec, group, is_instance):
    """FamilyManager.AddParameter for every version."""
    return fm.AddParameter(name, group_id(group), spec_id(spec), bool(is_instance))


def add_shared_family_parameter(fm, external_definition, group, is_instance):
    return fm.AddParameter(external_definition, group_id(group), bool(is_instance))


def external_definition_options(name, spec):
    return DB.ExternalDefinitionCreationOptions(name, spec_id(spec))


def insert_binding(doc, definition, binding, group):
    return doc.ParameterBindings.Insert(definition, binding, group_id(group))


def reinsert_binding(doc, definition, binding, group):
    return doc.ParameterBindings.ReInsert(definition, binding, group_id(group))


def bic_from_category(cat):
    """Category -> BuiltInCategory name (e.g. 'OST_Doors') or None."""
    if cat is None:
        return None
    try:
        return str(cat.BuiltInCategory)  # 2023+
    except AttributeError:
        pass
    try:
        v = id_int(cat.Id)
        if v < 0:
            return str(System.Enum.ToObject(DB.BuiltInCategory, v))
    except Exception:
        pass
    return None


def new_floor(doc, curve_loops, floor_type, level, structural=False):
    """Floor.Create (2022+) or doc.Create.NewFloor (older)."""
    if hasattr(DB, "Floor") and hasattr(DB.Floor, "Create"):
        from System.Collections.Generic import List

        loops = List[DB.CurveLoop]()
        for loop in curve_loops:
            loops.Add(loop)
        floor = DB.Floor.Create(doc, loops, floor_type.Id, level.Id)
        if structural:
            p = floor.get_Parameter(DB.BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
            if p and not p.IsReadOnly:
                p.Set(1)
        return floor
    arr = DB.CurveArray()
    for c in curve_loops[0]:
        arr.Append(c)
    return doc.Create.NewFloor(arr, floor_type, level, structural)
