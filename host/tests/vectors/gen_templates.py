# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/templates.py -> templates.json.
Run: uv run --project . python host/tests/vectors/gen_templates.py"""
import os
import shutil
import tempfile

from _lane_c import Recorder
from revit_mcp.pure import templates as T

rec = Recorder("templates")
rec.extra["constants"] = {
    "TEMPLATE_KINDS": dict((k, [list(v[0]), list(v[1])]) for k, v in T.TEMPLATE_KINDS.items()),
    "KIND_CATEGORY": T.KIND_CATEGORY,
    "UNIT_SYSTEM_HINTS": T.UNIT_SYSTEM_HINTS,
}

EN = "C:\\ProgramData\\Autodesk\\RVT 2026\\Family Templates\\English\\"
US = "C:\\ProgramData\\Autodesk\\RVT 2026\\Family Templates\\English-Imperial\\"
PATHS = [
    EN + "Metric Door.rft", EN + "Metric Door - Curtain Wall.rft", EN + "Metric Window.rft",
    EN + "Metric Window - Curtain Wall.rft", EN + "Metric Window with Trim.rft", EN + "Metric Generic Model.rft",
    EN + "Metric Generic Model face based.rft", EN + "Metric Generic Model wall based.rft",
    EN + "Metric Generic Model floor based.rft", EN + "Metric Generic Model ceiling based.rft",
    EN + "Metric Generic Model line based.rft", EN + "Metric Generic Model Adaptive.rft",
    EN + "Metric Generic Model Pattern Based.rft", EN + "Metric Generic Model two level based.rft",
    EN + "Metric Furniture.rft", EN + "Metric Furniture System.rft", EN + "Metric Casework.rft",
    EN + "Metric Casework wall based.rft", EN + "Metric Plumbing Fixture.rft", EN + "Metric Plumbing Fixture wall based.rft",
    EN + "Metric Lighting Fixture.rft", EN + "Metric Lighting Fixture ceiling based.rft",
    EN + "Metric Mechanical Equipment.rft", EN + "Metric Electrical Equipment.rft", EN + "Metric Electrical Fixture.rft",
    EN + "Metric Specialty Equipment.rft", EN + "Metric Column.rft", EN + "Metric Structural Column.rft",
    EN + "Metric Structural Framing - Beams and Braces.rft", EN + "Metric Structural Framing - Complex and Trusses.rft",
    EN + "Metric Structural Foundation.rft", EN + "Metric Structural Stiffener.rft", EN + "Metric Structural Trusses.rft",
    EN + "Metric Entourage.rft", EN + "Metric Planting.rft", EN + "Metric Site.rft", EN + "Metric Parking.rft",
    EN + "Metric Profile.rft", EN + "Metric Profile-Mullion.rft", EN + "Metric Profile-Rail.rft",
    EN + "Metric Profile-Reveal.rft", EN + "Metric Profile-Hosted.rft", EN + "Metric Profile-Stair Nosing.rft",
    EN + "Metric Detail Item.rft", EN + "Metric Detail Item line based.rft", EN + "Metric Mass.rft",
    EN + "Metric Baluster.rft", EN + "Metric Baluster-Panel.rft", EN + "Metric Baluster-Post.rft",
    EN + "Metric Rebar Shape Template.rft",
    EN + "Annotations\\Metric Generic Annotation.rft", EN + "Annotations\\Metric Door Tag.rft",
    EN + "Annotations\\Metric Window Tag.rft", EN + "Annotations\\Metric Room Tag.rft",
    EN + "Annotations\\Metric Multi-Category Tag.rft", EN + "Annotations\\Metric Generic Tag.rft",
    EN + "Titleblocks\\A1 metric.rft", EN + "Titleblocks\\A0 metric.rft", EN + "Title Blocks\\New Size metric.rft",
    EN + "Conceptual Mass\\Metric Mass.rft",
    US + "Door.rft", US + "Door - Curtain Wall.rft", US + "Window.rft", US + "Generic Model.rft",
    US + "Furniture.rft", US + "Structural Column.rft", US + "Titleblocks\\D 22 x 34.rft", US + "Imperial Door.rft",
    "C:/lib/M_Door.rft", "C:/lib/m_window.RFT", "C:/lib/US Door.rft", "/usr/share/rvt/Metric_Generic-Model.rft",
    "Door.rft", "door", "Metric  Door\t(2).rft", "Garage Door.rft", "Door.Panel.rft", ".rft", "..rft", "Mass", "",
    "C:\\templates\\", "C:\\Door.rft\\readme.txt", "Titleblock.rft", "title_block-A3.rft", "Fixed Window.rft",
    "METRIC DOOR.RFT", "Metric Door.rfa", "Doors\\Metric Template.rft", "Metric Door Elevation Tag Thing Extra Long Name Here.rft",
]

UNITS = [None, "metric", "imperial", "bogus", ""]
KINDS = sorted(T.TEMPLATE_KINDS) + ["unknown_kind", ""]

# compact: scores[unit index][kind index] = one score per path
rec.extra["paths"] = PATHS
rec.extra["units"] = UNITS
rec.extra["kinds"] = KINDS
rec.extra["scores"] = [[[T.score(p, k, u) for p in PATHS] for k in KINDS] for u in UNITS]
rec.extra["score_default_unit"] = [[T.score(p, k) for p in PATHS] for k in KINDS]
rec.extra["matches"] = [[T.match(PATHS, k, u) for k in KINDS] for u in UNITS]

rec.call("score", T.score, None, "door", None)
rec.call("score", T.score, None, "door", "metric")
rec.call("score", T.score, "Metric Door.rft", None, "metric")
rec.call("match", T.match, [], "door", None)
rec.call("match", T.match, list(reversed(PATHS)), "door", "metric")
rec.call("match", T.match, ["b Door.rft", "a Door.rft", "Door a.rft", "Door.rft", "Door.rft"], "door", None)

# ---------------------------------------------------------------- find_template_files on a real folder tree
TREE = [
    "one/Metric Door.rft", "one/Metric Window.RFT", "one/readme.txt", "one/Door.rfa", "one/sub/M_Chair.rft",
    "one/sub/deep/er/Metric Mass.rft", "one/sub/deep/notes.rft.txt", "one/a first/Titleblocks/A1 metric.rft",
    "two/Door.rft", "two/zz/Generic Model.rft", "empty/placeholder.txt", "one/.rft", "one/sub/UPPER.Rft",
]
tmp = tempfile.mkdtemp(prefix="rvtss_tpl_")
try:
    for rel in TREE:
        full = os.path.join(tmp, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write("x")
    os.makedirs(os.path.join(tmp, "really empty"))

    def find(dirs, max_files=None):
        """dirs relative to the tree root (None and "" stay as they are) -> found paths relative to the root."""
        real = [d if not d else os.path.join(tmp, *d.split("/")) for d in dirs]
        found = T.find_template_files(real) if max_files is None else T.find_template_files(real, max_files)
        return [f[len(tmp) + 1:] for f in found]

    cases = []
    for dirs, max_files in ((["one"], None), (["one", "two"], None), (["two", "one"], None), (["one", "one"], None),
                            (["one", "one/sub"], None), (["one/sub", "one"], None), ([None, "", "missing", "empty"], None),
                            (["ONE"], None), (["one", "two"], 3), (["one", "two"], 1), (["one", "two"], 5000),
                            (["one/Metric Door.rft"], None), ([], None), (["really empty"], None), (["one/sub/deep"], 1)):
        cases.append({"dirs": dirs, "max_files": max_files, "expected": find(dirs, max_files)})
    # the order of a folder listing is the file system's: compare as sets unless max_files cuts the list
    rec.extra["tree"] = {"files": TREE, "dirs": ["really empty"], "cases": cases}
finally:
    shutil.rmtree(tmp, ignore_errors=True)

rec.save()
