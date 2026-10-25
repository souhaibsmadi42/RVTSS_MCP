# -*- coding: UTF-8 -*-
"""MEP systems and connectivity (RVTSS v2.2). Read-only.

Routes:
    POST /mep/systems/       mechanical / piping / electrical systems with type, classification, element counts
    POST /mep/connectors/    connectors of elements: domain, shape, size, flow, what they connect to
    POST /mep/disconnects/   open connectors (nothing attached) on ducts, pipes, trays, conduits, fittings, equipment
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int
from .query import collect, query_spec
from .pure import units as U
from .pure import filters as F
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

# categories scanned by default for open connectors
MEP_CATEGORIES = ("OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctTerminal", "OST_FlexDuctCurves",
                  "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves",
                  "OST_PlumbingFixtures", "OST_MechanicalEquipment", "OST_CableTray", "OST_CableTrayFitting",
                  "OST_Conduit", "OST_ConduitFitting", "OST_Sprinklers")


def connector_manager(e):
    """ConnectorManager of an MEP curve (pipe, duct...) or of a family instance (fittings, equipment)."""
    try:
        cm = e.ConnectorManager  # MEPCurve
        if cm is not None:
            return cm
    except Exception:
        pass
    try:
        mm = e.MEPModel  # FamilyInstance
        return mm.ConnectorManager if mm is not None else None
    except Exception:
        return None


def connectors(e):
    cm = connector_manager(e)
    if cm is None:
        return []
    try:
        return [c for c in cm.Connectors]
    except Exception:
        return []


def _enum(v):
    try:
        return str(v)
    except Exception:
        return None


def _is_physical(c):
    try:
        return c.ConnectorType in (DB.ConnectorType.End, DB.ConnectorType.Curve, DB.ConnectorType.Physical)
    except Exception:
        return True


def describe_connector(doc, owner, c, unit):
    d = {"id": c.Id, "domain": _enum(c.Domain), "type": _enum(c.ConnectorType), "connected": c.IsConnected}
    try:
        d["origin"] = core.xyz_list(c.Origin, unit)
    except Exception:
        pass
    try:
        d["shape"] = _enum(c.Shape)
        if c.Shape == DB.ConnectorProfileType.Round:
            d["diameter"] = U.from_internal(c.Radius * 2.0, unit, 1)
        elif c.Shape in (DB.ConnectorProfileType.Rectangular, DB.ConnectorProfileType.Oval):
            d["width"] = U.from_internal(c.Width, unit, 1)
            d["height"] = U.from_internal(c.Height, unit, 1)
    except Exception:
        pass
    for attr in ("Direction", "PipeSystemType", "DuctSystemType", "ElectricalSystemType"):
        try:
            v = getattr(c, attr)
            if v is not None:
                d[attr[0].lower() + "".join("_" + ch.lower() if ch.isupper() else ch for ch in attr[1:])] = _enum(v)
        except Exception:
            continue
    try:
        if c.MEPSystem is not None:
            d["system"] = normalize_string(c.MEPSystem.Name)
    except Exception:
        pass
    peers = []
    try:
        for ref in c.AllRefs:
            o = ref.Owner
            if o is None or o.Id == owner.Id or not _is_physical(ref):
                continue
            peers.append({"element_id": id_int(o), "category": normalize_string(o.Category.Name) if o.Category else None,
                          "connector_id": ref.Id})
    except Exception:
        pass
    d["connected_to"] = peers
    return d


def systems(ctx):
    doc = ctx.doc
    core.require_project(doc)
    domain = (ctx.get("domain") or "").lower()
    contains = (ctx.get("contains") or "").lower()
    out = []
    for s in DB.FilteredElementCollector(doc).OfClass(DB.MEPSystem):
        cls = type(s).__name__
        dom = "electrical" if "Electrical" in cls else ("piping" if "Piping" in cls else
                                                         ("mechanical" if "Mechanical" in cls else "other"))
        if domain and dom != domain:
            continue
        name = normalize_string(s.Name)
        if contains and contains not in name.lower():
            continue
        d = {"id": id_int(s), "name": name, "domain": dom}
        try:
            st = doc.GetElement(s.GetTypeId())
            d["system_type"] = normalize_string(get_element_name(st)) if st else None
        except Exception:
            pass
        for attr, key in (("SystemType", "classification"), ("SystemClassification", "classification")):
            try:
                d[key] = _enum(getattr(s, attr))
                break
            except Exception:
                continue
        try:
            d["element_count"] = s.Elements.Size
        except Exception:
            pass
        try:
            be = s.BaseEquipment
            d["base_equipment"] = core.element_brief(doc, be) if be is not None else None
        except Exception:
            pass
        try:
            d["is_well_connected"] = s.IsWellConnected
        except Exception:
            pass
        if ctx.bool("include_elements", False):
            try:
                d["element_ids"] = [id_int(e) for e in s.Elements][:500]
            except Exception:
                pass
        out.append(d)
    out.sort(key=lambda d: (d["domain"], d["name"]))
    page, meta = F.paginate(out, ctx.int("offset", 0), ctx.int("limit", 200, 1, core.MAX_LIMIT))
    by_domain = {}
    for d in out:
        by_domain[d["domain"]] = by_domain.get(d["domain"], 0) + 1
    return {"count": len(out), "by_domain": by_domain,
            "not_well_connected": [d["name"] for d in out if d.get("is_well_connected") is False][:100],
            "pagination": meta, "systems": page}


def connectors_of(ctx):
    doc = ctx.doc
    ids = ctx.list("element_ids")
    if not ids:
        raise RvtssError("'element_ids' is required (max 50)")
    if len(ids) > 50:
        raise RvtssError("At most 50 elements per call")
    out = []
    for e in core.get_elements(doc, ids):
        cons = connectors(e)
        d = core.element_brief(doc, e)
        d["connectors"] = [describe_connector(doc, e, c, ctx.unit) for c in cons]
        d["open_connectors"] = len([c for c in cons if _is_physical(c) and not c.IsConnected])
        if not cons:
            d["note"] = "no connectors (not an MEP element)"
        out.append(d)
    return {"unit": ctx.unit, "elements": out}


def disconnects(ctx):
    doc = ctx.doc
    core.require_project(doc)
    spec = query_spec(ctx.data)
    if not spec.get("categories") and not spec.get("element_ids") and not spec.get("selection"):
        spec = dict(spec, categories=[c for c in MEP_CATEGORIES if _category_exists(doc, c)])
    elements = collect(ctx, spec, max_scan=ctx.int("max_scan", 300000))
    found = []
    by_cat = {}
    scanned = 0
    for e in elements:
        cons = connectors(e)
        if not cons:
            continue
        scanned += 1
        for c in cons:
            if not _is_physical(c) or c.IsConnected:
                continue
            brief = core.element_brief(doc, e)
            item = {"element_id": brief["id"], "category": brief.get("category"), "family": brief.get("family"),
                    "type": brief.get("type"), "connector_id": c.Id, "domain": _enum(c.Domain),
                    "level": core.element_level(doc, e)}
            try:
                item["origin"] = core.xyz_list(c.Origin, ctx.unit)
            except Exception:
                pass
            try:
                if c.MEPSystem is not None:
                    item["system"] = normalize_string(c.MEPSystem.Name)
            except Exception:
                pass
            found.append(item)
            by_cat[item["category"] or "(none)"] = by_cat.get(item["category"] or "(none)", 0) + 1
    page, meta = F.paginate(found, ctx.int("offset", 0), ctx.int("limit", 200, 1, 2000))
    return {"elements_scanned": scanned, "open_connectors": len(found), "by_category": by_cat, "unit": ctx.unit,
            "note": "An open connector is a physical end with nothing attached: missing fitting, cap, terminal or "
                    "a gap. Equipment connectors waiting for future work are reported too.",
            "pagination": meta, "items": page}


def _category_exists(doc, bic_name):
    try:
        return DB.Category.GetCategory(doc, getattr(DB.BuiltInCategory, bic_name)) is not None
    except Exception:
        return False


def register_mep_routes(api):
    @api.route("/mep/systems/", methods=["POST"])
    def mep_systems_route(doc, request):
        return handle(doc, request, systems)

    @api.route("/mep/connectors/", methods=["POST"])
    def mep_connectors_route(doc, request):
        return handle(doc, request, connectors_of)

    @api.route("/mep/disconnects/", methods=["POST"])
    def mep_disconnects_route(doc, uidoc, request):
        return handle(doc, request, disconnects, uidoc=uidoc)

    logger.info("RVTSS MEP routes registered")

