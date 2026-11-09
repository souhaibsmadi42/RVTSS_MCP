# -*- coding: UTF-8 -*-
"""MEP editing: connections and fittings, flex / placeholder / inline parts, insulation, systems (RVTSS v2.4).

Routes:
    POST /mep/connect/          connect two connectors; elbow / tee / cross / transition / union fittings;
                                cap open ends; disconnect
    POST /mep/create/           flex ducts and pipes, duct / pipe placeholders (and converting them), a family
                                instance inserted on a duct or pipe, an air terminal connected to a duct
    POST /mep/insulation/       list / add / remove insulation on ducts and pipes, lining on ducts
    POST /mep/systems/manage/   create a duct or piping system, add / remove elements, rename, set the system
                                type of ducts / pipes; electrical circuits and panel schedules

The Revit API has no automatic duct / pipe sizing; sizes are set with set_parameters.
"""
import logging
import math

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type, bic_from_category
from .mep import connectors, _is_physical
from .pure import units as U
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

DUCT_CATS = ("OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_FlexDuctCurves")
PIPE_CATS = ("OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves")
LINING_CATS = ("OST_DuctCurves", "OST_DuctFitting")
FITTINGS = {"elbow": 2, "transition": 2, "union": 2, "tee": 3, "cross": 4}


def _bic(e):
    try:
        return bic_from_category(e.Category) if e.Category is not None else None
    except Exception:
        return None


def _family(e):
    b = _bic(e)
    if b in DUCT_CATS or b == "OST_DuctTerminal":
        return "duct"
    if b in PIPE_CATS:
        return "pipe"
    return None


def _err(ex):
    return ex.message if isinstance(ex, RvtssError) else normalize_string(text_type(ex))


def _named_type(doc, cls, name, what):
    types = list(DB.FilteredElementCollector(doc).OfClass(cls))
    if not types:
        raise RvtssError("No {} exists in '{}'".format(what, doc.Title), status=409,
                         hint="Start from an MEP template or transfer the types into this project.")
    if name in (None, ""):
        return types[0]
    key = text_type(name).strip().lower()
    for t in types:
        if normalize_string(get_element_name(t)).lower() == key or text_type(id_int(t)) == key:
            return t
    raise core.not_found(what, name, [get_element_name(t) for t in types])


def _physical(e):
    return [c for c in connectors(e) if _is_physical(c)]


def _open(e):
    return [c for c in _physical(e) if not c.IsConnected]


def _nearest_pair(a, b):
    """Closest pair of connectors of two elements, open ones first."""
    ca, cb = _open(a) or _physical(a), _open(b) or _physical(b)
    if not ca or not cb:
        missing = a if not ca else b
        raise RvtssError("Element {} has no connectors".format(id_int(missing)), status=409,
                         hint="Use ducts, pipes, cable trays, conduit, fittings, accessories or equipment.")
    best = None
    for x in ca:
        for y in cb:
            d = x.Origin.DistanceTo(y.Origin)
            if best is None or d < best[0]:
                best = (d, x, y)
    return best


def _nearest_to(e, point, exclude=()):
    best = None
    for c in _open(e) or _physical(e):
        if any(c.Id == x.Id and c.Owner.Id == x.Owner.Id for x in exclude):
            continue
        d = c.Origin.DistanceTo(point)
        if best is None or d < best[0]:
            best = (d, c)
    if best is None:
        raise RvtssError("Element {} has no free connector".format(id_int(e)), status=409)
    return best[1]


# ------------------------------------------------------------------- connect / fittings
def _fitting_connectors(elements, n):
    """Connectors meeting at one joint: the pair of the first two elements, then the nearest of the others."""
    _d, c1, c2 = _nearest_pair(elements[0], elements[1])
    cons = [c1, c2]
    for e in elements[2:n]:
        cons.append(_nearest_to(e, c1.Origin, cons))
    return cons


def connect(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "connect")
    ids = ctx.list("element_ids")
    unit = ctx.unit
    dry = ctx.dry_run

    if action in FITTINGS or action == "connect":
        need = FITTINGS.get(action, 2)
        if len(ids) != need:
            raise RvtssError("{} needs exactly {} element_ids".format(action, need),
                             hint="tee: [run 1, run 2, branch]; cross: [run 1, run 2, branch 1, branch 2].")
        elements = core.get_elements(doc, ids)

        def run():
            cons = _fitting_connectors(elements, need)
            gap = cons[0].Origin.DistanceTo(cons[1].Origin)
            if action == "connect":
                if cons[0].IsConnectedTo(cons[1]):
                    return {"action": action, "already_connected": True}
                if gap > U.to_internal(ctx.float("tolerance", 1.0), unit):
                    raise RvtssError("The nearest connectors are {} {} apart".format(
                        U.from_internal(gap, unit, 1), unit), status=409,
                        hint="Move the ends together (transform_elements) or use action='elbow' / 'transition'.")
                cons[0].ConnectTo(cons[1])
                return {"action": action, "connected": [[id_int(c.Owner), c.Id] for c in cons]}
            create = doc.Create
            if action == "elbow":
                fit = create.NewElbowFitting(cons[0], cons[1])
            elif action == "transition":
                fit = create.NewTransitionFitting(cons[0], cons[1])
            elif action == "union":
                fit = create.NewUnionFitting(cons[0], cons[1])
            elif action == "tee":
                fit = create.NewTeeFitting(cons[0], cons[1], cons[2])
            else:
                fit = create.NewCrossFitting(cons[0], cons[1], cons[2], cons[3])
            if fit is None:
                raise RvtssError("Revit created no {} fitting".format(action), status=409,
                                 hint="Check the routing preferences of the duct / pipe type.")
            out = {"action": action, "fitting_id": id_int(fit)}
            try:
                sym = doc.GetElement(fit.GetTypeId())
                out["fitting_type"] = normalize_string(get_element_name(sym))
            except Exception:
                pass
            return out

        try:
            result, fails = core.run_transaction(doc, "MEP " + action, run, dry_run=dry)
        except RvtssError:
            raise
        except Exception as ex:
            raise RvtssError("Revit could not create the {}: {}".format(action, _err(ex)), status=409,
                             hint="The type's routing preferences need a matching fitting, and the elements "
                                  "must meet at one point (tee / cross: the first two are the straight run).")
        return core.commit_result(result, fails, dry)

    if action == "cap":
        if not ids:
            raise RvtssError("'element_ids' is required (ducts or pipes with open ends)")
        elements = core.get_elements(doc, ids)
        preview = core.confirm_gate(ctx, len(elements), "mep_connect cap")
        dry = preview or ctx.dry_run

        def cap_one(e):
            fam = _family(e)
            before = len(_open(e))
            if before == 0:
                return {"id": id_int(e), "open_ends": 0, "capped": 0}
            if fam == "duct":
                from Autodesk.Revit.DB import Mechanical as M
                M.MechanicalUtils.PlaceCapOnOpenEnds(doc, e.Id, DB.ElementId.InvalidElementId)
            elif fam == "pipe":
                from Autodesk.Revit.DB import Plumbing as P
                P.PlumbingUtils.PlaceCapOnOpenEnds(doc, e.Id, DB.ElementId.InvalidElementId)
            else:
                raise RvtssError("caps exist for ducts and pipes only")
            doc.Regenerate()
            return {"id": id_int(e), "open_ends": before, "capped": before - len(_open(e))}

        def run():
            return {"action": action, "results": core.batch(doc, elements, cap_one, atomic=ctx.bool("atomic", False))}

        result, fails = core.run_transaction(doc, "MEP cap open ends", run, dry_run=dry)
        return core.preview_status(core.commit_result(result, fails, dry), preview)

    if action == "disconnect":
        if not ids or len(ids) > 2:
            raise RvtssError("disconnect needs 1 element (all its connections) or 2 elements (between them)")
        elements = core.get_elements(doc, ids)
        other = elements[1].Id if len(elements) == 2 else None

        def run():
            done = []
            for c in _physical(elements[0]):
                if not c.IsConnected:
                    continue
                for ref in list(c.AllRefs):
                    o = ref.Owner
                    if o is None or o.Id == elements[0].Id or not _is_physical(ref):
                        continue
                    if other is not None and o.Id != other:
                        continue
                    c.DisconnectFrom(ref)
                    done.append({"connector_id": c.Id, "from_element_id": id_int(o), "from_connector_id": ref.Id})
            return {"action": action, "disconnected": done, "count": len(done)}

        result, fails = core.run_transaction(doc, "MEP disconnect", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    raise RvtssError("action must be connect, elbow, tee, cross, transition, union, cap or disconnect")


# ------------------------------------------------------------------------ create parts
def _points(ctx, level, minimum=2):
    raw = ctx.list("points")
    if len(raw) < minimum:
        raise RvtssError("'points' needs at least {} points [[x, y(, z)], ...]".format(minimum))
    off = U.to_internal(ctx.float("offset", 0.0), ctx.unit)
    pts = []
    for p in raw:
        x, y, z = U.point_from(p, ctx.unit)
        pts.append(DB.XYZ(x, y, z if len(list(p)) == 3 else level.Elevation + off))
    for a, b in zip(pts, pts[1:]):
        if a.DistanceTo(b) < 1e-4:
            raise RvtssError("Two consecutive points are the same")
    return pts


def _point(ctx, key="point"):
    v = ctx.get(key)
    if v is None:
        raise RvtssError("'{}' is required: [x, y, z]".format(key))
    x, y, z = U.point_from(v, ctx.unit)
    return DB.XYZ(x, y, z)


def _curve_of(e):
    loc = getattr(e, "Location", None)
    curve = getattr(loc, "Curve", None)
    if curve is None or not isinstance(e, DB.MEPCurve):
        raise RvtssError("Element {} is not a duct or pipe".format(id_int(e)), status=409)
    return loc, curve


def _insert_on_curve(ctx):
    """Break a straight duct / pipe at a point, place a family instance there and connect both sides."""
    doc = ctx.doc
    host = core.get_element(doc, ctx.require("host_id"), "Duct / pipe")
    fam = _family(host)
    if fam not in ("duct", "pipe"):
        raise RvtssError("host_id must be a duct or a pipe", status=409)
    _loc, curve = _curve_of(host)
    if ctx.get("type_id") is not None:
        sym = core.find_type(doc, type_id=ctx.get("type_id"))
    else:
        sym = core.find_type(doc, family=ctx.get("family"), type_name=ctx.require("type"))
    if not isinstance(sym, DB.FamilySymbol):
        raise RvtssError("The type is not a loadable family type")
    point = curve.Project(_point(ctx)).XYZPoint
    ends = (curve.GetEndPoint(0), curve.GetEndPoint(1))
    if min(point.DistanceTo(ends[0]), point.DistanceTo(ends[1])) < 1e-3:
        raise RvtssError("The point is at the end of the duct / pipe; pick a point along it")
    direction = (ends[1] - ends[0]).Normalize()

    def run():
        if not sym.IsActive:
            sym.Activate()
        if fam == "duct":
            from Autodesk.Revit.DB import Mechanical as M
            new_id = M.MechanicalUtils.BreakCurve(doc, host.Id, point)
        else:
            from Autodesk.Revit.DB import Plumbing as P
            new_id = P.PlumbingUtils.BreakCurve(doc, host.Id, point)
        other = doc.GetElement(new_id)
        level = doc.GetElement(host.ReferenceLevel.Id) if getattr(host, "ReferenceLevel", None) is not None else None
        if level is not None:
            inst = doc.Create.NewFamilyInstance(point, sym, level, DB.Structure.StructuralType.NonStructural)
        else:
            inst = doc.Create.NewFamilyInstance(point, sym, DB.Structure.StructuralType.NonStructural)
        doc.Regenerate()
        note = None
        if abs(direction.Z) < 0.999:
            angle = math.atan2(direction.Y, direction.X)
            if abs(angle) > 1e-9:
                axis = DB.Line.CreateBound(point, DB.XYZ(point.X, point.Y, point.Z + 1.0))
                DB.ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle)
        else:
            note = "Vertical run: the instance was not rotated; check its orientation."
        try:
            move = point - inst.Location.Point
            if move.GetLength() > 1e-6:
                DB.ElementTransformUtils.MoveElement(doc, inst.Id, move)
        except Exception:
            pass
        doc.Regenerate()
        connected, errors = [], []
        for c in _physical(inst):
            try:
                # which piece lies on this connector's side of the break
                piece = None
                for cand in (host, other):
                    cl, cc = _curve_of(cand)
                    mid = cc.Evaluate(0.5, True)
                    if ((mid - point).DotProduct(direction) < 0) == ((c.Origin - point).DotProduct(direction) < 0):
                        piece = (cand, cl, cc)
                if piece is None:
                    raise RvtssError("no duct / pipe piece on this side")
                cand, cl, cc = piece
                e0, e1 = cc.GetEndPoint(0), cc.GetEndPoint(1)
                far = e0 if e0.DistanceTo(point) > e1.DistanceTo(point) else e1
                if far.DistanceTo(c.Origin) < 1e-3:
                    raise RvtssError("the remaining piece is shorter than the inserted part")
                cl.Curve = DB.Line.CreateBound(far, c.Origin) if far.IsAlmostEqualTo(e0) \
                    else DB.Line.CreateBound(c.Origin, far)
                doc.Regenerate()
                c.ConnectTo(_nearest_to(cand, c.Origin))
                connected.append({"connector_id": c.Id, "element_id": id_int(cand)})
            except Exception as ex:
                errors.append({"connector_id": c.Id, "error": _err(ex)})
        out = {"action": "insert_on_curve", "id": id_int(inst), "host_id": id_int(host), "new_piece_id": id_int(other),
               "family": normalize_string(sym.FamilyName), "type": normalize_string(get_element_name(sym)),
               "connected": connected}
        if errors:
            out["connection_errors"] = errors
        if note:
            out["note"] = note
        return out

    result, fails = core.run_transaction(doc, "MEP insert on curve", run, dry_run=ctx.dry_run)
    return core.commit_result(result, fails, ctx.dry_run)


def create_parts(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.require("action")
    dry = ctx.dry_run

    if action in ("flex_duct", "flex_pipe", "duct_placeholder", "pipe_placeholder"):
        from System.Collections.Generic import List

        level = core.find_level(doc, ctx.get("level"))
        duct = action.endswith("duct") or action.startswith("duct")
        if duct:
            from Autodesk.Revit.DB import Mechanical as M
            st = _named_type(doc, M.MechanicalSystemType, ctx.get("system_type"), "Duct system type")
        else:
            from Autodesk.Revit.DB import Plumbing as P
            st = _named_type(doc, P.PipingSystemType, ctx.get("system_type"), "Piping system type")
        if action == "flex_duct":
            tt = _named_type(doc, M.FlexDuctType, ctx.get("type"), "Flex duct type")
        elif action == "flex_pipe":
            tt = _named_type(doc, P.FlexPipeType, ctx.get("type"), "Flex pipe type")
        elif action == "duct_placeholder":
            tt = _named_type(doc, M.DuctType, ctx.get("type"), "Duct type")
        else:
            tt = _named_type(doc, P.PipeType, ctx.get("type"), "Pipe type")
        pts = _points(ctx, level)

        def run():
            ids = []
            if action.startswith("flex"):
                plist = List[DB.XYZ]()
                for p in pts:
                    plist.Add(p)
                cls = M.FlexDuct if duct else P.FlexPipe
                ids.append(id_int(cls.Create(doc, st.Id, tt.Id, level.Id, plist)))
            else:
                cls = M.Duct if duct else P.Pipe
                for a, b in zip(pts, pts[1:]):
                    ids.append(id_int(cls.CreatePlaceholder(doc, st.Id, tt.Id, level.Id, a, b)))
            if ctx.get("diameter") is not None:
                bip = "RBS_CURVE_DIAMETER_PARAM" if duct else "RBS_PIPE_DIAMETER_PARAM"
                for e in core.get_elements(doc, ids):
                    p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
                    if p is not None and not p.IsReadOnly:
                        p.Set(U.to_internal(ctx.float("diameter"), ctx.unit))
            return {"action": action, "ids": ids, "type": normalize_string(get_element_name(tt)),
                    "system_type": normalize_string(get_element_name(st))}

        result, fails = core.run_transaction(doc, "MEP " + action.replace("_", " "), run, dry_run=dry)
        return core.commit_result(result, fails, dry, {"unit": ctx.unit})

    if action == "convert_placeholders":
        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("'element_ids' is required (duct or pipe placeholders)")
        ducts = [e.Id for e in elements if _family(e) == "duct"]
        pipes = [e.Id for e in elements if _family(e) == "pipe"]
        if len(ducts) + len(pipes) != len(elements):
            raise RvtssError("Only duct and pipe placeholders can be converted")

        def run():
            out = []
            if ducts:
                from Autodesk.Revit.DB import Mechanical as M
                out.extend(id_int(i) for i in M.MechanicalUtils.ConvertDuctPlaceholders(doc, core.to_id_list(ducts)))
            if pipes:
                from Autodesk.Revit.DB import Plumbing as P
                out.extend(id_int(i) for i in P.PlumbingUtils.ConvertPipePlaceholders(doc, core.to_id_list(pipes)))
            return {"action": action, "created_ids": out}

        result, fails = core.run_transaction(doc, "MEP convert placeholders", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action == "insert_on_curve":
        return _insert_on_curve(ctx)

    if action == "air_terminal_on_duct":
        terminal = core.get_element(doc, ctx.require("terminal_id"), "Air terminal")
        duct_el = core.get_element(doc, ctx.require("host_id"), "Duct")
        from Autodesk.Revit.DB import Mechanical as M

        fn = getattr(M.MechanicalUtils, "ConnectAirTerminalOnDuct", None)
        if fn is None:
            raise RvtssError("This Revit version cannot connect an air terminal on a duct through the API",
                             status=501)

        def run():
            ok = fn(doc, terminal.Id, duct_el.Id)
            if ok is False:
                raise RvtssError("Revit could not connect the air terminal to the duct", status=409,
                                 hint="The terminal must sit on the duct face and be perpendicular to it.")
            return {"action": action, "terminal_id": id_int(terminal), "duct_id": id_int(duct_el)}

        result, fails = core.run_transaction(doc, "MEP air terminal on duct", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    raise RvtssError("action must be flex_duct, flex_pipe, duct_placeholder, pipe_placeholder, "
                     "convert_placeholders, insert_on_curve or air_terminal_on_duct")


# -------------------------------------------------------------------------- insulation
def _layer_ids(doc, e, kind):
    try:
        if kind == "lining":
            return list(DB.InsulationLiningBase.GetLiningIds(doc, e.Id))
        return list(DB.InsulationLiningBase.GetInsulationIds(doc, e.Id))
    except Exception:
        return []


def _layer_info(doc, lid, unit):
    el = doc.GetElement(lid)
    d = {"id": id_int(lid)}
    if el is None:
        return d
    try:
        d["type"] = normalize_string(get_element_name(doc.GetElement(el.GetTypeId())))
    except Exception:
        pass
    try:
        d["thickness"] = U.from_internal(el.Thickness, unit, 1)
    except Exception:
        pass
    return d


def insulation(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.get("action", "list")
    kind = (ctx.get("kind") or "insulation").lower()
    if kind not in ("insulation", "lining"):
        raise RvtssError("kind must be insulation or lining")
    ids = ctx.list("element_ids")
    if not ids:
        raise RvtssError("'element_ids' is required (ducts, pipes, their fittings and accessories)")
    elements = core.get_elements(doc, ids)
    unit = ctx.unit

    if action == "list":
        out = []
        for e in elements:
            d = core.element_brief(doc, e)
            d["insulation"] = [_layer_info(doc, i, unit) for i in _layer_ids(doc, e, "insulation")]
            d["lining"] = [_layer_info(doc, i, unit) for i in _layer_ids(doc, e, "lining")]
            out.append(d)
        return {"unit": unit, "elements": out}

    if action not in ("add", "remove"):
        raise RvtssError("action must be list, add or remove")
    preview = core.confirm_gate(ctx, len(elements), "mep_insulation " + action)
    dry = preview or ctx.dry_run

    if action == "add":
        thickness = ctx.float("thickness")
        if thickness is None or thickness <= 0:
            raise RvtssError("'thickness' (> 0, in `unit`) is required")
        t_int = U.to_internal(thickness, unit)
        cache = {}

        def layer_type(fam):
            key = (fam, kind)
            if key not in cache:
                if kind == "lining":
                    from Autodesk.Revit.DB import Mechanical as M
                    cache[key] = _named_type(doc, M.DuctLiningType, ctx.get("type"), "Duct lining type")
                elif fam == "duct":
                    from Autodesk.Revit.DB import Mechanical as M
                    cache[key] = _named_type(doc, M.DuctInsulationType, ctx.get("type"), "Duct insulation type")
                else:
                    from Autodesk.Revit.DB import Plumbing as P
                    cache[key] = _named_type(doc, P.PipeInsulationType, ctx.get("type"), "Pipe insulation type")
            return cache[key]

        def add_one(e):
            b = _bic(e)
            fam = "duct" if b in DUCT_CATS else ("pipe" if b in PIPE_CATS else None)
            if fam is None or (kind == "lining" and b not in LINING_CATS):
                raise RvtssError("{} cannot take {}".format(normalize_string(e.Category.Name) if e.Category else "element",
                                                           kind))
            if _layer_ids(doc, e, kind):
                if not ctx.bool("replace", False):
                    return {"id": id_int(e), "skipped": "already has {} (pass replace=true)".format(kind)}
                for i in _layer_ids(doc, e, kind):
                    doc.Delete(i)
            lt = layer_type(fam)
            if kind == "lining":
                from Autodesk.Revit.DB import Mechanical as M
                layer = M.DuctLining.Create(doc, e.Id, lt.Id, t_int)
            elif fam == "duct":
                from Autodesk.Revit.DB import Mechanical as M
                layer = M.DuctInsulation.Create(doc, e.Id, lt.Id, t_int)
            else:
                from Autodesk.Revit.DB import Plumbing as P
                layer = P.PipeInsulation.Create(doc, e.Id, lt.Id, t_int)
            return {"id": id_int(e), kind + "_id": id_int(layer), "type": normalize_string(get_element_name(lt))}

        def run():
            return {"action": action, "kind": kind, "thickness": thickness, "unit": unit,
                    "results": core.batch(doc, elements, add_one, atomic=ctx.bool("atomic", False))}
    else:
        def remove_one(e):
            layers = _layer_ids(doc, e, kind)
            for i in layers:
                doc.Delete(i)
            return {"id": id_int(e), "removed": len(layers)}

        def run():
            return {"action": action, "kind": kind,
                    "results": core.batch(doc, elements, remove_one, atomic=ctx.bool("atomic", False))}

    result, fails = core.run_transaction(doc, "MEP {} {}".format(action, kind), run, dry_run=dry)
    return core.preview_status(core.commit_result(result, fails, dry), preview)


# ----------------------------------------------------------------------------- systems
def _system(doc, ref):
    key = text_type(ref).strip().lower()
    for s in DB.FilteredElementCollector(doc).OfClass(DB.MEPSystem):
        if text_type(id_int(s)) == key or normalize_string(s.Name).lower() == key:
            return s
    raise RvtssError("MEP system '{}' not found".format(ref), status=404, hint="list_mep_systems lists them.")


def _connector_set(elements, domain, free_only=True):
    cs = DB.ConnectorSet()
    skipped = []
    for e in elements:
        pick = None
        for c in connectors(e):
            try:
                if c.Domain != domain:
                    continue
                if free_only and c.MEPSystem is not None:
                    continue
            except Exception:
                continue
            pick = c
            break
        if pick is None:
            skipped.append({"id": id_int(e), "reason": "no free connector of this domain"})
        else:
            cs.Insert(pick)
    return cs, skipped


def _circuit_info(doc, c):
    d = {"id": id_int(c), "name": normalize_string(c.Name)}
    for attr, key in (("CircuitNumber", "circuit_number"), ("PanelName", "panel"), ("LoadName", "load_name"),
                      ("SystemType", "system_type")):
        try:
            d[key] = normalize_string(text_type(getattr(c, attr)))
        except Exception:
            pass
    try:
        d["element_ids"] = [id_int(e) for e in c.Elements][:200]
    except Exception:
        pass
    return d


def manage_systems(ctx):
    doc = ctx.doc
    core.require_project(doc)
    action = ctx.require("action")
    dry = ctx.dry_run

    if action == "list_circuits":
        from Autodesk.Revit.DB import Electrical as E

        items = [_circuit_info(doc, c) for c in DB.FilteredElementCollector(doc).OfClass(E.ElectricalSystem)]
        limit = ctx.int("limit", 200, 1, core.MAX_LIMIT)
        return {"count": len(items), "circuits": items[:limit], "truncated": len(items) > limit}

    if action == "create":
        domain = (ctx.get("domain") or "").lower()
        if domain not in ("mechanical", "piping"):
            raise RvtssError("domain must be mechanical or piping (electrical: action='create_circuit')")
        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("'element_ids' is required (terminals, fixtures or equipment)")
        if domain == "mechanical":
            from Autodesk.Revit.DB import Mechanical as M
            st = _named_type(doc, M.MechanicalSystemType, ctx.get("system_type"), "Duct system type")
            cls, dom = M.MechanicalSystem, DB.Domain.DomainHvac
        else:
            from Autodesk.Revit.DB import Plumbing as P
            st = _named_type(doc, P.PipingSystemType, ctx.get("system_type"), "Piping system type")
            cls, dom = P.PipingSystem, DB.Domain.DomainPiping

        def run():
            cs, skipped = _connector_set(elements, dom)
            if cs.Size == 0:
                raise RvtssError("None of the elements has a free {} connector".format(domain), status=409,
                                 skipped=skipped)
            name = ctx.get("name")
            system = cls.Create(doc, st.Id, text_type(name)) if name else cls.Create(doc, st.Id)
            system.Add(cs)
            return {"action": action, "system_id": id_int(system), "name": normalize_string(system.Name),
                    "system_type": normalize_string(get_element_name(st)), "added": cs.Size, "skipped": skipped}

        result, fails = core.run_transaction(doc, "MEP create system", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action in ("add_elements", "remove_elements"):
        system = _system(doc, ctx.require("system"))
        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("'element_ids' is required")
        try:
            dom = [c for c in system.ConnectorManager.Connectors][0].Domain
        except Exception:
            dom = DB.Domain.DomainPiping if "Piping" in type(system).__name__ else DB.Domain.DomainHvac

        def run():
            cs, skipped = _connector_set(elements, dom, free_only=(action == "add_elements"))
            if cs.Size == 0:
                raise RvtssError("No matching connector on the elements", status=409, skipped=skipped)
            if action == "add_elements":
                system.Add(cs)
            else:
                system.Remove(cs)
            return {"action": action, "system_id": id_int(system), "connectors": cs.Size, "skipped": skipped}

        result, fails = core.run_transaction(doc, "MEP system " + action.replace("_", " "), run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action == "rename":
        system = _system(doc, ctx.require("system"))
        name = text_type(ctx.require("name"))

        def run():
            old = normalize_string(system.Name)
            system.Name = name
            return {"action": action, "system_id": id_int(system), "old_name": old, "name": normalize_string(system.Name)}

        result, fails = core.run_transaction(doc, "MEP rename system", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action == "set_system_type":
        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("'element_ids' is required (ducts or pipes)")
        name = ctx.require("system_type")
        preview = core.confirm_gate(ctx, len(elements), "manage_mep_systems set_system_type")
        dry = preview or ctx.dry_run
        cache = {}

        def one(e):
            fam = _family(e)
            if fam not in ("duct", "pipe") or not isinstance(e, DB.MEPCurve):
                raise RvtssError("only ducts and pipes have a system type")
            if fam not in cache:
                if fam == "duct":
                    from Autodesk.Revit.DB import Mechanical as M
                    cache[fam] = _named_type(doc, M.MechanicalSystemType, name, "Duct system type")
                else:
                    from Autodesk.Revit.DB import Plumbing as P
                    cache[fam] = _named_type(doc, P.PipingSystemType, name, "Piping system type")
            st = cache[fam]
            try:
                e.SetSystemType(st.Id)
            except Exception:
                bip = "RBS_DUCT_SYSTEM_TYPE_PARAM" if fam == "duct" else "RBS_PIPING_SYSTEM_TYPE_PARAM"
                p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
                if p is None or p.IsReadOnly:
                    raise RvtssError("the system type of this element is read-only")
                p.Set(st.Id)
            return {"id": id_int(e), "system_type": normalize_string(get_element_name(st))}

        def run():
            return {"action": action, "results": core.batch(doc, elements, one, atomic=ctx.bool("atomic", False))}

        result, fails = core.run_transaction(doc, "MEP set system type", run, dry_run=dry)
        return core.preview_status(core.commit_result(result, fails, dry), preview)

    if action == "create_circuit":
        from Autodesk.Revit.DB import Electrical as E

        elements = core.get_elements(doc, ctx.list("element_ids"))
        if not elements:
            raise RvtssError("'element_ids' is required (electrical fixtures, devices or equipment)")
        kinds = {"power": "PowerCircuit", "data": "Data", "telephone": "Telephone", "fire_alarm": "FireAlarm",
                 "security": "Security", "nurse_call": "NurseCall", "communication": "Communication",
                 "controls": "Controls"}
        kind = (ctx.get("circuit_type") or "power").lower()
        if kind not in kinds:
            raise RvtssError("circuit_type must be one of: {}".format(", ".join(sorted(kinds))))
        panel = core.get_element(doc, ctx.get("panel_id"), "Panel") if ctx.get("panel_id") is not None else None

        def run():
            circuit = E.ElectricalSystem.Create(doc, core.to_id_list([e.Id for e in elements]),
                                                getattr(E.ElectricalSystemType, kinds[kind]))
            if circuit is None:
                raise RvtssError("Revit created no circuit", status=409,
                                 hint="The elements need free electrical connectors of this circuit type.")
            if panel is not None:
                circuit.SelectPanel(panel)
            return dict(_circuit_info(doc, circuit), action=action)

        result, fails = core.run_transaction(doc, "MEP create circuit", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action == "select_panel":
        circuit = core.get_element(doc, ctx.require("circuit_id"), "Circuit")
        panel = core.get_element(doc, ctx.require("panel_id"), "Panel")
        if not hasattr(circuit, "SelectPanel"):
            raise RvtssError("Element {} is not an electrical circuit".format(id_int(circuit)), status=409)

        def run():
            circuit.SelectPanel(panel)
            return dict(_circuit_info(doc, circuit), action=action)

        result, fails = core.run_transaction(doc, "MEP select panel", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    if action == "create_panel_schedule":
        from Autodesk.Revit.DB import Electrical as E

        panel = core.get_element(doc, ctx.require("panel_id"), "Panel")

        def run():
            view = E.PanelScheduleView.CreateInstanceView(doc, panel.Id)
            if view is None:
                raise RvtssError("Revit created no panel schedule", status=409,
                                 hint="The element must be electrical equipment with a distribution system, "
                                      "and a panel schedule template must exist.")
            return {"action": action, "view_id": id_int(view), "name": normalize_string(view.Name),
                    "panel_id": id_int(panel)}

        result, fails = core.run_transaction(doc, "MEP panel schedule", run, dry_run=dry)
        return core.commit_result(result, fails, dry)

    raise RvtssError("action must be create, add_elements, remove_elements, rename, set_system_type, "
                     "list_circuits, create_circuit, select_panel or create_panel_schedule")


def register_mep_edit_routes(api):
    @api.route("/mep/connect/", methods=["POST"])
    def mep_connect_route(doc, request):
        return handle(doc, request, connect)

    @api.route("/mep/create/", methods=["POST"])
    def mep_create_route(doc, request):
        return handle(doc, request, create_parts)

    @api.route("/mep/insulation/", methods=["POST"])
    def mep_insulation_route(doc, request):
        return handle(doc, request, insulation)

    @api.route("/mep/systems/manage/", methods=["POST"])
    def mep_systems_manage_route(doc, request):
        return handle(doc, request, manage_systems)

    logger.info("RVTSS MEP editing routes registered")
