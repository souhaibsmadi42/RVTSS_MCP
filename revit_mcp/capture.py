# -*- coding: UTF-8 -*-
"""Look at elements: a temporary 3D view framed on them, exported as an image (RVTSS v2.3).

Routes:
    POST /views/capture/   section box around element_ids (+ margin), orientation preset or eye/target,
                           optional isolate / highlight / perspective; PNG or JPG, base64

Everything happens inside a TransactionGroup that is rolled back after the export, so the model,
its views and the undo history are unchanged (works in read-only mode too).
"""
import base64
import logging
import os
import tempfile

from pyrevit import DB

from . import core
from .core import RvtssError, handle
from .compat import id_int, text_type
from .pure import units as U

logger = logging.getLogger(__name__)

# direction the camera looks (forward); the eye sits on the opposite side of the box centre
ORIENTATIONS = {
    "iso_se": (-1.0, 1.0, -1.0), "iso_sw": (1.0, 1.0, -1.0), "iso_ne": (-1.0, -1.0, -1.0),
    "iso_nw": (1.0, -1.0, -1.0), "top": (0.0, 0.0, -1.0), "front": (0.0, 1.0, 0.0),
    "back": (0.0, -1.0, 0.0), "left": (1.0, 0.0, 0.0), "right": (-1.0, 0.0, 0.0),
}


def _union_bbox(elements):
    lo = hi = None
    for e in elements:
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        if lo is None:
            lo, hi = bb.Min, bb.Max
        else:
            lo = DB.XYZ(min(lo.X, bb.Min.X), min(lo.Y, bb.Min.Y), min(lo.Z, bb.Min.Z))
            hi = DB.XYZ(max(hi.X, bb.Max.X), max(hi.Y, bb.Max.Y), max(hi.Z, bb.Max.Z))
    return lo, hi


def _up_for(forward):
    if abs(forward.Z) > 0.999:
        return DB.XYZ.BasisY
    right = forward.CrossProduct(DB.XYZ.BasisZ).Normalize()
    return right.CrossProduct(forward).Normalize()


def _solid_fill(doc):
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            continue
    return None


def _export(doc, view, fmt, pixel_size):
    from System.Collections.Generic import List

    folder = tempfile.mkdtemp(prefix="rvtss_capture_")
    prefix = os.path.join(folder, "capture")
    ieo = DB.ImageExportOptions()
    ieo.ExportRange = DB.ExportRange.SetOfViews
    ids = List[DB.ElementId]()
    ids.Add(view.Id)
    ieo.SetViewsAndSheets(ids)
    ieo.FilePath = prefix
    ft = DB.ImageFileType.JPEGMedium if fmt == "jpg" else DB.ImageFileType.PNG
    ieo.HLRandWFViewsFileType = ft
    ieo.ShadowViewsFileType = ft
    ieo.ImageResolution = DB.ImageResolution.DPI_150
    ieo.ZoomType = DB.ZoomFitType.FitToPage
    ieo.PixelSize = pixel_size
    doc.ExportImage(ieo)
    files = [os.path.join(folder, f) for f in os.listdir(folder)]
    if not files:
        raise RvtssError("Revit exported no image", status=500)
    path = max(files, key=os.path.getsize)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        for f in files:
            try:
                os.remove(f)
            except Exception:
                pass
        try:
            os.rmdir(folder)
        except Exception:
            pass


def capture(ctx):
    doc = ctx.doc
    if doc.IsFamilyDocument:
        raise RvtssError("capture works in project documents", hint="Use get_revit_view in the family editor.")
    elements = core.get_elements(doc, ctx.list("element_ids"))
    if not elements:
        raise RvtssError("element_ids is required")
    lo, hi = _union_bbox(elements)
    if lo is None:
        raise RvtssError("None of the elements has a 3D bounding box (annotation only?)")
    elo, ehi = lo, hi
    margin = U.to_internal(ctx.float("margin", 1000.0), ctx.unit)
    lo = DB.XYZ(lo.X - margin, lo.Y - margin, lo.Z - margin)
    hi = DB.XYZ(hi.X + margin, hi.Y + margin, hi.Z + margin)
    center = (lo + hi) * 0.5
    fmt = "jpg" if text_type(ctx.get("image_format", "png")).lower() in ("jpg", "jpeg") else "png"
    pixel_size = ctx.int("pixel_size", 1024, minimum=128, maximum=4096)
    orientation = ctx.get("orientation", "iso_se")
    if ctx.get("eye") and ctx.get("target"):
        eye = DB.XYZ(*U.point_from(ctx.get("eye"), ctx.unit))
        target = DB.XYZ(*U.point_from(ctx.get("target"), ctx.unit))
        forward = (target - eye).Normalize()
    else:
        if orientation not in ORIENTATIONS:
            raise RvtssError("orientation must be one of {} (or pass eye + target)".format(sorted(ORIENTATIONS)))
        forward = DB.XYZ(*ORIENTATIONS[orientation]).Normalize()
        eye = center - forward * (hi - lo).GetLength() * 1.5
    vft = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
           if t.ViewFamily == DB.ViewFamily.ThreeDimensional]
    if not vft:
        raise RvtssError("The model has no 3D view type")
    ids = core.to_id_list([e.Id for e in elements])

    group = DB.TransactionGroup(doc, "RVTSS: capture (temporary, rolled back)")
    group.Start()
    try:
        t, _collector = core._start_tx(doc, "RVTSS: capture view")
        persp = ctx.bool("perspective", False)
        v = DB.View3D.CreatePerspective(doc, vft[0].Id) if persp else DB.View3D.CreateIsometric(doc, vft[0].Id)
        box = DB.BoundingBoxXYZ()
        box.Min, box.Max = lo, hi
        v.SetSectionBox(box)
        v.SetOrientation(DB.ViewOrientation3D(eye, _up_for(forward), forward))
        v.DetailLevel = DB.ViewDetailLevel.Fine
        # datums run far outside the section box and would shrink the zoom-to-fit image
        for bic in ("OST_Levels", "OST_Grids", "OST_CLines", "OST_SectionBox", "OST_Cameras"):
            try:
                cat = DB.Category.GetCategory(doc, getattr(DB.BuiltInCategory, bic))
                if cat is not None and v.CanCategoryBeHidden(cat.Id):
                    v.SetCategoryHidden(cat.Id, True)
            except Exception:
                pass
        style = ctx.get("display_style", "shaded")
        v.DisplayStyle = {"wireframe": DB.DisplayStyle.Wireframe, "hidden": DB.DisplayStyle.HLR,
                          "realistic": DB.DisplayStyle.Realistic}.get(style, DB.DisplayStyle.ShadingWithEdges)
        if ctx.bool("isolate", False):
            v.IsolateElementsTemporary(ids)
            v.ConvertTemporaryHideIsolateToPermanent()
        if ctx.bool("highlight", True) and not ctx.bool("isolate", False):
            ogs = DB.OverrideGraphicSettings()
            color = DB.Color(255, 120, 0)
            fill = _solid_fill(doc)
            ogs.SetProjectionLineColor(color)
            if fill is not None:
                for setter in ("SetSurfaceForegroundPatternId", "SetProjectionFillPatternId"):
                    if hasattr(ogs, setter):
                        getattr(ogs, setter)(fill)
                        break
                for setter in ("SetSurfaceForegroundPatternColor", "SetProjectionFillColor"):
                    if hasattr(ogs, setter):
                        getattr(ogs, setter)(color)
                        break
            for e in elements:
                v.SetElementOverrides(e.Id, ogs)
        if not persp:
            # image export fits the whole view, not the section box: crop to the elements (view coordinates)
            doc.Regenerate()
            cb = v.CropBox
            inv = cb.Transform.Inverse
            pad = max((ehi - elo).GetLength() * 0.04, U.to_internal(100.0, "mm"))
            corners = [inv.OfPoint(DB.XYZ(x, y, z)) for x in (elo.X - pad, ehi.X + pad)
                       for y in (elo.Y - pad, ehi.Y + pad) for z in (elo.Z - pad, ehi.Z + pad)]
            crop = DB.BoundingBoxXYZ()
            crop.Transform = cb.Transform
            crop.Min = DB.XYZ(min(p.X for p in corners), min(p.Y for p in corners), cb.Min.Z)
            crop.Max = DB.XYZ(max(p.X for p in corners), max(p.Y for p in corners), cb.Max.Z)
            v.CropBox = crop
            v.CropBoxActive = True
            v.CropBoxVisible = False
        if t.Commit() != DB.TransactionStatus.Committed:
            raise RvtssError("Revit rejected the temporary 3D view", status=409)
        data = _export(doc, v, fmt, pixel_size)
    finally:
        if group.HasStarted() and not group.HasEnded():
            group.RollBack()
    return {"image_data": base64.b64encode(data).decode("utf-8"),
            "content_type": "image/jpeg" if fmt == "jpg" else "image/png",
            "file_size_bytes": len(data), "elements": [id_int(e) for e in elements[:50]],
            "orientation": "custom" if ctx.get("eye") else orientation,
            "section_box": {"min": U.point_to((lo.X, lo.Y, lo.Z), ctx.unit),
                            "max": U.point_to((hi.X, hi.Y, hi.Z), ctx.unit)}}


def register_capture_routes(api):
    @api.route("/views/capture/", methods=["POST"])
    def capture_route(doc, uidoc, request):
        return handle(doc, request, capture, uidoc=uidoc)

    logger.info("RVTSS capture routes registered")
