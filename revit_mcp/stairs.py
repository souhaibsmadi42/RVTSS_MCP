# -*- coding: UTF-8 -*-
"""Stairs by component (RVTSS v2.3).

Routes:
    POST /stairs/create/   straight runs between two levels, automatic landings between runs,
                           optional railings; one undo step, dry_run rolls everything back

Revit needs a StairsEditScope for stairs, which cannot run inside create_elements' transaction,
so stairs have their own route. Run lines are horizontal; their height is set by the run's
riser count, Revit distributes risers between base and top level.
"""
import logging

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type
from .pure import units as U
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)


def create_stairs(ctx):
    from Autodesk.Revit.DB import Architecture as A

    doc = ctx.doc
    core.require_project(doc)
    core.check_modifiable(doc)
    dry = ctx.dry_run
    if not dry:
        core.require_writable("create_stairs")
    if doc.IsModifiable:
        raise RvtssError("A transaction is already open; stairs need their own edit scope", status=409)
    base = core.find_level(doc, ctx.get("base_level") or ctx.get("level"))
    top = core.find_level(doc, ctx.require("top_level"))
    if top.Elevation <= base.Elevation:
        raise RvtssError("top_level must be above base_level")
    runs = ctx.list("runs") or []
    if not runs and ctx.get("start") and ctx.get("end"):
        runs = [{"start": ctx.get("start"), "end": ctx.get("end")}]
    if not runs:
        raise RvtssError("Give 'runs': [{start:[x,y], end:[x,y], width?}, ...] or start + end")
    width = ctx.get("width")
    just = {"left": A.StairsRunJustification.Left, "right": A.StairsRunJustification.Right}.get(
        ctx.get("justification", "center"), A.StairsRunJustification.Center)
    stype = None
    if ctx.get("type"):
        stype = core.find_type(doc, type_name=ctx.get("type"), of_class=A.StairsType)

    group = DB.TransactionGroup(doc, "RVTSS: Create stairs")
    group.Start()
    result = {}
    try:
        scope = DB.StairsEditScope(doc, "RVTSS: Create stairs")
        stairs_id = scope.Start(base.Id, top.Id)
        t, collector = core._start_tx(doc, "RVTSS: stairs runs")
        made, landings = [], []
        z = 0.0  # run lines are relative to the stairs base (the first run starts on the base level)
        for i, r in enumerate(runs):
            a = U.point_from(r.get("start"), ctx.unit)
            b = U.point_from(r.get("end"), ctx.unit)
            line = DB.Line.CreateBound(DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z))
            run = A.StairsRun.CreateStraightRun(doc, stairs_id, line, just)
            w = r.get("width", width)
            if w is not None:
                run.ActualRunWidth = U.to_internal(w, ctx.unit)
            made.append(run)
            z = run.TopElevation
            if i > 0 and ctx.bool("landings", True):
                try:
                    # returns the new landing ids (a list), not a landing
                    landings.extend(list(A.StairsLanding.CreateAutomaticLanding(doc, made[i - 1].Id, run.Id)))
                except Exception as ex:
                    result.setdefault("landing_errors", []).append(normalize_string(text_type(ex)))
        if t.Commit() != DB.TransactionStatus.Committed:
            raise RvtssError("Revit rejected the stairs runs", status=409, failures=collector.messages)
        scope.Commit(core.FailureCollector())
        stairs = doc.GetElement(stairs_id)
        if stype is not None:
            t2, _c2 = core._start_tx(doc, "RVTSS: stairs type")
            stairs.ChangeTypeId(stype.Id)
            t2.Commit()
        # many stairs types add their railings automatically; only add one when there is none
        st = doc.GetElement(stairs_id)
        railing_ids = [id_int(x) for x in st.GetAssociatedRailings()] if hasattr(st, "GetAssociatedRailings") else []
        if ctx.bool("railings", False) and not railing_ids:
            t3, _c3 = core._start_tx(doc, "RVTSS: stairs railings")
            rt = DB.FilteredElementCollector(doc).OfClass(A.RailingType).FirstElement()
            if rt is not None:
                railing_ids = [id_int(x) for x in A.Railing.Create(doc, stairs_id, rt.Id,
                                                                   A.RailingPlacementPosition.Treads)]
            t3.Commit()
        result.update({
            "stairs_id": id_int(stairs_id), "run_ids": [id_int(r.Id) for r in made],
            "landing_ids": [id_int(l) for l in landings if l is not None], "railing_ids": railing_ids,
            "type": normalize_string(get_element_name(doc.GetElement(st.GetTypeId()))),
            "risers": getattr(st, "ActualRisersNumber", None),
            "riser_height": U.from_internal(st.ActualRiserHeight, ctx.unit, 1) if hasattr(st, "ActualRiserHeight")
            else None, "warnings": collector.messages})
        if dry:
            group.RollBack()
        else:
            group.Assimilate()
    finally:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
    return core.commit_result(result, [], dry, {"unit": ctx.unit})


def register_stairs_routes(api):
    @api.route("/stairs/create/", methods=["POST"])
    def stairs_create_route(doc, request):
        return handle(doc, request, create_stairs)

    logger.info("RVTSS stairs routes registered")
