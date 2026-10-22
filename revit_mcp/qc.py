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
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

ALL_CHECKS = ("warnings", "duplicates", "naming", "similar_family_names", "duplicate_types", "unused_families",
              "in_place_families", "cad_imports", "links", "rooms", "views_not_on_sheets", "sheets",
              "required_parameters", "groups")


def _rules(ctx):
    path = os.path.join(core.rvtss_home(), "qc_rules.json")
    rules = {}
    if os.path.isfile(path):
        try:
            with io.open(path, encoding="utf-8") as fh:
                rules = json.load(fh)
        except Exception as e:
            ctx.warn("qc_rules.json is invalid: {}".format(e))
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


CHECKS = {"warnings": _check_warnings, "duplicates": _check_duplicates, "naming": _check_naming,
          "similar_family_names": _check_similar_families, "duplicate_types": _check_duplicate_types,
          "unused_families": _check_unused_families, "in_place_families": _check_in_place, "cad_imports": _check_cad,
          "links": _check_links, "rooms": _check_rooms, "views_not_on_sheets": _check_views, "sheets": _check_sheets,
          "required_parameters": _check_required, "groups": _check_groups}


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


def clashes(ctx):
    doc = ctx.doc
    core.require_project(doc)
    set_a = ctx.get("set_a") or {}
    set_b = ctx.get("set_b") or {}
    if not set_a or not set_b:
        raise RvtssError("set_a and set_b are required, e.g. {categories: ['Ducts']} and {categories: ['Structural Framing']}")
    max_el = ctx.int("max_elements", 2000)
    a_elems = collect(ctx, set_a)[:max_el]
    link = None
    b_doc = doc
    to_b = None
    if set_b.get("link_instance_id") is not None:
        link = core.get_element(doc, set_b["link_instance_id"], "Link")
        if not isinstance(link, DB.RevitLinkInstance) or link.GetLinkDocument() is None:
            raise RvtssError("link_instance_id must be a loaded Revit link", status=409)
        b_doc = link.GetLinkDocument()
        to_b = link.GetTotalTransform().Inverse
    b_cats = [core.resolve_category(b_doc, c).Id for c in set_b.get("categories") or []]
    b_ids = set(set_b.get("element_ids") or [])
    pairs, seen = [], set()
    max_pairs = ctx.int("max_pairs", 200)
    compute_volume = ctx.bool("compute_volume", False)
    checked = 0
    for a in a_elems:
        solids = _solids(a, to_b)
        if not solids:
            continue
        checked += 1
        for s in solids:
            bb = s.GetBoundingBox()
            t = bb.Transform
            p0, p1 = t.OfPoint(bb.Min), t.OfPoint(bb.Max)
            outline = DB.Outline(DB.XYZ(min(p0.X, p1.X), min(p0.Y, p1.Y), min(p0.Z, p1.Z)),
                                 DB.XYZ(max(p0.X, p1.X), max(p0.Y, p1.Y), max(p0.Z, p1.Z)))
            col = DB.FilteredElementCollector(b_doc).WhereElementIsNotElementType()
            if b_cats:
                col = col.WherePasses(DB.ElementMulticategoryFilter(core.to_id_list(b_cats)))
            col = col.WherePasses(DB.BoundingBoxIntersectsFilter(outline)).WherePasses(DB.ElementIntersectsSolidFilter(s))
            for b in col:
                bid = id_int(b)
                if b_doc is doc and bid == id_int(a):
                    continue
                if b_ids and bid not in b_ids:
                    continue
                key = (id_int(a), bid) if link or id_int(a) < bid else (bid, id_int(a))
                if key in seen:
                    continue
                seen.add(key)
                pair = {"a": core.element_brief(doc, a), "b": core.element_brief(b_doc, b)}
                if compute_volume and len(pairs) < 50:
                    vol = 0.0
                    for bs in _solids(b):
                        try:
                            inter = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                                s, bs, DB.BooleanOperationsType.Intersect)
                            vol += inter.Volume if inter else 0.0
                        except Exception:
                            continue
                    pair["intersection_volume"] = U.from_internal(vol, U.length_unit_for("volume", ctx.unit), 6)
                pairs.append(pair)
                if len(pairs) >= max_pairs:
                    break
            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            ctx.warn("Stopped at max_pairs={}".format(max_pairs))
            break
    return {"elements_checked": checked, "set_a_count": len(a_elems), "clash_count": len(pairs),
            "against_link": normalize_string(link.Name) if link else None, "clashes": pairs,
            "note": "Hard (solid intersection) clashes only; clearance/soft clashes are not computed."}


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
