# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/mapping_presets.py -> mapping_presets.json.
Run: uv run --project . python host/tests/vectors/gen_mapping_presets.py"""
from _lane_c import Recorder
from revit_mcp.pure import mapping_presets as MP

rec = Recorder("mapping_presets")
rec.extra["constants"] = {"IFC_OVERRIDES": MP.IFC_OVERRIDES, "IFC_COMMON_PSETS": MP.IFC_COMMON_PSETS,
                          "COBIE_TYPE": MP.COBIE_TYPE, "COBIE_COMPONENT": MP.COBIE_COMPONENT,
                          "COBIE_SPACE": MP.COBIE_SPACE, "PRESETS": MP.PRESETS}


def get_preset(name, user_presets="<default>"):
    return MP.get_preset(name) if user_presets == "<default>" else MP.get_preset(name, user_presets)


office = {"office_ifc": {"description": "x", "mappings": [{"from": "A", "to": "B", "categories": ["Doors"]}]}}
override = {"ifc_overrides": {"description": "office wins", "mappings": [{"from": "Mark", "to": "OfficeTag"}]},
            "empty": {"description": "no mappings"}, "none": {"mappings": None}, "nolist": {"mappings": []},
            "Zeta": {"mappings": [{"from": "a", "to": "b", "extra": [1, 2, {"k": None}]}]}}

for name in sorted(MP.PRESETS):
    rec.call("get_preset", get_preset, name)
    rec.call("get_preset", get_preset, name, None)
    rec.call("get_preset", get_preset, name, {})
    rec.call("get_preset", get_preset, name, office)
    rec.call("get_preset", get_preset, name, override)
for name in ("office_ifc", "nope", "", "IFC_OVERRIDES", "empty", "none", "nolist", "Zeta", None):
    rec.call("get_preset", get_preset, name)
    rec.call("get_preset", get_preset, name, office)
    rec.call("get_preset", get_preset, name, override)
# mappings without from / to: the message shows the mapping
for bad in ([{"from": "A"}], [{"to": "B"}], [{"from": "", "to": "B"}], [{"from": "A", "to": None}], [{}],
            [{"from": "A", "to": "B"}, {"from": "it's", "to": "", "categories": ["Doors", "Walls"], "verified": True,
                                         "allow_type": False, "n": 1, "f": 1.5, "none": None, "q": 'say "hi"',
                                         "both": "it's \"x\"", "nested": {"a": [1, "two"]}, "back\\slash": "tab\there"}],
            [{"from": 0, "to": "B"}], [{"from": "A", "to": "B"}]):
    rec.call("get_preset", get_preset, "bad", {"bad": {"mappings": bad}})
rec.call("get_preset", get_preset, "bad", {"bad": {"mappings": [{"from": "A", "to": "B"}, "text"]}})  # AttributeError
rec.call("get_preset", get_preset, "bad", {"bad": "text"})  # AttributeError

for ms in (MP.COBIE_SPACE, MP.COBIE_TYPE, MP.IFC_COMMON_PSETS, MP.IFC_OVERRIDES, [],
           [{"categories": ["B", "A", "B"]}, {"categories": None}, {"categories": []}, {}, {"categories": ["a", "A", 1, 1.0, "C"]}]):
    rec.call("preset_categories", MP.preset_categories, ms)

m = {"from": "Number", "to": "IfcName", "categories": ["Rooms", "Wall Sweeps"]}
for mapping in (m, {"from": "a", "to": "b"}, {"categories": []}, {"categories": None}, {"categories": ["ÉTAGE"]}):
    for cat in ("Rooms", "rooms", "ROOMS", "Doors", None, "", "wall sweeps", " Rooms", "étage"):
        rec.call("applies", MP.applies, mapping, cat)

rec.call("describe", MP.describe)

rec.save()
