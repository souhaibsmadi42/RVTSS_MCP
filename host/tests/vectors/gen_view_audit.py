# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/view_audit.py -> view_audit.json.
Run: uv run --project . python host/tests/vectors/gen_view_audit.py"""
import random

from _lane_c import Recorder
from revit_mcp.pure import view_audit as VA

rec = Recorder("view_audit")


def audit(views, sheets, scope_boxes, datum_scope_box_ids="<default>", require_template_types="<default>"):
    if datum_scope_box_ids == "<default>":
        return VA.audit(views, sheets, scope_boxes)
    datum = set(datum_scope_box_ids) if datum_scope_box_ids is not None else None  # the route passes a set
    if require_template_types == "<default>":
        return VA.audit(views, sheets, scope_boxes, datum)
    return VA.audit(views, sheets, scope_boxes, datum, require_template_types)


views = [
    {"id": 1, "name": "L1 Plan", "view_type": "FloorPlan", "template_id": 10, "on_sheet": True},
    {"id": 2, "name": "L1 Plan", "view_type": "CeilingPlan", "template_id": None, "on_sheet": False},
    {"id": 3, "name": "Working", "view_type": "FloorPlan", "template_id": None, "on_sheet": False,
     "scope_box_id": 50},
    {"id": 4, "name": "Dep", "view_type": "FloorPlan", "template_id": 10, "on_sheet": False, "is_dependent": True},
    {"id": 10, "name": "T-Plan", "is_template": True}, {"id": 11, "name": "T-Unused", "is_template": True},
]
sheets = [{"id": 20, "number": "A-100", "name": "Plans", "view_count": 1},
          {"id": 21, "number": "A-101", "name": "Empty", "view_count": 0},
          {"id": 22, "number": "X", "name": "Placeholder", "view_count": 0, "is_placeholder": True}]
boxes = [{"id": 50, "name": "SB-View"}, {"id": 51, "name": "SB-Grid"}, {"id": 52, "name": "SB-Idle"}]

rec.call("audit", audit, views, sheets, boxes, [51], ["FloorPlan", "CeilingPlan"])
rec.call("audit", audit, views, [], [], None, ["FloorPlan"])
rec.call("audit", audit, views, sheets, boxes)
rec.call("audit", audit, views, sheets, boxes, None)
rec.call("audit", audit, views, sheets, boxes, [], [])
rec.call("audit", audit, views, sheets, boxes, [50, 51, 52], None)
rec.call("audit", audit, views, sheets, None, [51], ["Section"])
rec.call("audit", audit, [], [], [])
rec.call("audit", audit, [], [], boxes)
rec.call("audit", audit, [], sheets, [], [51])
rec.call("audit", audit, views, sheets, boxes, [51.0, 52.0], ["FloorPlan"])  # 51 == 51.0 in a set

more = [
    {"id": 100, "name": "  Dup  ", "view_type": "Section", "template_id": 0, "on_sheet": 0, "printable": True},
    {"id": 101, "name": "dup", "view_type": "Section", "template_id": "", "on_sheet": None},
    {"id": 102, "name": "DUP", "view_type": "Elevation", "template_id": 10.0, "on_sheet": 1},
    {"id": 103, "name": "", "view_type": None, "on_sheet": False},
    {"id": 104, "name": None, "on_sheet": False},
    {"id": 105, "name": "   ", "view_type": "Legend", "printable": False},
    {"id": 106, "name": "Schedule", "view_type": "Schedule", "printable": False, "template_id": 12},
    {"id": 107, "name": "schedule", "view_type": "Schedule", "printable": 0, "scope_box_id": 53},
    {"id": 108, "name": "Other", "view_type": 5, "printable": None},
    {"id": 109, "name": "Other", "view_type": 5, "printable": 1, "is_dependent": True},
    {"id": 12, "name": "T-Sched", "is_template": True, "scope_box_id": 54},
    {"id": 13, "name": "T-Plan", "is_template": 1, "template_id": 11},
    {"id": "t-14", "name": "T-Text id", "is_template": True},
]
boxes2 = boxes + [{"id": 53, "name": "SB-53"}, {"id": 54, "name": "SB-Template"}, {"id": "x", "name": "SB-Text"},
                  {"id": 55.0, "name": "SB-Float"}]
sheets2 = sheets + [{"id": 23, "view_count": None}, {"id": 24, "number": None, "name": "No number"},
                    {"id": 25, "number": 7, "name": "Seven", "view_count": 2, "is_placeholder": True},
                    {"id": 26, "number": "A-102", "name": "Placeholder off", "is_placeholder": False, "view_count": 0.0}]
rec.call("audit", audit, views + more, sheets2, boxes2, [55, "x"], ["FloorPlan", "Section", None, 5])
rec.call("audit", audit, views + more, sheets2, boxes2)
rec.call("audit", audit, more, sheets2, boxes2, [], ["Elevation"])
rec.call("audit", audit, list(reversed(views + more)), list(reversed(sheets2)), list(reversed(boxes2)), [53])

# more than 15 examples / more than 50 ids
big = [{"id": i, "name": "View %03d" % (i % 40), "view_type": ["FloorPlan", "Section", "ThreeD"][i % 3],
        "template_id": None if i % 4 else 900, "on_sheet": i % 5 == 0} for i in range(1, 121)]
big += [{"id": 900 + i, "name": "T%d" % i, "is_template": True} for i in range(20)]
rec.call("audit", audit, big, [{"id": 2000 + i, "number": "S-%d" % i, "name": "Sheet", "view_count": 0} for i in range(60)],
         [{"id": 3000 + i, "name": "Box %d" % i} for i in range(18)], [3001], ["FloorPlan", "Section"])
rec.call("audit", audit, big, [], [], None, None)

# missing keys
rec.call("audit", audit, [{"name": "no id"}], [], [])  # KeyError
rec.call("audit", audit, [{"id": 1}], [], [])  # KeyError: name
rec.call("audit", audit, [{"id": 1, "template_id": 5, "on_sheet": True, "name": "x"}, {"name": "t", "is_template": True}], [], [])
rec.call("audit", audit, [], [{"number": "A"}], [])  # KeyError
rec.call("audit", audit, [], [], [{"name": "box"}])  # KeyError
rec.call("audit", audit, [{"id": 1, "template_id": 5, "on_sheet": True, "name": "x"}], [], [{"id": 9}])  # KeyError: name

rnd = random.Random(42)
for n in range(30):
    vs = []
    for i in range(rnd.randint(0, 14)):
        v = {"id": i + 1, "name": rnd.choice(["Plan", "plan ", "Section A", "3D", "", "Detail"]),
             "view_type": rnd.choice(["FloorPlan", "Section", "ThreeD", None])}
        if rnd.random() < 0.25:
            v["is_template"] = True
        else:
            v.update({"template_id": rnd.choice([None, 1, 2, 3, 99]), "on_sheet": rnd.random() < 0.5,
                      "is_dependent": rnd.random() < 0.2, "printable": rnd.random() < 0.9,
                      "scope_box_id": rnd.choice([None, 50, 51])})
        vs.append(v)
    ss = [{"id": 200 + i, "number": "A-%d" % i, "name": "S", "view_count": rnd.randint(0, 2),
           "is_placeholder": rnd.random() < 0.2} for i in range(rnd.randint(0, 5))]
    rec.call("audit", audit, vs, ss, rnd.choice([boxes, [], None]), rnd.choice([None, [], [52], [50, 51, 52]]),
             rnd.choice([None, [], ["FloorPlan"], ["Section", "ThreeD"]]))

rec.save()
