# -*- coding: UTF-8 -*-
"""Insert, manage and collaborate (RVTSS v2.4).

Routes:
    POST /insert/files/         list CAD links / imports and images; link or import CAD (DWG, DXF, DGN, SAT,
                                SKP); place an image; reload or delete a CAD link
    POST /insert/family/        load .rfa files (or one type) from disk into the document
    POST /project/settings/     project information, project units, starting view, project location
    POST /styles/manage/        object styles, subcategories, line styles, line patterns, fill patterns
    POST /standards/transfer/   copy types / templates / filters / materials / patterns from another open
                                document (Transfer Project Standards)
    POST /worksharing/          ownership status, relinquish, reload latest, shared coordinates with a link

Relinquish and reload latest talk to the central model outside a transaction and cannot be undone, so
they follow the same policy as sync_with_central (RVTSS_ALLOW_SYNC / "allow_sync").
"""
import logging
import math
import os

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, is_valid_id, text_type
from .pure import units as U
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------ helpers
def _name(e):
    return normalize_string(get_element_name(e) or "")


def _existing_file(path, extensions=None, what="File"):
    if not path:
        raise RvtssError("'path' is required")
    path = os.path.normpath(os.path.expandvars(text_type(path)))
    if not os.path.isfile(path):
        raise RvtssError("{} not found: {}".format(what, path), status=404,
                         hint="Give the full path as Revit's machine sees it.")
    ext = os.path.splitext(path)[1].lower()
    if extensions and ext not in extensions:
        raise RvtssError("{} must be one of {} (got '{}')".format(what, ", ".join(sorted(extensions)), ext))
    return path


def _out_id():
    import clr

    return clr.Reference[DB.ElementId]()


def _color(value):
    """[r, g, b] or '#rrggbb' -> DB.Color."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        rgb = [int(v) for v in value]
    else:
        s = text_type(value).strip().lstrip("#")
        if len(s) != 6:
            raise RvtssError("Colour must be [r, g, b] or '#rrggbb' (got '{}')".format(value))
        try:
            rgb = [int(s[i:i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            raise RvtssError("Colour must be [r, g, b] or '#rrggbb' (got '{}')".format(value))
    if any(v < 0 or v > 255 for v in rgb):
        raise RvtssError("Colour components must be 0-255")
    return DB.Color(rgb[0], rgb[1], rgb[2])


def _color_list(c):
    try:
        if c is None or not c.IsValid:
            return None
        return [int(c.Red), int(c.Green), int(c.Blue)]
    except Exception:
        return None


def _require_sync_policy(action):
    """Same switch as sync_with_central: talking to central is off unless allow_sync is set."""
    try:
        from .secure_api import settings

        allowed = bool(settings().get("allow_sync"))
    except Exception:
        allowed = False
    if not allowed:
        raise RvtssError(
            "{} is refused: synchronize with central is off in the RVTSS policy (allow_sync)".format(action),
            status=403, code="POLICY_DENIED", policy="allow_sync",
            hint="Do it in Revit yourself, or set \"allow_sync\": true in %APPDATA%/RVTSS/config.json (or "
                 "RVTSS_ALLOW_SYNC=1 for Revit) and restart Revit.")


def _no_open_transaction(doc, action):
    if doc.IsModifiable:
        raise RvtssError("{} cannot run while a transaction is open".format(action), status=409)
    if core.in_batch():
        raise RvtssError("{} cannot run in batch_execute (it is not a transaction and cannot be rolled "
                         "back)".format(action))


# ------------------------------------------------------------------- insert files
CAD_EXT = {".dwg": "dwg", ".dxf": "dwg", ".dgn": "dgn", ".sat": "sat", ".skp": "skp"}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf")
_PLACEMENT = {"origin": "Origin", "center": "Centered", "shared": "Shared", "site": "Site"}
_UNITS = {"auto": "Default", "mm": "Millimeter", "cm": "Centimeter", "dm": "Decimeter", "m": "Meter",
          "ft": "Foot", "in": "Inch"}
_COLORS = {"preserve": "Preserved", "invert": "Inverted", "black_white": "BlackAndWhite"}


def _cad_options(ctx, kind):
    cls = {"dwg": "DWGImportOptions", "dgn": "DGNImportOptions", "sat": "SATImportOptions",
           "skp": "SKPImportOptions"}[kind]
    if not hasattr(DB, cls):
        raise RvtssError("This Revit version has no {}".format(cls), status=501)
    opts = getattr(DB, cls)()
    applied, ignored = {}, []

    def put(attr, value, label):
        try:
            setattr(opts, attr, value)
            applied[label] = text_type(value)
        except Exception:
            ignored.append(label)

    placement = ctx.get("placement", "origin")
    if placement not in _PLACEMENT:
        raise RvtssError("placement must be one of: {}".format(", ".join(sorted(_PLACEMENT))))
    put("Placement", getattr(DB.ImportPlacement, _PLACEMENT[placement]), "placement")
    unit = ctx.get("import_unit", "auto")
    if unit not in _UNITS:
        raise RvtssError("import_unit must be one of: {}".format(", ".join(sorted(_UNITS))))
    put("Unit", getattr(DB.ImportUnit, _UNITS[unit]), "import_unit")
    if kind in ("dwg", "dgn"):
        colour = ctx.get("color_mode", "preserve")
        if colour not in _COLORS:
            raise RvtssError("color_mode must be one of: {}".format(", ".join(sorted(_COLORS))))
        put("ColorMode", getattr(DB.ImportColorMode, _COLORS[colour]), "color_mode")
        put("ThisViewOnly", ctx.bool("current_view_only", False), "current_view_only")
        put("VisibleLayersOnly", ctx.bool("visible_layers_only", False), "visible_layers_only")
        if ctx.bool("orient_to_view", False):
            put("OrientToView", True, "orient_to_view")
    return opts, applied, ignored


def _cad_instances(doc):
    return list(DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance))


def _cad_path(doc, type_id):
    try:
        t = doc.GetElement(type_id)
        ref = t.GetExternalFileReference()
        return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetAbsolutePath())
    except Exception:
        return None


def _cad_brief(doc, inst):
    owner = None
    try:
        if inst.ViewSpecific and is_valid_id(inst.OwnerViewId):
            owner = normalize_string(doc.GetElement(inst.OwnerViewId).Name)
    except Exception:
        pass
    return {"id": id_int(inst), "type_id": id_int(inst.GetTypeId()), "name": _name(doc.GetElement(inst.GetTypeId())),
            "is_linked": bool(inst.IsLinked), "pinned": bool(inst.Pinned), "view_specific_in": owner,
            "path": _cad_path(doc, inst.GetTypeId()) if inst.IsLinked else None}


def _images(doc):
    out = []
    for t in DB.FilteredElementCollector(doc).OfClass(DB.ImageType):
        d = {"type_id": id_int(t), "name": _name(t)}
        try:
            d["path"] = normalize_string(t.Path)
        except Exception:
            pass
        out.append(d)
    if hasattr(DB, "ImageInstance"):
        by_type = {}
        for i in DB.FilteredElementCollector(doc).OfClass(DB.ImageInstance):
            by_type.setdefault(id_int(i.GetTypeId()), []).append(id_int(i))
        for d in out:
            d["instance_ids"] = by_type.get(d["type_id"], [])
    return out


def _find_cad(doc, ref):
    key = text_type(ref).strip().lower()
    for inst in _cad_instances(doc):
        t = doc.GetElement(inst.GetTypeId())
        if key in (text_type(id_int(inst)), text_type(id_int(inst.GetTypeId())), _name(t).lower()):
            return inst, t
    raise core.not_found("CAD link / import", ref, [_name(doc.GetElement(i.GetTypeId())) for i in _cad_instances(doc)])


def _image_type(doc, path):
    """ImageType from a file on every supported version (the options class changed in 2020 and 2021)."""
    errors = []
    if hasattr(DB, "ImageTypeOptions"):
        if hasattr(DB, "ImageTypeSource"):
            try:
                return DB.ImageType.Create(doc, DB.ImageTypeOptions(path, False, DB.ImageTypeSource.Import))
            except Exception as e:
                errors.append(text_type(e))
        try:
            return DB.ImageType.Create(doc, DB.ImageTypeOptions(path))
        except Exception as e:
            errors.append(text_type(e))
    try:
        return DB.ImageType.Create(doc, path)
    except Exception as e:
        errors.append(text_type(e))
    raise RvtssError("Revit could not create an image type from '{}'".format(path),
                     hint="; ".join(normalize_string(x) for x in errors[-2:]))


def insert_files(ctx):
    doc = ctx.doc
    action = ctx.get("action", "list")
    if action == "list":
        cad = [_cad_brief(doc, i) for i in _cad_instances(doc)]
        return {"cad_count": len(cad), "cad": cad, "images": _images(doc),
                "cad_linked": len([c for c in cad if c["is_linked"]]),
                "cad_imported": len([c for c in cad if not c["is_linked"]])}
    if action in ("link_cad", "import_cad"):
        path = _existing_file(ctx.get("path"), set(CAD_EXT), "CAD file")
        kind = CAD_EXT[os.path.splitext(path)[1].lower()]
        opts, applied, ignored = _cad_options(ctx, kind)
        view = core.find_view(doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
        if view.IsTemplate:
            raise RvtssError("A view template cannot host a CAD file")
        plan = {"action": action, "path": path, "format": kind, "options": applied,
                "options_not_supported_for_format": ignored, "view": normalize_string(view.Name)}
        if ctx.dry_run:
            return dict(plan, status="dry_run", committed=False,
                        message="Dry run: the file and options were checked; the file was not loaded.")

        def run():
            ref = _out_id()
            ok = doc.Link(path, opts, view, ref) if action == "link_cad" else doc.Import(path, opts, view, ref)
            new_id = ref.Value
            if not ok or not is_valid_id(new_id):
                raise RvtssError("Revit did not {} '{}'".format("link" if action == "link_cad" else "import",
                                                                os.path.basename(path)), status=409,
                                 hint="Check that the file opens in its own application and is not empty.")
            inst = doc.GetElement(new_id)
            if ctx.bool("pin", True):
                try:
                    inst.Pinned = True
                except Exception:
                    pass
            return {"element_id": id_int(new_id)}

        res, fails = core.run_transaction(doc, "Link CAD" if action == "link_cad" else "Import CAD", run)
        return core.commit_result(res, fails, False, plan)
    if action == "place_image":
        path = _existing_file(ctx.get("path"), set(IMAGE_EXT), "Image")
        if not hasattr(DB, "ImageInstance"):
            raise RvtssError("Placing images needs Revit 2020 or newer", status=501)
        view = core.find_view(doc, ctx.get("view", "active"), uidoc=ctx.uidoc)
        x, y, z = U.point_from(ctx.get("point") or [0, 0, 0], ctx.unit)
        width = ctx.float("width")

        def run():
            itype = _image_type(doc, path)
            placement = DB.ImagePlacementOptions(DB.XYZ(x, y, z), DB.BoxPlacement.Center)
            inst = DB.ImageInstance.Create(doc, view, itype.Id, placement)
            out = {"image_type_id": id_int(itype), "image_id": id_int(inst)}
            if width:
                try:
                    inst.LockProportions = True
                    inst.Width = U.to_internal(width, ctx.unit)
                    out["width"] = width
                except Exception as e:
                    ctx.warn("Width was not set: {}".format(normalize_string(text_type(e))))
            return out

        res, fails = core.run_transaction(doc, "Place image", run, dry_run=ctx.dry_run)
        return core.commit_result(res, fails, ctx.dry_run, {"view": normalize_string(view.Name), "path": path})
    if action == "reload_cad":
        inst, ltype = _find_cad(doc, ctx.require("link"))
        if not inst.IsLinked or not hasattr(ltype, "Reload"):
            raise RvtssError("'{}' is an import, not a link; imports cannot be reloaded".format(_name(ltype)),
                             status=409)
        if ctx.dry_run:
            return {"status": "dry_run", "would_reload": _cad_brief(doc, inst)}
        core.require_writable("reload CAD link")
        _no_open_transaction(doc, "Reloading a CAD link")
        try:
            ltype.Reload()
        except Exception as e:
            # some versions want a transaction around the reload
            if "transaction" not in text_type(e).lower():
                raise
            core.run_transaction(doc, "Reload CAD link", lambda: ltype.Reload() and None)
        return {"reloaded": _cad_brief(doc, inst)}
    if action == "delete":
        inst, ltype = _find_cad(doc, ctx.require("link"))
        brief = _cad_brief(doc, inst)
        whole = ctx.bool("all_instances", True)
        if not ctx.confirmed and not ctx.dry_run:
            return {"status": "preview", "requires_confirmation": True, "would_delete": brief,
                    "message": "Preview only - nothing was deleted. Re-run with confirm=true to apply."}

        def run():
            target = ltype.Id if whole else inst.Id
            deleted = [id_int(i) for i in doc.Delete(target)]
            return {"deleted": brief, "deleted_ids": deleted[:200], "deleted_count": len(deleted)}

        res, fails = core.run_transaction(doc, "Delete CAD", run, dry_run=ctx.dry_run)
        return core.commit_result(res, fails, ctx.dry_run)
    raise RvtssError("action must be list, link_cad, import_cad, place_image, reload_cad or delete")


# -------------------------------------------------------------------- load family
class _FamilyLoadOptions(DB.IFamilyLoadOptions):
    def __init__(self, overwrite, overwrite_values):
        self.overwrite = overwrite
        self.overwrite_values = overwrite_values
        self.found = False

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        self.found = True
        overwriteParameterValues.Value = self.overwrite_values
        return self.overwrite

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        self.found = True
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = self.overwrite_values
        return self.overwrite


def _family_named(doc, name):
    for f in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        if normalize_string(f.Name) == name:
            return f
    return None


def _family_types(doc, fam):
    return sorted(_name(doc.GetElement(s)) for s in fam.GetFamilySymbolIds())


def load_family(ctx):
    doc = ctx.doc
    paths = ctx.list("paths") or ctx.list("path")
    if not paths:
        raise RvtssError("'paths' is required: one or more .rfa files")
    if len(paths) > 100:
        raise RvtssError("At most 100 families per call")
    files = [_existing_file(p, set([".rfa"]), "Family file") for p in paths]
    type_name = ctx.get("type")
    if type_name and len(files) != 1:
        raise RvtssError("'type' loads one type from one family: give a single path")
    overwrite = ctx.bool("overwrite", False)
    overwrite_values = ctx.bool("overwrite_parameter_values", False)

    def one(path):
        import clr

        base = normalize_string(os.path.splitext(os.path.basename(path))[0])
        before = _family_named(doc, base)
        before_types = _family_types(doc, before) if before is not None else []
        opts = _FamilyLoadOptions(overwrite, overwrite_values)
        if type_name:
            ref = clr.Reference[DB.FamilySymbol]()
            ok = doc.LoadFamilySymbol(path, text_type(type_name), opts, ref)
        else:
            ref = clr.Reference[DB.Family]()
            ok = doc.LoadFamily(path, opts, ref)
        fam = _family_named(doc, base)
        if fam is None:
            raise RvtssError("Revit did not load '{}'".format(base),
                             hint="The family may be from a newer Revit version, or the type name is wrong.")
        types = _family_types(doc, fam)
        if before is None:
            result = "loaded"
        elif ok:
            result = "reloaded"
        else:
            result = "already_loaded"
        out = {"family": base, "family_id": id_int(fam), "result": result, "types": types,
               "new_types": [t for t in types if t not in before_types]}
        if result == "already_loaded" and not overwrite and not type_name:
            out["hint"] = "Pass overwrite=true to reload the family from the file."
        return out

    def run():
        return {"results": core.batch(doc, files, one, atomic=ctx.bool("atomic", False))}

    res, fails = core.run_transaction(doc, "Load families", run, dry_run=ctx.dry_run)
    results = res.get("results", [])
    res["loaded"] = len([r for r in results if r.get("ok") and r.get("result") != "already_loaded"])
    res["failed"] = len([r for r in results if not r.get("ok")])
    for r, path in zip(results, files):
        r["path"] = path
    return core.commit_result(res, fails, ctx.dry_run)


# --------------------------------------------------------------- project settings
_INFO_PROPS = ("Name", "Number", "ClientName", "Address", "Status", "IssueDate", "Author", "BuildingName",
               "OrganizationName", "OrganizationDescription")
_INFO_KEYS = dict((p.lower(), p) for p in _INFO_PROPS)
_INFO_KEYS.update({"project_name": "Name", "project_number": "Number", "client_name": "ClientName",
                   "project_address": "Address", "project_status": "Status", "issue_date": "IssueDate",
                   "project_issue_date": "IssueDate", "building_name": "BuildingName",
                   "organization_name": "OrganizationName",
                   "organization_description": "OrganizationDescription"})
_UNIT_SPECS = {"length": "Length", "area": "Area", "volume": "Volume", "angle": "Angle"}
_UNIT_IDS = {
    "length": {"mm": "Millimeters", "cm": "Centimeters", "m": "Meters", "ft": "Feet", "in": "Inches",
               "ft_in": "FeetFractionalInches", "m_cm": "MetersCentimeters"},
    "area": {"m2": "SquareMeters", "ft2": "SquareFeet", "mm2": "SquareMillimeters", "cm2": "SquareCentimeters"},
    "volume": {"m3": "CubicMeters", "ft3": "CubicFeet", "l": "Liters", "mm3": "CubicMillimeters"},
    "angle": {"deg": "Degrees", "rad": "Radians", "dms": "DegreesMinutes", "grad": "Gradians"},
}


def _forge_units():
    if not (hasattr(DB, "SpecTypeId") and hasattr(DB, "UnitTypeId")):
        raise RvtssError("Project units need Revit 2021 or newer (ForgeTypeId units)", status=501)


def _units_info(doc):
    _forge_units()
    units = doc.GetUnits()
    out = {}
    for key, spec in _UNIT_SPECS.items():
        try:
            fo = units.GetFormatOptions(getattr(DB.SpecTypeId, spec))
            type_id = text_type(fo.GetUnitTypeId().TypeId)
            short = None
            for name, attr in _UNIT_IDS[key].items():
                uid = getattr(DB.UnitTypeId, attr, None)
                if uid is not None and text_type(uid.TypeId) == type_id:
                    short = name
            out[key] = {"unit": short, "unit_type_id": type_id, "rounding": fo.Accuracy}
        except Exception as e:
            out[key] = {"error": normalize_string(text_type(e))}
    return out


def _info(doc):
    pi = doc.ProjectInformation
    out = {}
    for prop in _INFO_PROPS:
        try:
            out[prop] = normalize_string(getattr(pi, prop) or "")
        except Exception:
            pass
    extra = {}
    for p in pi.Parameters:
        try:
            if p.StorageType == DB.StorageType.String and not p.IsReadOnly:
                name = normalize_string(p.Definition.Name)
                extra[name] = normalize_string(p.AsString() or "")
        except Exception:
            continue
    return {"properties": out, "text_parameters": extra}


def _starting_view(doc):
    try:
        svs = DB.StartingViewSettings.GetStartingViewSettings(doc)
        v = doc.GetElement(svs.ViewId) if is_valid_id(svs.ViewId) else None
        return {"view_id": id_int(v) if v is not None else None,
                "view": normalize_string(v.Name) if v is not None else None,
                "last_opened": v is None}
    except Exception as e:
        return {"error": normalize_string(text_type(e))}


def _location(doc, unit):
    out = {}
    try:
        site = doc.SiteLocation
        out.update({"latitude_deg": round(math.degrees(site.Latitude), 6),
                    "longitude_deg": round(math.degrees(site.Longitude), 6),
                    "time_zone": site.TimeZone})
        try:
            out["place_name"] = normalize_string(site.PlaceName or "")
        except Exception:
            pass
    except Exception as e:
        out["site_error"] = normalize_string(text_type(e))
    try:
        loc = doc.ActiveProjectLocation
        pos = loc.GetProjectPosition(DB.XYZ.Zero)
        out.update({"project_location": normalize_string(loc.Name),
                    "east_west": U.from_internal(pos.EastWest, unit, 3),
                    "north_south": U.from_internal(pos.NorthSouth, unit, 3),
                    "elevation": U.from_internal(pos.Elevation, unit, 3),
                    "angle_to_true_north_deg": round(math.degrees(pos.Angle), 6), "unit": unit})
    except Exception as e:
        out["position_error"] = normalize_string(text_type(e))
    return out


def project_settings(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "get")
    dry = ctx.dry_run
    if action == "get":
        wanted = set(ctx.list("include")) or set(["info", "units", "starting_view", "location"])
        out = {}
        if "info" in wanted:
            out["info"] = _info(doc)
        if "units" in wanted:
            try:
                out["units"] = _units_info(doc)
            except RvtssError as e:
                out["units"] = {"error": e.message}
        if "starting_view" in wanted:
            out["starting_view"] = _starting_view(doc)
        if "location" in wanted:
            out["location"] = _location(doc, ctx.unit)
        return out
    if action == "set_info":
        values = ctx.get("values")
        if not isinstance(values, dict) or not values:
            raise RvtssError("'values' is required: {\"Number\": \"P-001\", \"Client Name\": \"...\"}")
        pi = doc.ProjectInformation

        def run():
            changed, failed = [], []
            for key, value in values.items():
                value = u"" if value is None else text_type(value)
                prop = _INFO_KEYS.get(text_type(key).strip().lower().replace(" ", "_")) or \
                    _INFO_KEYS.get(text_type(key).strip().lower().replace(" ", ""))
                try:
                    if prop is not None:
                        old = normalize_string(getattr(pi, prop) or "")
                        setattr(pi, prop, value)
                    else:
                        p = pi.LookupParameter(text_type(key))
                        if p is None:
                            raise RvtssError("no such project information parameter")
                        if p.IsReadOnly:
                            raise RvtssError("parameter is read-only")
                        if p.StorageType != DB.StorageType.String:
                            raise RvtssError("only text parameters can be set here; use set_parameters with "
                                             "element id {}".format(id_int(pi)))
                        old = normalize_string(p.AsString() or "")
                        p.Set(value)
                    changed.append({"name": key, "old": old, "new": normalize_string(value)})
                except Exception as e:
                    failed.append({"name": key, "error": e.message if isinstance(e, RvtssError)
                                   else normalize_string(text_type(e))})
            if failed and ctx.bool("atomic", True):
                raise RvtssError("Some project information values could not be set; nothing was changed",
                                 failed=failed, available=sorted(_info(doc)["text_parameters"]))
            return {"changed": changed, "failed": failed}

        res, fails = core.run_transaction(doc, "Project information", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "set_units":
        _forge_units()
        spec_units = ctx.get("units")
        if not isinstance(spec_units, dict) or not spec_units:
            raise RvtssError("'units' is required: {\"length\": {\"unit\": \"mm\", \"rounding\": 1}, ...}")
        plan = []
        for key, value in spec_units.items():
            k = text_type(key).lower()
            if k not in _UNIT_SPECS:
                raise RvtssError("Unknown quantity '{}': use {}".format(key, ", ".join(sorted(_UNIT_SPECS))))
            if not isinstance(value, dict):
                value = {"unit": value}
            unit_name = value.get("unit")
            if unit_name is not None and unit_name not in _UNIT_IDS[k]:
                raise RvtssError("Unknown {} unit '{}': use {}".format(k, unit_name, ", ".join(sorted(_UNIT_IDS[k]))))
            plan.append((k, unit_name, value.get("rounding")))
        before = _units_info(doc)

        def run():
            units = doc.GetUnits()
            for k, unit_name, rounding in plan:
                spec = getattr(DB.SpecTypeId, _UNIT_SPECS[k])
                fo = units.GetFormatOptions(spec)
                if unit_name is not None:
                    uid = getattr(DB.UnitTypeId, _UNIT_IDS[k][unit_name], None)
                    if uid is None:
                        raise RvtssError("This Revit version has no unit '{}'".format(unit_name), status=501)
                    fo = DB.FormatOptions(uid)
                fo.UseDefault = False
                if rounding is not None:
                    acc = float(rounding)
                    try:
                        valid = fo.IsValidAccuracy(acc)
                    except Exception:
                        valid = True
                    if not valid:
                        raise RvtssError("Rounding {} is not valid for {} in {}".format(
                            rounding, k, unit_name or before.get(k, {}).get("unit")),
                            hint="Use a decimal step such as 1, 0.1, 0.01; fractional feet and inches use "
                                 "fractions of an inch expressed in feet.")
                    fo.Accuracy = acc
                units.SetFormatOptions(spec, fo)
            doc.SetUnits(units)
            return {"units": _units_info(doc)}

        res, fails = core.run_transaction(doc, "Project units", run, dry_run=dry)
        return core.commit_result(res, fails, dry, {"before": before})
    if action == "set_starting_view":
        ref = ctx.get("view")
        svs = DB.StartingViewSettings.GetStartingViewSettings(doc)
        if ref in (None, "", "none", "last_opened"):
            target, name = DB.ElementId.InvalidElementId, None
        else:
            v = core.find_view(doc, ref, default_active=False, uidoc=ctx.uidoc)
            try:
                acceptable = svs.IsAcceptableStartingView(v.Id)
            except Exception:
                acceptable = True
            if not acceptable:
                raise RvtssError("View '{}' cannot be a starting view".format(normalize_string(v.Name)), status=409)
            target, name = v.Id, normalize_string(v.Name)
        before = _starting_view(doc)

        def run():
            svs.ViewId = target
            return {"starting_view": name, "last_opened": name is None}

        res, fails = core.run_transaction(doc, "Starting view", run, dry_run=dry)
        return core.commit_result(res, fails, dry, {"before": before})
    if action == "set_location":
        lat, lon = ctx.float("latitude"), ctx.float("longitude")
        angle = ctx.float("true_north_angle")
        ew, ns, elev = ctx.float("east_west"), ctx.float("north_south"), ctx.float("elevation")
        if all(v is None for v in (lat, lon, angle, ew, ns, elev)):
            raise RvtssError("Give latitude / longitude (degrees), true_north_angle (degrees) or east_west / "
                             "north_south / elevation (in `unit`)")
        if lat is not None and not -90 <= lat <= 90:
            raise RvtssError("latitude must be between -90 and 90 degrees")
        if lon is not None and not -180 <= lon <= 180:
            raise RvtssError("longitude must be between -180 and 180 degrees")
        before = _location(doc, ctx.unit)

        def run():
            if lat is not None or lon is not None:
                site = doc.SiteLocation
                if lat is not None:
                    site.Latitude = math.radians(lat)
                if lon is not None:
                    site.Longitude = math.radians(lon)
            if any(v is not None for v in (angle, ew, ns, elev)):
                loc = doc.ActiveProjectLocation
                pos = loc.GetProjectPosition(DB.XYZ.Zero)
                new = DB.ProjectPosition(
                    U.to_internal(ew, ctx.unit) if ew is not None else pos.EastWest,
                    U.to_internal(ns, ctx.unit) if ns is not None else pos.NorthSouth,
                    U.to_internal(elev, ctx.unit) if elev is not None else pos.Elevation,
                    math.radians(angle) if angle is not None else pos.Angle)
                loc.SetProjectPosition(DB.XYZ.Zero, new)
            return {"location": _location(doc, ctx.unit)}

        res, fails = core.run_transaction(doc, "Project location", run, dry_run=dry)
        return core.commit_result(res, fails, dry, {"before": before})
    raise RvtssError("action must be get, set_info, set_units, set_starting_view or set_location")


# -------------------------------------------------------------------------- styles
_GST = {"projection": "Projection", "cut": "Cut"}


def _gst(name):
    return getattr(DB.GraphicsStyleType, _GST[name])


def _line_patterns(doc):
    return list(DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement))


def _line_pattern_id(doc, name):
    if text_type(name).strip().lower() in ("solid", "<solid>"):
        return DB.LinePatternElement.GetSolidPatternId()
    key = text_type(name).strip().lower()
    for p in _line_patterns(doc):
        if _name(p).lower() == key or text_type(id_int(p)) == key:
            return p.Id
    raise core.not_found("Line pattern", name, ["Solid"] + [_name(p) for p in _line_patterns(doc)])


def _style_info(doc, cat):
    out = {"name": normalize_string(cat.Name), "id": id_int(cat.Id)}
    for key in ("projection", "cut"):
        try:
            w = cat.GetLineWeight(_gst(key))
            out["line_weight_" + key] = int(w) if w is not None else None
        except Exception:
            out["line_weight_" + key] = None
    out["line_color"] = _color_list(getattr(cat, "LineColor", None))
    try:
        pid = cat.GetLinePatternId(_gst("projection"))
        if pid == DB.LinePatternElement.GetSolidPatternId():
            out["line_pattern"] = "Solid"
        else:
            p = doc.GetElement(pid)
            out["line_pattern"] = _name(p) if p is not None else None
    except Exception:
        out["line_pattern"] = None
    try:
        out["material"] = _name(cat.Material) if cat.Material is not None else None
    except Exception:
        out["material"] = None
    return out


def _subcategory(parent, name):
    key = text_type(name).strip().lower()
    for sub in parent.SubCategories:
        if normalize_string(sub.Name).lower() == key:
            return sub
    return None


def _target_category(ctx, doc):
    parent = core.resolve_category(doc, ctx.require("category"))
    sub_name = ctx.get("subcategory")
    if not sub_name:
        return parent, parent
    sub = _subcategory(parent, sub_name)
    if sub is None:
        raise core.not_found("Subcategory of {}".format(normalize_string(parent.Name)), sub_name,
                             [normalize_string(s.Name) for s in parent.SubCategories])
    return parent, sub


def _apply_style(ctx, doc, cat):
    changed = {}
    for key in ("projection", "cut"):
        w = ctx.int("line_weight_" + key if key == "cut" else "line_weight")
        if w is not None:
            if not 1 <= w <= 16:
                raise RvtssError("Line weights are 1-16")
            try:
                cat.SetLineWeight(w, _gst(key))
                changed["line_weight_" + key] = w
            except Exception as e:
                if key == "projection":
                    raise
                ctx.warn("Cut line weight not set: {}".format(normalize_string(text_type(e))))
    if ctx.get("line_color") is not None:
        cat.LineColor = _color(ctx.get("line_color"))
        changed["line_color"] = _color_list(cat.LineColor)
    if ctx.get("line_pattern"):
        cat.SetLinePatternId(_line_pattern_id(doc, ctx.get("line_pattern")), _gst("projection"))
        changed["line_pattern"] = ctx.get("line_pattern")
    if ctx.get("material") is not None:
        mname = text_type(ctx.get("material")).strip()
        if mname.lower() in ("", "none"):
            cat.Material = None
        else:
            mats = list(DB.FilteredElementCollector(doc).OfClass(DB.Material))
            mat = next((m for m in mats if _name(m).lower() == mname.lower()), None)
            if mat is None:
                raise core.not_found("Material", mname, [_name(m) for m in mats])
            cat.Material = mat
        changed["material"] = mname or None
    return changed


def manage_styles(ctx):
    doc = ctx.doc
    action = ctx.get("action", "list_object_styles")
    dry = ctx.dry_run
    if action == "list_object_styles":
        if ctx.get("category"):
            cats = [core.resolve_category(doc, ctx.get("category"))]
        else:
            ctype = {"model": DB.CategoryType.Model, "annotation": DB.CategoryType.Annotation}.get(
                ctx.get("category_type", "model"))
            cats = [c for c in doc.Settings.Categories if ctype is None or c.CategoryType == ctype]
            cats.sort(key=lambda c: normalize_string(c.Name).lower())
        limit = ctx.int("limit", 80, 1, 500)
        include_sub = ctx.bool("include_subcategories", bool(ctx.get("category")))
        out = []
        for c in cats[:limit]:
            d = _style_info(doc, c)
            subs = list(c.SubCategories)
            d["subcategory_count"] = len(subs)
            if include_sub:
                d["subcategories"] = sorted((_style_info(doc, s) for s in subs), key=lambda x: x["name"].lower())
            out.append(d)
        return {"count": len(cats), "truncated": len(cats) > limit, "categories": out}
    if action == "list_patterns":
        wanted = set(ctx.list("kinds")) or set(["line", "fill"])
        out = {}
        if "line" in wanted:
            out["line_patterns"] = ["Solid"] + sorted(_name(p) for p in _line_patterns(doc))
        if "fill" in wanted:
            fills = []
            for f in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
                d = {"id": id_int(f), "name": _name(f)}
                try:
                    fp = f.GetFillPattern()
                    d["target"] = text_type(fp.Target)
                    d["solid"] = bool(fp.IsSolidFill)
                except Exception:
                    pass
                fills.append(d)
            out["fill_patterns"] = sorted(fills, key=lambda d: d["name"].lower())
        return out
    if action == "set_object_style":
        _parent, cat = _target_category(ctx, doc)
        before = _style_info(doc, cat)

        def run():
            changed = _apply_style(ctx, doc, cat)
            if not changed:
                raise RvtssError("Nothing to set: give line_weight, line_weight_cut, line_color, line_pattern "
                                 "or material")
            return {"changed": changed, "style": _style_info(doc, cat)}

        res, fails = core.run_transaction(doc, "Object style", run, dry_run=dry)
        return core.commit_result(res, fails, dry, {"before": before})
    if action in ("create_subcategory", "create_line_style"):
        name = text_type(ctx.require("name")).strip()
        if action == "create_line_style":
            parent = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        else:
            parent = core.resolve_category(doc, ctx.require("category"))
        if _subcategory(parent, name) is not None:
            raise RvtssError("'{}' already exists under {}".format(name, normalize_string(parent.Name)), status=409,
                             hint="Use set_object_style with subcategory='{}' to change it.".format(name))

        def run():
            sub = doc.Settings.Categories.NewSubcategory(parent, name)
            _apply_style(ctx, doc, sub)
            return {"created": _style_info(doc, sub), "parent": normalize_string(parent.Name)}

        res, fails = core.run_transaction(doc, "New subcategory", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "create_line_pattern":
        from System.Collections.Generic import List

        name = text_type(ctx.require("name")).strip()
        segs = ctx.list("segments")
        if len(segs) < 2 or len(segs) % 2:
            raise RvtssError("'segments' needs an even number of entries alternating dash/dot and space, e.g. "
                             "[{type:'dash', length:6}, {type:'space', length:3}]")
        if any(_name(p).lower() == name.lower() for p in _line_patterns(doc)):
            raise RvtssError("Line pattern '{}' already exists".format(name), status=409)
        kinds = {"dash": DB.LinePatternSegmentType.Dash, "space": DB.LinePatternSegmentType.Space,
                 "dot": DB.LinePatternSegmentType.Dot}
        built = List[DB.LinePatternSegment]()
        for s in segs:
            kind = text_type(s.get("type", "")).lower()
            if kind not in kinds:
                raise RvtssError("Segment type must be dash, space or dot")
            length = 0.0 if kind == "dot" else U.to_internal(float(s.get("length") or 0), ctx.unit)
            if kind != "dot" and length <= 0:
                raise RvtssError("Dash and space segments need a positive length")
            built.Add(DB.LinePatternSegment(kinds[kind], length))

        def run():
            lp = DB.LinePattern(name)
            lp.SetSegments(built)
            el = DB.LinePatternElement.Create(doc, lp)
            return {"created": {"id": id_int(el), "name": _name(el), "segments": len(segs)}}

        res, fails = core.run_transaction(doc, "New line pattern", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    if action == "create_fill_pattern":
        name = text_type(ctx.require("name")).strip()
        for f in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
            if _name(f).lower() == name.lower():
                raise RvtssError("Fill pattern '{}' already exists".format(name), status=409)
        target = DB.FillPatternTarget.Model if ctx.get("target", "drafting") == "model" \
            else DB.FillPatternTarget.Drafting
        spacing = ctx.float("spacing")
        if not spacing or spacing <= 0:
            raise RvtssError("'spacing' (in `unit`) is required and must be positive")
        spacing2 = ctx.float("spacing2")
        angle = math.radians(ctx.float("angle", 0.0))

        def run():
            orient = DB.FillPatternHostOrientation.ToHost
            s1 = U.to_internal(spacing, ctx.unit)
            if spacing2:
                fp = DB.FillPattern(name, target, orient, angle, s1, U.to_internal(spacing2, ctx.unit))
            else:
                fp = DB.FillPattern(name, target, orient, angle, s1)
            el = DB.FillPatternElement.Create(doc, fp)
            return {"created": {"id": id_int(el), "name": _name(el), "target": text_type(target),
                                "crosshatch": bool(spacing2)}}

        res, fails = core.run_transaction(doc, "New fill pattern", run, dry_run=dry)
        return core.commit_result(res, fails, dry)
    raise RvtssError("action must be list_object_styles, set_object_style, create_subcategory, "
                     "create_line_style, list_patterns, create_line_pattern or create_fill_pattern")


# ------------------------------------------------------- transfer project standards
def _class_collector(cls_name):
    def collect(d):
        cls = getattr(DB, cls_name, None)
        if cls is None:
            return []
        return list(DB.FilteredElementCollector(d).OfClass(cls))
    return collect


def _view_templates(d):
    return [v for v in DB.FilteredElementCollector(d).OfClass(DB.View) if v.IsTemplate]


STANDARD_KINDS = {
    "view_templates": _view_templates,
    "filters": _class_collector("ParameterFilterElement"),
    "materials": _class_collector("Material"),
    "line_patterns": _class_collector("LinePatternElement"),
    "fill_patterns": _class_collector("FillPatternElement"),
    "text_types": _class_collector("TextNoteType"),
    "dimension_types": _class_collector("DimensionType"),
    "filled_region_types": _class_collector("FilledRegionType"),
    "wall_types": _class_collector("WallType"),
    "floor_types": _class_collector("FloorType"),
    "ceiling_types": _class_collector("CeilingType"),
    "roof_types": _class_collector("RoofType"),
}


class _DuplicateTypes(DB.IDuplicateTypeNamesHandler):
    def __init__(self, abort):
        self.abort = abort
        self.called = False

    def OnDuplicateTypeNamesFound(self, args):
        self.called = True
        return DB.DuplicateTypeAction.Abort if self.abort else DB.DuplicateTypeAction.UseDestinationTypes


def _named_elements(d, kind):
    out = {}
    for e in STANDARD_KINDS[kind](d):
        n = _name(e)
        if n:
            out.setdefault(n, e)
    return out


def transfer_standards(ctx):
    doc = ctx.doc
    core.require_project(doc)
    source = core.resolve_document(ctx.active_doc, ctx.require("source", "title or path of another open document"))
    if source.Equals(doc):
        raise RvtssError("Source and target are the same document", hint="Pass `document` for the target.")
    if source.IsFamilyDocument:
        raise RvtssError("The source must be a project, not a family", status=409)
    kinds = ctx.list("kinds")
    bad = [k for k in kinds if k not in STANDARD_KINDS]
    if bad:
        raise RvtssError("Unknown kinds {}: use {}".format(bad, ", ".join(sorted(STANDARD_KINDS))))
    action = ctx.get("action", "list")
    if action == "list":
        out = {}
        for k in (kinds or sorted(STANDARD_KINDS)):
            src, dst = _named_elements(source, k), _named_elements(doc, k)
            names = sorted(src)
            out[k] = {"in_source": len(names), "already_in_target": len([n for n in names if n in dst]),
                      "new": [n for n in names if n not in dst][:ctx.int("limit", 100, 1, 1000)]}
        return {"source": normalize_string(source.Title), "target": normalize_string(doc.Title), "kinds": out}
    if action != "copy":
        raise RvtssError("action must be list or copy")
    if not kinds:
        raise RvtssError("'kinds' is required for copy: {}".format(", ".join(sorted(STANDARD_KINDS))))
    wanted = set(text_type(n).strip().lower() for n in ctx.list("names"))
    skip_existing = ctx.bool("skip_existing", True)
    to_copy, skipped, plan = [], [], {}
    for k in kinds:
        src, dst = _named_elements(source, k), _named_elements(doc, k)
        picked = []
        for n in sorted(src):
            if wanted and n.lower() not in wanted:
                continue
            if skip_existing and n in dst:
                skipped.append({"kind": k, "name": n, "reason": "already in the target"})
                continue
            picked.append(n)
            to_copy.append(src[n].Id)
        plan[k] = picked
    if wanted:
        found = set(n.lower() for names in plan.values() for n in names) | set(s["name"].lower() for s in skipped)
        missing = sorted(wanted - found)
        if missing:
            raise RvtssError("Not found in the source: {}".format(missing), status=404,
                             hint="transfer_project_standards(action='list') shows the names.")
    summary = {"source": normalize_string(source.Title), "target": normalize_string(doc.Title),
               "to_copy": plan, "to_copy_count": len(to_copy), "skipped": skipped[:200],
               "skipped_count": len(skipped)}
    if not to_copy:
        return dict(summary, message="Nothing to copy.")
    preview = core.confirm_gate(ctx, len(to_copy), "transfer_project_standards")
    dry = preview or ctx.dry_run
    handler = _DuplicateTypes(ctx.get("on_duplicate_types", "use_target") == "abort")

    def run():
        opts = DB.CopyPasteOptions()
        opts.SetDuplicateTypeNamesHandler(handler)
        new_ids = DB.ElementTransformUtils.CopyElements(source, core.to_id_list(to_copy), doc,
                                                        DB.Transform.Identity, opts)
        ids = [id_int(i) for i in new_ids]
        return {"copied_count": len(ids), "new_ids": ids[:500], "duplicate_type_names_found": handler.called}

    res, fails = core.run_transaction(doc, "Transfer project standards", run, dry_run=dry)
    return core.preview_status(core.commit_result(res, fails, dry, summary), preview)


# ------------------------------------------------------------------- worksharing
def _link_instance(doc, ref):
    key = text_type(ref).strip().lower()
    links = list(DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance))
    for li in links:
        names = [_name(li).lower(), _name(doc.GetElement(li.GetTypeId())).lower()]
        if text_type(id_int(li)) == key or key in names or key + ".rvt" in names:
            return li
    raise core.not_found("Revit link instance", ref, [_name(doc.GetElement(li.GetTypeId())) for li in links])


def _central_path(doc):
    try:
        return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(doc.GetWorksharingCentralModelPath())
    except Exception:
        return None


def worksharing(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "status")
    if action == "status":
        out = {"workshared": bool(doc.IsWorkshared)}
        if not doc.IsWorkshared:
            out["message"] = "The model is not workshared."
            return out
        out["central_path"] = _central_path(doc)
        try:
            out["is_detached"] = bool(doc.IsDetached)
        except Exception:
            pass
        owned = []
        for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
            if w.IsEditable or w.Owner:
                owned.append({"name": normalize_string(w.Name), "owner": normalize_string(w.Owner or "") or None,
                              "editable_by_you": bool(w.IsEditable)})
        out["worksets_owned"] = owned
        items = []
        for e in core.get_elements(doc, ctx.list("element_ids")[:500]):
            d = {"id": id_int(e)}
            try:
                d["checkout_status"] = text_type(DB.WorksharingUtils.GetCheckoutStatus(doc, e.Id))
                d["updates_status"] = text_type(DB.WorksharingUtils.GetModelUpdatesStatus(doc, e.Id))
                info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, e.Id)
                d.update({"owner": normalize_string(info.Owner or "") or None,
                          "creator": normalize_string(info.Creator or "") or None,
                          "last_changed_by": normalize_string(info.LastChangedBy or "") or None})
            except Exception as ex:
                d["error"] = normalize_string(text_type(ex))
            items.append(d)
        if items:
            out["elements"] = items
            out["owned_by_others"] = [d["id"] for d in items if d.get("checkout_status") == "OwnedByOtherUser"]
        return out
    if action in ("relinquish", "reload_latest"):
        if not doc.IsWorkshared:
            raise RvtssError("The model is not workshared", status=409)
        label = "Relinquish" if action == "relinquish" else "Reload latest"
        if ctx.dry_run:
            return {"status": "dry_run", "would": action, "central_path": _central_path(doc),
                    "message": "Dry run: nothing was sent to or read from central."}
        core.require_writable(label)
        _require_sync_policy(label)
        _no_open_transaction(doc, label)
        if action == "reload_latest":
            doc.ReloadLatest(DB.ReloadLatestOptions())
            return {"reloaded_latest": True, "central_path": _central_path(doc),
                    "note": "Revit's undo history was cleared by the reload."}
        items = DB.WorksharingUtils.RelinquishOwnership(doc, DB.RelinquishOptions(True),
                                                        DB.TransactWithCentralOptions())
        out = {"relinquished": True, "central_path": _central_path(doc)}
        try:
            out["items"] = {"elements": items.GetRelinquishedElements().Count,
                            "worksets": items.GetRelinquishedWorksets().Count}
        except Exception:
            pass
        return out
    if action in ("acquire_coordinates", "publish_coordinates"):
        li = _link_instance(doc, ctx.require("link"))
        link_doc = li.GetLinkDocument()
        if link_doc is None:
            raise RvtssError("The link is not loaded", status=409, hint="manage_links(action='reload') first.")
        brief = {"link_instance_id": id_int(li), "link": _name(doc.GetElement(li.GetTypeId()))}
        if action == "acquire_coordinates":
            if not hasattr(doc, "AcquireCoordinates"):
                raise RvtssError("Acquire coordinates needs Revit 2018 or newer", status=501)

            def run():
                doc.AcquireCoordinates(li.Id)
                return dict(brief, acquired=True, location=_location(doc, ctx.unit))

            res, fails = core.run_transaction(doc, "Acquire coordinates", run, dry_run=ctx.dry_run)
            return core.commit_result(res, fails, ctx.dry_run)
        if not hasattr(doc, "PublishCoordinates"):
            raise RvtssError("Publish coordinates needs Revit 2018 or newer", status=501)
        target = dict(brief, link_location=normalize_string(link_doc.ActiveProjectLocation.Name))
        if ctx.dry_run or not ctx.confirmed:
            return {"status": "dry_run" if ctx.dry_run else "preview", "requires_confirmation": not ctx.dry_run,
                    "would_publish_to": target,
                    "message": "Publishing changes the linked file's shared coordinates; Revit will ask to save "
                               "the link. Re-run with confirm=true to apply."}

        def run():
            doc.PublishCoordinates(DB.LinkElementId(li.Id, link_doc.ActiveProjectLocation.Id))
            return dict(target, published=True)

        res, fails = core.run_transaction(doc, "Publish coordinates", run)
        out = core.commit_result(res, fails, False)
        out["note"] = "The linked model was modified in memory; save the link when Revit asks (or on sync)."
        return out
    raise RvtssError("action must be status, relinquish, reload_latest, acquire_coordinates or "
                     "publish_coordinates")


def register_project_admin_routes(api):
    @api.route("/insert/files/", methods=["POST"])
    def insert_files_route(doc, uidoc, request):
        return handle(doc, request, insert_files, uidoc=uidoc)

    @api.route("/insert/family/", methods=["POST"])
    def insert_family_route(doc, request):
        return handle(doc, request, load_family)

    @api.route("/project/settings/", methods=["POST"])
    def project_settings_route(doc, uidoc, request):
        return handle(doc, request, project_settings, uidoc=uidoc)

    @api.route("/styles/manage/", methods=["POST"])
    def styles_manage_route(doc, request):
        return handle(doc, request, manage_styles)

    @api.route("/standards/transfer/", methods=["POST"])
    def standards_transfer_route(doc, request):
        return handle(doc, request, transfer_standards)

    @api.route("/worksharing/", methods=["POST"])
    def worksharing_route(doc, uidoc, request):
        return handle(doc, request, worksharing, uidoc=uidoc)

    logger.info("RVTSS insert / project settings / styles / standards / worksharing routes registered")
