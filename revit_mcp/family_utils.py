# -*- coding: UTF-8 -*-
"""Helpers shared by the family editor route modules."""
from pyrevit import DB

from .core import RvtssError, not_found
from .compat import id_int, definition_spec, definition_group
from .params_util import family_type_value
from .pure import units as U
from .utils import normalize_string

FORM_CLASSES = (("extrusion", "Extrusion"), ("blend", "Blend"), ("revolution", "Revolution"),
                ("sweep", "Sweep"), ("swept_blend", "SweptBlend"))


def owner_family(doc):
    return doc.OwnerFamily


def family_name(doc):
    import os

    if doc.PathName:
        return os.path.splitext(os.path.basename(doc.PathName))[0]
    return os.path.splitext(normalize_string(doc.Title))[0]


def ref_level(doc):
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    if not levels:
        return None
    for lv in levels:
        if "ref" in normalize_string(lv.Name).lower():
            return lv
    return levels[0]


def plan_view(doc):
    lv = ref_level(doc)
    plans = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
             if not v.IsTemplate and v.ViewType in (DB.ViewType.FloorPlan, DB.ViewType.EngineeringPlan)]
    if lv is not None:
        for v in plans:
            try:
                if v.GenLevel is not None and v.GenLevel.Id == lv.Id:
                    return v
            except Exception:
                continue
    if plans:
        return plans[0]
    raise RvtssError("This family template has no plan view", status=409,
                     hint="Plan-based operations (dimensions, alignments of vertical faces) need a plan view.")


def elevation_view(doc, side="front"):
    """Front elevation looks towards +Y (view direction points to the viewer: -Y)."""
    wanted = {"front": DB.XYZ(0, -1, 0), "back": DB.XYZ(0, 1, 0), "left": DB.XYZ(-1, 0, 0),
              "right": DB.XYZ(1, 0, 0)}[side]
    elevs = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
             if not v.IsTemplate and v.ViewType == DB.ViewType.Elevation]
    for v in elevs:
        try:
            if v.ViewDirection.IsAlmostEqualTo(wanted):
                return v
        except Exception:
            continue
    for v in elevs:
        if normalize_string(v.Name).lower() == side:
            return v
    if elevs:
        return elevs[0]
    raise RvtssError("This family template has no elevation view", status=409)


def reference_planes(doc):
    return list(DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane))


def plane_orientation(rp):
    n = rp.Normal
    if abs(n.X) > 0.999:
        return "x"
    if abs(n.Y) > 0.999:
        return "y"
    if abs(n.Z) > 0.999:
        return "z"
    return "skew"


def plane_offset(rp):
    """Signed position of an axis-aligned plane along its normal axis (internal units)."""
    o = plane_orientation(rp)
    p = rp.BubbleEnd
    return {"x": p.X, "y": p.Y, "z": p.Z}.get(o)


def find_ref_plane(doc, name, required=True):
    """Reference plane by name, or 'Ref. Level' / 'level' returning the Level."""
    if name is None:
        return None
    low = normalize_string(name).lower()
    if low in ("ref. level", "ref level", "level", "reference level"):
        lv = ref_level(doc)
        if lv is not None:
            return lv
    planes = reference_planes(doc)
    for rp in planes:
        if normalize_string(rp.Name).lower() == low:
            return rp
    if isinstance(name, int) or str(name).isdigit():
        from .compat import make_id

        e = doc.GetElement(make_id(int(name)))
        if isinstance(e, (DB.ReferencePlane, DB.Level)):
            return e
    if required:
        raise not_found("Reference plane", name, [rp.Name for rp in planes] + ["Ref. Level"])
    return None


def datum_reference(datum):
    if isinstance(datum, DB.Level):
        return datum.GetPlaneReference()
    return datum.GetReference()


def datum_orientation(datum):
    return "z" if isinstance(datum, DB.Level) else plane_orientation(datum)


def datum_offset(datum):
    return datum.Elevation if isinstance(datum, DB.Level) else plane_offset(datum)


IS_REFERENCE_VALUES = ("NotAReference", "Left", "CenterLeftRight", "Right", "Front", "CenterFrontBack",
                       "Back", "Bottom", "CenterElevation", "Top", "StrongReference", "WeakReference")


def is_reference_label(rp):
    try:
        p = rp.get_Parameter(DB.BuiltInParameter.ELEM_REFERENCE_NAME)
        if p is not None:
            return normalize_string(p.AsValueString() or "")
    except Exception:
        pass
    return None


def set_is_reference(rp, value):
    """Best effort: set the 'Is Reference' property of a reference plane."""
    enum = getattr(DB, "FamilyInstanceReferenceType", None)
    member = getattr(enum, value, None) if enum is not None else None
    if member is None:
        raise RvtssError("Unknown is_reference '{}'. Use one of: {}".format(value, ", ".join(IS_REFERENCE_VALUES)))
    p = rp.get_Parameter(DB.BuiltInParameter.ELEM_REFERENCE_NAME)
    if p is None or p.IsReadOnly:
        raise RvtssError("This reference plane's 'Is Reference' cannot be set")
    p.Set(int(member))


def describe_ref_plane(rp, unit):
    o = plane_orientation(rp)
    off = plane_offset(rp)
    return {"id": id_int(rp), "name": normalize_string(rp.Name), "orientation": o,
            "offset": U.from_internal(off, unit, 3) if off is not None else None,
            "is_reference": is_reference_label(rp)}


def forms(doc):
    out = []
    for kind, cls_name in FORM_CLASSES:
        cls = getattr(DB, cls_name, None)
        if cls is None:
            continue
        for f in DB.FilteredElementCollector(doc).OfClass(cls):
            out.append((kind, f))
    return out


def describe_form(doc, kind, f, unit, fm=None):
    d = {"id": id_int(f), "kind": kind, "solid": f.IsSolid}
    try:
        d["subcategory"] = normalize_string(f.Subcategory.Name) if f.Subcategory else None
    except Exception:
        pass
    try:
        vis = f.GetVisibility()
        d["visibility"] = {"coarse": vis.IsShownInCoarse, "medium": vis.IsShownInMedium, "fine": vis.IsShownInFine}
    except Exception:
        pass
    bb = f.get_BoundingBox(None)
    if bb is not None:
        d["size"] = [U.from_internal(bb.Max.X - bb.Min.X, unit, 2), U.from_internal(bb.Max.Y - bb.Min.Y, unit, 2),
                     U.from_internal(bb.Max.Z - bb.Min.Z, unit, 2)]
    if fm is not None:
        assoc = {}
        for bip, label in (("MATERIAL_ID_PARAM", "material"), ("IS_VISIBLE_PARAM", "visible"),
                           ("EXTRUSION_END_PARAM", "extrusion_end"), ("EXTRUSION_START_PARAM", "extrusion_start")):
            try:
                p = f.get_Parameter(getattr(DB.BuiltInParameter, bip))
                if p is None:
                    continue
                fp = fm.GetAssociatedFamilyParameter(p)
                if fp is not None:
                    assoc[label] = normalize_string(fp.Definition.Name)
            except Exception:
                continue
        if assoc:
            d["associated_parameters"] = assoc
    if kind == "extrusion":
        try:
            d["start"] = U.from_internal(f.StartOffset, unit, 3)
            d["end"] = U.from_internal(f.EndOffset, unit, 3)
        except Exception:
            pass
    return d


def labeled_dimensions(doc):
    """{family parameter name: [dimension ids]}"""
    out = {}
    for dim in DB.FilteredElementCollector(doc).OfClass(DB.Dimension):
        try:
            lbl = dim.FamilyLabel
        except Exception:
            lbl = None
        if lbl is not None:
            out.setdefault(normalize_string(lbl.Definition.Name), []).append(id_int(dim))
    return out


def describe_dimension(dim, unit):
    d = {"id": id_int(dim)}
    try:
        d["label"] = normalize_string(dim.FamilyLabel.Definition.Name) if dim.FamilyLabel else None
    except Exception:
        d["label"] = None
    try:
        v = dim.Value
        d["value"] = U.from_internal(v, unit, 3) if v is not None else None
    except Exception:
        pass
    try:
        d["references"] = dim.References.Size
        d["segments"] = dim.NumberOfSegments
        d["locked"] = dim.IsLocked
    except Exception:
        pass
    try:
        d["equality"] = dim.AreSegmentsEqual
    except Exception:
        pass
    try:
        d["view"] = normalize_string(dim.View.Name) if dim.View else None
    except Exception:
        pass
    return d


def family_param_info(doc, fm, fp, unit="mm", labels=None):
    spec, kind = definition_spec(fp.Definition)
    d = {
        "name": normalize_string(fp.Definition.Name),
        "id": id_int(fp.Id),
        "instance": fp.IsInstance,
        "spec": spec,
        "group": definition_group(fp.Definition),
        "shared": fp.IsShared,
        "formula": fp.Formula or None,
        "reporting": fp.IsReporting,
        "read_only": fp.IsReadOnly,
        "associated_element_parameters": fp.AssociatedParameters.Size,
    }
    if fp.IsShared:
        try:
            d["guid"] = str(fp.GUID)
        except Exception:
            pass
    if labels is not None:
        d["labels_dimensions"] = len(labels.get(d["name"], []))
    try:
        if fm.CurrentType is not None:
            d["current_value"] = family_type_value(fm, fm.CurrentType, fp, unit)
    except Exception:
        pass
    if kind in ("length", "area", "volume"):
        d["unit"] = U.length_unit_for(kind, unit)
    elif kind == "angle":
        d["unit"] = "deg"
    try:
        bip = fp.Definition.BuiltInParameter
        if bip != DB.BuiltInParameter.INVALID:
            d["builtin"] = str(bip)
    except Exception:
        pass
    return d


def is_builtin(fp):
    try:
        return fp.Definition.BuiltInParameter != DB.BuiltInParameter.INVALID
    except Exception:
        return False


def is_relevant(fp, include_all_builtin=False):
    """User parameters plus built-in parameters that drive the family.

    Door/window templates expose Width, Height, Thickness... as *built-in* family
    parameters, so filtering out every built-in would hide the most important
    ones. Only built-in text/identity data (Type Mark, Keynote, URL, ...) is noise.
    """
    if include_all_builtin or not is_builtin(fp):
        return True
    if fp.StorageType == DB.StorageType.String:
        return False
    group = (definition_group(fp.Definition) or "").lower()
    return "identity" not in group and "ifc" not in group


def ensure_current_type(fm, default_name="Default"):
    """Families without types cannot hold parameter values; create one if needed."""
    if fm.CurrentType is None:
        fm.NewType(default_name)
    return fm.CurrentType


def find_family_type(fm, name):
    for t in fm.Types:
        if normalize_string(t.Name) == name or normalize_string(t.Name).lower() == (name or "").lower():
            return t
    raise not_found("Family type", name, [normalize_string(t.Name) for t in fm.Types])


def solid_faces(form):
    opt = DB.Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    geom = form.get_Geometry(opt)
    if geom is None:
        return []
    faces = []
    for obj in geom:
        if isinstance(obj, DB.Solid) and obj.Faces.Size > 0:
            for f in obj.Faces:
                if isinstance(f, DB.PlanarFace):
                    faces.append(f)
    return faces


def combined_bbox(doc, solids_only=True):
    mins, maxs = None, None
    for _kind, f in forms(doc):
        if solids_only and not f.IsSolid:
            continue
        bb = f.get_BoundingBox(None)
        if bb is None:
            continue
        if mins is None:
            mins = [bb.Min.X, bb.Min.Y, bb.Min.Z]
            maxs = [bb.Max.X, bb.Max.Y, bb.Max.Z]
        else:
            mins = [min(a, b) for a, b in zip(mins, [bb.Min.X, bb.Min.Y, bb.Min.Z])]
            maxs = [max(a, b) for a, b in zip(maxs, [bb.Max.X, bb.Max.Y, bb.Max.Z])]
    if mins is None:
        return None
    return mins, maxs
