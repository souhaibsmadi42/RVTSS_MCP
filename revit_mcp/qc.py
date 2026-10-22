# -*- coding: UTF-8 -*-
"""BIM coordination and quality control (RVTSS).

Routes:
    POST /qc/model_checks/  configurable checks -> findings with severity, ids and recommendations
    POST /qc/clashes/       hard clashes between two element sets (optionally against a Revit link)
    POST /qc/snapshot/      create / list model snapshots (JSON files) for change detection
    POST /qc/compare/       compare snapshots (or a snapshot with the live model), or match two
                            element sets by location (design model vs shop/fabrication model)

Rules come from the request and from %APPDATA%/RVTSS/qc_rules.json (see pure/rules.py).
"""
import os
import io
import json
import time
import hashlib
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, is_valid_id
from .query import collect, query_spec
from .params_util import find as find_param, read as read_param
from .pure import rules as R
from .pure import diff as D
from .pure import units as U
from .pure import naming as N
from .pure import view_audit as VA
from .pure import clash as CL
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

ALL_CHECKS = ("warnings", "duplicates", "naming", "similar_family_names", "duplicate_types", "unused_families",
              "in_place_families", "cad_imports", "links", "rooms", "views_not_on_sheets", "sheets",
              "required_parameters", "groups", "iso19650", "view_audit")


def _rules(ctx):
    rules, error = core.load_qc_rules()
    if error:
        ctx.warn(error)
    for k, v in (ctx.get("rules") or {}).items():
        rules[k] = v
    return rules


def _check_warnings(ctx, doc, rules):
    groups = {}
    for w in doc.GetWarnings():
        t = normalize_string(w.GetDescriptionText())
        groups.setdefault(t, []).extend(id_int(i) for i in w.GetFailingElements())
    out = []
    serious = ("identical instances", "overlap", "cannot be", "not enclosed", "duplicate", "inaccurate", "joined",
               "highlighted walls overlap", "room separation")
    for t, ids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        sev = "error" if "identical instances" in t.lower() else (
            "warning" if any(s in t.lower() for s in serious) else "info")
        out.append(R.finding("warnings", sev, t, ids, recommendation="Resolve in Revit (Manage > Warnings) or with "
                                                                     "the affected element ids."))
    return out


def _check_duplicates(ctx, doc, rules):
    tol = U.to_internal(ctx.float("duplicate_tolerance", 1.0), ctx.unit)
    buckets = {}
    for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        loc = fi.Location
        if not isinstance(loc, DB.LocationPoint):
            continue
        p = loc.Point
        key = (id_int(fi.Symbol.Id), round(p.X / tol), round(p.Y / tol), round(p.Z / tol),
               round(getattr(loc, "Rotation", 0.0), 3), id_int(fi.LevelId) if is_valid_id(fi.LevelId) else None)
        buckets.setdefault(key, []).append(id_int(fi))
    for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall):
        c = getattr(w.Location, "Curve", None)
        if c is None:
            continue
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        pts = sorted([(round(a.X / tol), round(a.Y / tol), round(a.Z / tol)), (round(b.X / tol), round(b.Y / tol),
                                                                               round(b.Z / tol))])
        buckets.setdefault(("wall", id_int(w.GetTypeId()), tuple(pts)), []).append(id_int(w))
    dups = [ids for ids in buckets.values() if len(ids) > 1]
    if not dups:
        return []
    return [R.finding("duplicates", "error", "{} set(s) of duplicate elements at the same location ({} elements)".format(
        len(dups), sum(len(d) for d in dups)), [i for d in dups for i in d[1:]],
        recommendation="Delete the extra copies (element_ids lists all but the first of each set).",
        sets=dups[:50])]


def _check_naming(ctx, doc, rules):
    naming = rules.get("naming") or {}
    out = []
    if not naming:
        return out
    if "views" in naming:
        out.extend(R.check_names([(id_int(v), normalize_string(v.Name)) for v in DB.FilteredElementCollector(doc)
                                  .OfClass(DB.View) if not v.IsTemplate and v.ViewType not in (
                                      DB.ViewType.Internal, DB.ViewType.ProjectBrowser, DB.ViewType.SystemBrowser,
                                      DB.ViewType.DrawingSheet)], naming["views"], "naming", "views"))
    if "sheets" in naming:
        field = naming["sheets"].get("field", "number")
        out.extend(R.check_names([(id_int(s), normalize_string(s.SheetNumber if field == "number" else s.Name))
                                  for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)],
                                 naming["sheets"], "naming", "sheets"))
    if "levels" in naming:
        out.extend(R.check_names([(id_int(l), normalize_string(l.Name)) for l in
                                  DB.FilteredElementCollector(doc).OfClass(DB.Level)], naming["levels"], "naming", "levels"))
    if "families" in naming:
        out.extend(R.check_names([(id_int(f), normalize_string(f.Name)) for f in
                                  DB.FilteredElementCollector(doc).OfClass(DB.Family) if f.IsEditable],
                                 naming["families"], "naming", "families"))
    if "types" in naming:
        out.extend(R.check_names([(id_int(t), normalize_string(get_element_name(t))) for t in
                                  DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)],
                                 naming["types"], "naming", "family types"))
    out.extend(R.check_duplicate_names([(id_int(v), normalize_string(v.Name)) for v in
                                        DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)], "naming", "sheet"))
    return out


def _check_similar_families(ctx, doc, rules):
    fams = [(id_int(f), normalize_string(f.Name)) for f in DB.FilteredElementCollector(doc).OfClass(DB.Family)
            if f.IsEditable][:600]
    pairs = R.similar_names([n for _i, n in fams])
    if not pairs:
        return []
    by_name = dict((n, i) for i, n in fams)
    return [R.finding("similar_family_names", "warning", "{} pair(s) of near-duplicate family names".format(len(pairs)),
                      [by_name[a] for a, _b in pairs] + [by_name[b] for _a, b in pairs],
                      recommendation="Merge duplicated families (Revit: reload one over the other) and purge.",
                      pairs=[list(p) for p in pairs[:30]])]


def _check_duplicate_types(ctx, doc, rules):
    out = []
    by_family = {}
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            by_family.setdefault(id_int(s.Family.Id), []).append(s)
        except Exception:
            continue
    dups = []
    for fid, syms in by_family.items():
        if len(syms) < 2 or len(syms) > 200:
            continue
        sig = {}
        for s in syms:
            vals = []
            for p in s.Parameters:
                try:
                    if p.Definition.Name in ("Type Name", "Type Mark", "Type Comments", "Description", "Keynote",
                                             "Assembly Code", "URL", "Cost", "Model", "Manufacturer"):
                        continue
                    vals.append(u"{}={}".format(p.Definition.Name, p.AsValueString() or p.AsString() or ""))
                except Exception:
                    continue
            key = hashlib.md5(u"|".join(sorted(vals)).encode("utf-8")).hexdigest()
            sig.setdefault(key, []).append(s)
        for group in sig.values():
            if len(group) > 1:
                dups.append([(id_int(s), normalize_string(s.Family.Name), normalize_string(get_element_name(s)))
                             for s in group])
    if dups:
        out.append(R.finding("duplicate_types", "warning", "{} group(s) of family types with identical values".format(
            len(dups)), [d[0] for g in dups for d in g[1:]],
            recommendation="Swap instances to one type (manage_element_types change_type) and delete the duplicates.",
            groups=[["{} : {}".format(f, t) for _i, f, t in g] for g in dups[:30]]))
    return out


def _check_unused_families(ctx, doc, rules):
    used = set()
    for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        try:
            used.add(id_int(fi.Symbol.Family.Id))
        except Exception:
            continue
    unused = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Family)
              if f.IsEditable and id_int(f) not in used and f.FamilyCategory is not None
              and f.FamilyCategory.CategoryType == DB.CategoryType.Model]
    if not unused:
        return []
    return [R.finding("unused_families", "info", "{} model families have no placed instances".format(len(unused)),
                      [id_int(f) for f in unused], examples=[normalize_string(f.Name) for f in unused[:15]],
                      recommendation="Purge unused families (Manage > Purge Unused) to reduce file size.")]


def _check_in_place(ctx, doc, rules):
    fams = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.Family) if f.IsInPlace]
    if not fams:
        return []
    return [R.finding("in_place_families", "warning", "{} in-place families".format(len(fams)),
                      [id_int(f) for f in fams], examples=[normalize_string(f.Name) for f in fams[:15]],
                      recommendation="Replace in-place families with loadable families where they repeat.")]


def _check_cad(ctx, doc, rules):
    imported = [i for i in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance) if not i.IsLinked]
    if not imported:
        return []
    return [R.finding("cad_imports", "warning", "{} imported (not linked) CAD files".format(len(imported)),
                      [id_int(i) for i in imported],
                      recommendation="Link CAD instead of importing; delete imports that are no longer needed.")]


def _check_links(ctx, doc, rules):
    out = []
    unloaded = [i for i in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance) if i.GetLinkDocument() is None]
    if unloaded:
        out.append(R.finding("links", "error", "{} Revit link(s) not loaded".format(len(unloaded)),
                             [id_int(i) for i in unloaded], examples=[normalize_string(i.Name) for i in unloaded],
                             recommendation="Reload or remove the links (Manage Links)."))
    unpinned = [i for i in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance) if not i.Pinned]
    if unpinned:
        out.append(R.finding("links", "warning", "{} Revit link(s) are not pinned".format(len(unpinned)),
                             [id_int(i) for i in unpinned], recommendation="Pin links to prevent accidental moves."))
    return out


def _check_rooms(ctx, doc, rules):
    unplaced, unbounded = [], []
    for r in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
        if r.Location is None:
            unplaced.append(id_int(r))
        elif r.Area <= 0:
            unbounded.append(id_int(r))
    out = []
    if unplaced:
        out.append(R.finding("rooms", "warning", "{} unplaced rooms".format(len(unplaced)), unplaced,
                             recommendation="Place or delete unplaced rooms."))
    if unbounded:
        out.append(R.finding("rooms", "error", "{} rooms are not enclosed / redundant".format(len(unbounded)), unbounded,
                             recommendation="Fix room boundaries or delete redundant rooms."))
    return out


def _placed_view_ids(doc):
    placed = set()
    for vp in DB.FilteredElementCollector(doc).OfClass(DB.Viewport):
        placed.add(id_int(vp.ViewId))
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance):
        placed.add(id_int(s.ScheduleId))
    return placed


def _check_views(ctx, doc, rules):
    placed = _placed_view_ids(doc)
    kinds = (DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan, DB.ViewType.Section, DB.ViewType.Elevation,
             DB.ViewType.DraftingView, DB.ViewType.Detail, DB.ViewType.EngineeringPlan, DB.ViewType.AreaPlan)
    unplaced = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                if not v.IsTemplate and v.ViewType in kinds and id_int(v) not in placed]
    if not unplaced:
        return []
    return [R.finding("views_not_on_sheets", "info", "{} views are not placed on any sheet".format(len(unplaced)),
                      [id_int(v) for v in unplaced], examples=[normalize_string(v.Name) for v in unplaced[:15]],
                      recommendation="Place them on sheets or delete working views before issue.")]


def _check_sheets(ctx, doc, rules):
    out = []
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if not s.IsPlaceholder]
    empty = [id_int(s) for s in sheets if not list(s.GetAllPlacedViews())]
    if empty:
        out.append(R.finding("sheets", "warning", "{} sheets have no views".format(len(empty)), empty,
                             recommendation="Place views or delete the empty sheets."))
    tb_owner = set(id_int(t.OwnerViewId) for t in DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType())
    no_tb = [id_int(s) for s in sheets if id_int(s) not in tb_owner]
    if no_tb:
        out.append(R.finding("sheets", "warning", "{} sheets have no title block".format(len(no_tb)), no_tb))
    required = ctx.list("sheet_parameters") or rules.get("sheet_parameters") or []
    for pname in required:
        missing = []
        for s in sheets:
            p, _o = find_param(doc, s, pname, allow_type=False)
            if p is None or not (p.AsString() or p.AsValueString()):
                missing.append(id_int(s))
        if missing:
            out.append(R.finding("sheets", "warning", "'{}' is empty on {} sheets".format(pname, len(missing)), missing,
                                 recommendation="Fill sheet parameters with bulk_update_parameter (class_name='ViewSheet')."))
    return out


def _check_required(ctx, doc, rules):
    out = []
    for rule in rules.get("required_parameters") or []:
        for cat in rule.get("categories", []):
            try:
                c = core.resolve_category(doc, cat)
            except RvtssError:
                out.append(R.finding("required_parameters", "warning", "Rule category '{}' not found".format(cat)))
                continue
            elems = list(DB.FilteredElementCollector(doc).OfCategoryId(c.Id).WhereElementIsNotElementType())
            for pname in rule.get("parameters", []):
                missing, empty = [], []
                for e in elems:
                    p, _o = find_param(doc, e, pname)
                    if p is None:
                        missing.append(id_int(e))
                    elif not (p.AsString() or p.AsValueString()):
                        empty.append(id_int(e))
                if missing:
                    out.append(R.finding("required_parameters", rule.get("severity", "error"),
                                         "{}: '{}' missing on {} elements".format(c.Name, pname, len(missing)), missing,
                                         recommendation="Bind the parameter (shared_parameters bind) or update families."))
                if empty:
                    out.append(R.finding("required_parameters", "warning",
                                         "{}: '{}' empty on {} elements".format(c.Name, pname, len(empty)), empty))
    return out


def _check_groups(ctx, doc, rules):
    used = set(id_int(g.GroupType) for g in DB.FilteredElementCollector(doc).OfClass(DB.Group))
    unused = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.GroupType) if id_int(t) not in used]
    if not unused:
        return []
    return [R.finding("groups", "info", "{} group types are unused".format(len(unused)), [id_int(t) for t in unused],
                      examples=[normalize_string(t.Name) for t in unused[:15]], recommendation="Purge unused groups.")]


_NON_VIEWS = ("Internal", "ProjectBrowser", "SystemBrowser", "Undefined", "DrawingSheet")
# view types that are printed / placed on sheets (template and placement checks)
_PRINTABLE = ("FloorPlan", "CeilingPlan", "Section", "Elevation", "DraftingView", "Detail", "EngineeringPlan",
              "AreaPlan", "ThreeD", "Legend", "Schedule")


# view types expected to carry a view template (configurable: view_audit.template_view_types)
_TEMPLATE_TYPES = ("FloorPlan", "CeilingPlan", "Section", "Elevation", "ThreeD", "AreaPlan", "EngineeringPlan")


def _views(doc):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if str(v.ViewType) not in _NON_VIEWS]


def _check_iso19650(ctx, doc, rules):
    scheme = rules.get("iso19650") or {}
    if not scheme.get("targets"):
        return [R.finding("iso19650", "info", "No iso19650 naming scheme configured",
                          recommendation="Add an 'iso19650' section to qc_rules.json "
                                         "(see docs/examples/qc_rules.iso19650.json) or pass rules={iso19650: ...}.")]
    targets = scheme["targets"]
    out = []
    try:
        if "sheets" in targets:
            src = targets["sheets"].get("source", "number")
            out.extend(N.check_items([(id_int(s), normalize_string(s.SheetNumber if src == "number" else s.Name))
                                      for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
                                      if not s.IsPlaceholder], scheme, "sheets"))
        views = _views(doc)
        if "views" in targets:
            out.extend(N.check_items([(id_int(v), normalize_string(v.Name)) for v in views if not v.IsTemplate],
                                     scheme, "views"))
        if "view_templates" in targets:
            out.extend(N.check_items([(id_int(v), normalize_string(v.Name)) for v in views if v.IsTemplate],
                                     scheme, "view_templates"))
        if "families" in targets:
            out.extend(N.check_items([(id_int(f), normalize_string(f.Name)) for f in
                                      DB.FilteredElementCollector(doc).OfClass(DB.Family) if f.IsEditable],
                                     scheme, "families"))
        if "types" in targets:
            out.extend(N.check_items([(id_int(t), normalize_string(get_element_name(t))) for t in
                                      DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)], scheme, "types"))
        if "worksets" in targets:
            if doc.IsWorkshared:
                ws = DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
                out.extend(N.check_items([(w.Id.IntegerValue, normalize_string(w.Name)) for w in ws],
                                         scheme, "worksets"))
            else:
                out.append(R.finding("iso19650", "info", "Worksets not checked: the model is not workshared"))
    except N.SchemeError as e:
        return [R.finding("iso19650", "error", text_type(e), recommendation="Fix the iso19650 section of qc_rules.json")]
    return out


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def _param_id(e, bip_name):
    bip = _bip(bip_name)
    if bip is None:
        return None
    try:
        p = e.get_Parameter(bip)
        if p is not None and is_valid_id(p.AsElementId()):
            return id_int(p.AsElementId())
    except Exception:
        pass
    return None


def _check_view_audit(ctx, doc, rules):
    placed = _placed_view_ids(doc)
    views = []
    for v in _views(doc):
        vt = str(v.ViewType)
        try:
            dependent = is_valid_id(v.GetPrimaryViewId())
        except Exception:
            dependent = False
        views.append({"id": id_int(v), "name": normalize_string(v.Name), "view_type": vt,
                      "is_template": v.IsTemplate,
                      "template_id": id_int(v.ViewTemplateId) if is_valid_id(v.ViewTemplateId) else None,
                      "on_sheet": id_int(v) in placed, "is_dependent": dependent,
                      "printable": vt in _PRINTABLE,
                      # scope box of a view: VIEWER_VOLUME_OF_INTEREST_CROP (looked up defensively)
                      "scope_box_id": _param_id(v, "VIEWER_VOLUME_OF_INTEREST_CROP")})
    # schedules are audited for placement only when asked; they rarely use templates
    if not ctx.bool("include_schedules", False):
        views = [v for v in views if v["view_type"] != "Schedule"]
    sheets = [{"id": id_int(s), "number": normalize_string(s.SheetNumber), "name": normalize_string(s.Name),
               "is_placeholder": s.IsPlaceholder, "view_count": len(list(s.GetAllPlacedViews()))}
              for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)]
    boxes = [{"id": id_int(b), "name": normalize_string(b.Name)} for b in
             DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_VolumeOfInterest)
             .WhereElementIsNotElementType()]
    datum_boxes = set()
    if boxes:
        for cls in (DB.Grid, DB.Level, DB.ReferencePlane):
            for d in DB.FilteredElementCollector(doc).OfClass(cls):
                bid = _param_id(d, "DATUM_VOLUME_OF_INTEREST")
                if bid:
                    datum_boxes.add(bid)
    out = VA.audit(views, sheets, boxes, datum_boxes, ctx.list("template_view_types") or
                   (rules.get("view_audit") or {}).get("template_view_types") or _TEMPLATE_TYPES)
    if boxes and (_bip("VIEWER_VOLUME_OF_INTEREST_CROP") is None or _bip("DATUM_VOLUME_OF_INTEREST") is None):
        out.append(R.finding("view_audit", "info", "Scope box usage could not be read in this Revit version"))
    return out


CHECKS = {"warnings": _check_warnings, "duplicates": _check_duplicates, "naming": _check_naming,
          "similar_family_names": _check_similar_families, "duplicate_types": _check_duplicate_types,
          "unused_families": _check_unused_families, "in_place_families": _check_in_place, "cad_imports": _check_cad,
          "links": _check_links, "rooms": _check_rooms, "views_not_on_sheets": _check_views, "sheets": _check_sheets,
          "required_parameters": _check_required, "groups": _check_groups, "iso19650": _check_iso19650,
          "view_audit": _check_view_audit}


def model_checks(ctx):
    doc = ctx.doc
    core.require_project(doc)
    rules = _rules(ctx)
    checks = ctx.list("checks") or list(ALL_CHECKS)
    unknown = [c for c in checks if c not in CHECKS]
    if unknown:
        raise RvtssError("Unknown checks: {}".format(unknown), hint="Use: " + ", ".join(ALL_CHECKS))
    findings, timings, failed = [], {}, {}
    for name in checks:
        t0 = time.time()
        try:
            findings.extend(CHECKS[name](ctx, doc, rules))
        except Exception as e:
            failed[name] = normalize_string(text_type(e))
        timings[name] = int((time.time() - t0) * 1000)
    min_sev = ctx.get("min_severity", "info")
    findings = [f for f in findings if R.severity_rank(f["severity"]) >= R.severity_rank(min_sev)]
    findings = R.sort_findings(findings)
    out = {"document": normalize_string(doc.Title), "summary": R.summarize(findings),
           "findings": findings[:ctx.int("max_findings", 200)], "timings_ms": timings,
           "rules_file": os.path.join(core.rvtss_home(), "qc_rules.json")}
    if failed:
        out["checks_failed"] = failed
    return out


# ---------------------------------------------------------------------- clashes
def _solids(e, transform=None):
    opt = DB.Options()
    opt.DetailLevel = DB.ViewDetailLevel.Fine
    geom = e.get_Geometry(opt)
    out = []
    if geom is None:
        return out

    def walk(g):
        for obj in g:
            if isinstance(obj, DB.Solid) and obj.Volume > 1e-6:
                out.append(obj)
            elif isinstance(obj, DB.GeometryInstance):
                walk(obj.GetInstanceGeometry())
    walk(geom)
    if transform is not None:
        out = [DB.SolidUtils.CreateTransformed(s, transform) for s in out]
    return out


def _sample_points(solids, n):
    """Points spread over the faces (UV grid, n x n per face) and edges of the solids."""
    pts = []
    for s in solids:
        for face in s.Faces:
            try:
                bb = face.GetBoundingBox()
                for i in range(n):
                    for j in range(n):
                        uv = DB.UV(bb.Min.U + (bb.Max.U - bb.Min.U) * (i + 0.5) / n,
                                   bb.Min.V + (bb.Max.V - bb.Min.V) * (j + 0.5) / n)
                        if face.IsInside(uv):
                            pts.append(face.Evaluate(uv))
            except Exception:
                continue
        for edge in s.Edges:
            for t in (0.0, 0.5, 1.0):
                try:
                    pts.append(edge.Evaluate(t))
                except Exception:
                    continue
    return pts


def _distance_to(p, solids):
    best, best_pt = None, None
    for s in solids:
        for face in s.Faces:
            try:
                r = face.Project(p)
            except Exception:
                r = None
            if r is not None and (best is None or r.Distance < best):
                best, best_pt = r.Distance, r.XYZPoint
        for edge in s.Edges:
            try:
                r = edge.AsCurve().Project(p)
            except Exception:
                r = None
            if r is not None and (best is None or r.Distance < best):
                best, best_pt = r.Distance, r.XYZPoint
    return best, best_pt


def _min_distance(solids_a, solids_b, n):
    """Approximate minimum distance between two solid sets (sampled; never below the true distance)."""
    best = (None, None, None)
    for src, dst, flip in ((solids_a, solids_b, False), (solids_b, solids_a, True)):
        for p in _sample_points(src, n):
            d, q = _distance_to(p, dst)
            if d is not None and (best[0] is None or d < best[0]):
                best = (d, q, p) if flip else (d, p, q)
    return best


def _bbox_center_overlap(a_outline, b_elem, view=None):
    bb = b_elem.get_BoundingBox(view)
    lo, hi = a_outline.MinimumPoint, a_outline.MaximumPoint
    if bb is None:
        return (lo + hi) * 0.5
    mn = DB.XYZ(max(lo.X, bb.Min.X), max(lo.Y, bb.Min.Y), max(lo.Z, bb.Min.Z))
    mx = DB.XYZ(min(hi.X, bb.Max.X), min(hi.Y, bb.Max.Y), min(hi.Z, bb.Max.Z))
    return (mn + mx) * 0.5


def _outline(solid, grow=0.0):
    bb = solid.GetBoundingBox()
    # the box is in the solid's own frame (bb.Transform may rotate): transform all 8
    # corners so the world-aligned outline really encloses the solid
    t = bb.Transform
    corners = [t.OfPoint(DB.XYZ(x, y, z)) for x in (bb.Min.X, bb.Max.X)
               for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]
    return DB.Outline(DB.XYZ(min(c.X for c in corners) - grow, min(c.Y for c in corners) - grow,
                             min(c.Z for c in corners) - grow),
                      DB.XYZ(max(c.X for c in corners) + grow, max(c.Y for c in corners) + grow,
                             max(c.Z for c in corners) + grow))


def project_grids(doc, unit):
    """Straight grids of the host model as plan lines in `unit` (arc / multi-segment grids skipped)."""
    out = []
    for g in DB.FilteredElementCollector(doc).OfClass(DB.Grid):
        c = g.Curve
        if not isinstance(c, DB.Line):
            continue
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        out.append({"name": normalize_string(g.Name),
                    "start": [U.from_internal(a.X, unit, 1), U.from_internal(a.Y, unit, 1)],
                    "end": [U.from_internal(b.X, unit, 1), U.from_internal(b.Y, unit, 1)]})
    return out


def clashes(ctx):
    doc = ctx.doc
    core.require_project(doc)
    set_a = ctx.get("set_a") or {}
    set_b = ctx.get("set_b") or {}
    if not set_a or not set_b:
        raise RvtssError("set_a and set_b are required, e.g. {categories: ['Ducts']} and {categories: ['Structural Framing']}")
    unit = ctx.unit
    clearance = ctx.float("clearance", 0.0) or 0.0
    if clearance < 0:
        raise RvtssError("clearance must be >= 0 (distance in `unit`)")
    clr = U.to_internal(clearance, unit) if clearance else 0.0
    samples = ctx.int("samples", 5, 2, 12)
    group_by = ctx.list("group_by")
    for g in group_by:
        if g not in CL.GROUP_KEYS:
            raise RvtssError("group_by values must be in {}".format(", ".join(CL.GROUP_KEYS)))
    max_el = ctx.int("max_elements", 2000)
    a_elems = collect(ctx, set_a)[:max_el]
    link = None
    b_doc = doc
    to_b = None
    to_host = None
    if set_b.get("link_instance_id") is not None:
        link = core.get_element(doc, set_b["link_instance_id"], "Link")
        if not isinstance(link, DB.RevitLinkInstance) or link.GetLinkDocument() is None:
            raise RvtssError("link_instance_id must be a loaded Revit link", status=409)
        b_doc = link.GetLinkDocument()
        to_host = link.GetTotalTransform()
        to_b = to_host.Inverse
    b_cats = [core.resolve_category(b_doc, c).Id for c in set_b.get("categories") or []]
    b_ids = set(set_b.get("element_ids") or [])
    if ctx.dry_run:
        return {"status": "dry_run", "set_a_count": len(a_elems), "set_b_categories": len(b_cats),
                "clearance": clearance, "unit": unit, "against_link": normalize_string(link.Name) if link else None,
                "note": "No geometry was checked. Run without dry_run to compute clashes."}
    pairs, seen = [], set()
    max_pairs = ctx.int("max_pairs", 200)
    compute_volume = ctx.bool("compute_volume", False)
    checked = 0
    b_solids_cache = {}

    def host_pt(p):
        return to_host.OfPoint(p) if to_host is not None and p is not None else p

    def b_solids(b):
        key = id_int(b)
        if key not in b_solids_cache:
            b_solids_cache[key] = _solids(b)
        return b_solids_cache[key]

    for a in a_elems:
        solids = _solids(a, to_b)
        if not solids:
            continue
        checked += 1
        for s in solids:
            outline = _outline(s, clr)
            col = DB.FilteredElementCollector(b_doc).WhereElementIsNotElementType()
            if b_cats:
                col = col.WherePasses(DB.ElementMulticategoryFilter(core.to_id_list(b_cats)))
            col = col.WherePasses(DB.BoundingBoxIntersectsFilter(outline))
            hard_filter = DB.ElementIntersectsSolidFilter(s)
            for b in col:
                bid = id_int(b)
                if b_doc is doc and bid == id_int(a):
                    continue
                if b_ids and bid not in b_ids:
                    continue
                key = (id_int(a), bid) if link or id_int(a) < bid else (bid, id_int(a))
                if key in seen:
                    continue
                hard = hard_filter.PassesFilter(b)
                distance = 0.0
                point = None
                if not hard:
                    if not clr:
                        continue
                    other = b_solids(b)
                    if not other:
                        continue
                    distance, pa, pb = _min_distance([s], other, samples)
                    if distance is None or distance > clr:
                        continue
                    point = (pa + pb) * 0.5
                else:
                    point = _bbox_center_overlap(outline, b)
                seen.add(key)
                pair = {"a": core.element_brief(doc, a), "b": core.element_brief(b_doc, b),
                        "type": "hard" if hard else "clearance",
                        "distance": 0.0 if hard else U.from_internal(distance, unit, 1),
                        "level": core.element_level(doc, a)}
                hp = host_pt(point)
                if hp is not None:
                    pair["point"] = [U.from_internal(c, unit, 1) for c in (hp.X, hp.Y, hp.Z)]
                if hard and compute_volume and len(pairs) < 50:
                    vol = 0.0
                    for bs in b_solids(b):
                        try:
                            inter = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                                s, bs, DB.BooleanOperationsType.Intersect)
                            vol += inter.Volume if inter else 0.0
                        except Exception:
                            continue
                    pair["intersection_volume"] = U.from_internal(vol, U.length_unit_for("volume", unit), 6)
                pairs.append(pair)
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            ctx.warn("Stopped at max_pairs={}".format(max_pairs))
            break
    grids = project_grids(doc, unit) if ctx.bool("locate", True) else []
    CL.locate(pairs, grids)
    out = {"elements_checked": checked, "set_a_count": len(a_elems), "clash_count": len(pairs),
           "hard_count": len([p for p in pairs if p["type"] == "hard"]),
           "clearance_count": len([p for p in pairs if p["type"] == "clearance"]),
           "clearance": clearance, "unit": unit,
           "against_link": normalize_string(link.Name) if link else None, "clashes": pairs,
           "groups": dict((g, CL.group_clashes(pairs, g)) for g in group_by) or None,
           "grids": grids if ctx.bool("include_grids", False) else None,
           "document": normalize_string(doc.Title), "created": time.strftime("%Y-%m-%d %H:%M")}
    if clearance:
        out["note"] = ("Clearance distances are sampled ({0}x{0} points per face plus edges): they are never "
                       "below the true distance, so pairs just inside the clearance can be missed - raise "
                       "`samples` for critical checks.").format(samples)
    return out


# --------------------------------------------------------------------- snapshot
def _snapshot(ctx, doc, spec, track, transform=None, hash_all=False):
    unit = "mm"
    if spec:
        elements = collect(_DocCtx(ctx, doc), spec)
    else:
        elements = [e for e in DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
                    if e.Category is not None and e.Category.CategoryType == DB.CategoryType.Model
                    and not isinstance(e, DB.ElementType)]
    records = []
    for e in elements:
        b = core.element_brief(doc, e)
        p = core.element_point(e)
        if p is not None and transform is not None:
            p = transform.OfPoint(p)
        rec = {"uid": e.UniqueId, "id": id_int(e), "category": b.get("category"), "family": b.get("family"),
               "type": b.get("type"), "level": core.element_level(doc, e),
               "loc": [round(U.from_internal(c, unit), 1) for c in (p.X, p.Y, p.Z)] if p is not None else None}
        vals = {}
        for n in track:
            prm, _o = find_param(doc, e, n, allow_type=False)
            if prm is not None:
                r = read_param(doc, prm, unit)
                vals[n] = r.get("display", r.get("value"))
        if hash_all:
            items = []
            for prm in e.Parameters:
                try:
                    items.append(u"{}={}".format(prm.Definition.Name, prm.AsValueString() or prm.AsString() or ""))
                except Exception:
                    continue
            rec["phash"] = hashlib.md5(u"|".join(sorted(items)).encode("utf-8")).hexdigest()
        else:
            rec["phash"] = hashlib.md5(json.dumps(vals, sort_keys=True, default=text_type).encode("utf-8")).hexdigest()
        rec["params"] = vals
        records.append(rec)
    return {"document": normalize_string(doc.Title), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "unit": unit,
            "tracked_parameters": track, "hash_all_parameters": hash_all, "elements": records}


class _DocCtx(object):
    """Minimal ctx for collect() against another document (e.g. a link)."""

    def __init__(self, ctx, doc):
        self.doc = doc
        self.uidoc = ctx.uidoc
        self.warnings = ctx.warnings

    def warn(self, m):
        self.warnings.append(m)


def _snapshot_path(ctx, name=None, path=None):
    if path:
        return path
    if not name:
        raise RvtssError("Pass a snapshot 'name' or 'path'")
    safe = "".join(c for c in name if c.isalnum() or c in "-_. ")
    return os.path.join(core.rvtss_subdir("snapshots"), safe + ".json")


def _source_doc(ctx, link_id):
    if link_id is None:
        return ctx.doc, None
    link = core.get_element(ctx.doc, link_id, "Link")
    if not isinstance(link, DB.RevitLinkInstance) or link.GetLinkDocument() is None:
        raise RvtssError("link_instance_id must be a loaded Revit link", status=409)
    return link.GetLinkDocument(), link.GetTotalTransform()


def snapshot(ctx):
    action = ctx.get("action", "create")
    if action == "list":
        folder = core.rvtss_subdir("snapshots")
        files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
        return {"folder": folder, "snapshots": [{"name": f[:-5], "size_kb": int(os.path.getsize(os.path.join(folder, f)) / 1024),
                                                 "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(
                                                     os.path.getmtime(os.path.join(folder, f))))} for f in files]}
    doc, transform = _source_doc(ctx, ctx.get("link_instance_id"))
    spec = query_spec(ctx.data)
    track = ctx.list("track_parameters") or ["Mark", "Comments"]
    snap = _snapshot(ctx, doc, spec, track, transform, ctx.bool("hash_all_parameters", False))
    path = _snapshot_path(ctx, ctx.get("name"), ctx.get("path"))
    if os.path.exists(path) and not ctx.bool("overwrite", False):
        raise RvtssError("Snapshot exists: {}".format(path), status=409, hint="Pass overwrite=true or another name.")
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text_type(json.dumps(snap, ensure_ascii=False)))
    cats = {}
    for r in snap["elements"]:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    return {"path": path, "elements": len(snap["elements"]), "by_category": dict(sorted(cats.items(), key=lambda kv: -kv[1])[:30]),
            "source": snap["document"]}


def _load_snapshot(path):
    if not os.path.isfile(path):
        raise RvtssError("Snapshot not found: {}".format(path), status=404, hint="qc_snapshot(action='list')")
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def compare(ctx):
    mode = ctx.get("mode", "snapshots")
    max_items = ctx.int("max_items", 300)
    if mode == "snapshots":
        a = _load_snapshot(_snapshot_path(ctx, ctx.get("baseline"), ctx.get("baseline_path")))
        if ctx.get("current") or ctx.get("current_path"):
            b = _load_snapshot(_snapshot_path(ctx, ctx.get("current"), ctx.get("current_path")))
        else:
            spec = query_spec(ctx.data)
            b = _snapshot(ctx, ctx.doc, spec, a.get("tracked_parameters") or ["Mark", "Comments"], None,
                          a.get("hash_all_parameters", False))
        result = D.diff_snapshots(a, b, ctx.float("move_tolerance", 1.0), max_items)
        result.update({"baseline": a.get("created"), "baseline_document": a.get("document"),
                       "compared_with": b.get("created") if ctx.get("current") else "live model"})
        return result
    if mode == "match":
        source = ctx.get("source") or {}
        target = ctx.get("target") or {}
        sdoc, st = _source_doc(ctx, source.get("link_instance_id"))
        tdoc, tt = _source_doc(ctx, target.get("link_instance_id"))
        s = _snapshot(ctx, sdoc, query_spec(source) or None, [], st)
        t = _snapshot(ctx, tdoc, query_spec(target) or None, [], tt)
        keys = tuple(ctx.list("match_on") or ["category"])
        result = D.match_by_location(s["elements"], t["elements"], ctx.float("tolerance", 50.0), keys, max_items)
        result.update({"source_document": s["document"], "target_document": t["document"], "unit": "mm",
                       "tolerance": ctx.float("tolerance", 50.0)})
        return result
    raise RvtssError("mode must be snapshots or match")


def register_qc_routes(api):
    @api.route("/qc/model_checks/", methods=["POST"])
    def qc_model_checks_route(doc, request):
        return handle(doc, request, model_checks)

    @api.route("/qc/clashes/", methods=["POST"])
    def qc_clashes_route(doc, uidoc, request):
        return handle(doc, request, clashes, uidoc=uidoc)

    @api.route("/qc/snapshot/", methods=["POST"])
    def qc_snapshot_route(doc, uidoc, request):
        return handle(doc, request, snapshot, uidoc=uidoc)

    @api.route("/qc/compare/", methods=["POST"])
    def qc_compare_route(doc, uidoc, request):
        return handle(doc, request, compare, uidoc=uidoc)

    logger.info("RVTSS QC routes registered")
