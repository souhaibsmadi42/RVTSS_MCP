# -*- coding: utf-8 -*-
"""Family template (.rft) discovery and matching.

Template file names differ between Revit versions and content packs
("Metric Door.rft", "M_Door.rft", "Door.rft"...), so matching is done on
normalised keywords rather than exact names.
"""
import os
import re

# kind -> (keywords that must all appear, keywords that must not appear)
TEMPLATE_KINDS = {
    "generic_model": (["generic", "model"], ["face", "wall", "ceiling", "floor", "roof", "line", "pattern", "adaptive", "two level", "annotation"]),
    "generic_model_face_based": (["generic", "model", "face"], ["adaptive"]),
    "generic_model_wall_based": (["generic", "model", "wall"], ["adaptive"]),
    "generic_model_floor_based": (["generic", "model", "floor"], []),
    "generic_model_ceiling_based": (["generic", "model", "ceiling"], []),
    "generic_model_line_based": (["generic", "model", "line"], []),
    "generic_model_adaptive": (["generic", "model", "adaptive"], []),
    "door": (["door"], ["tag", "curtain", "panel", "elevation", "garage"]),
    "door_curtain_wall": (["door", "curtain"], ["tag"]),
    "window": (["window"], ["tag", "curtain", "elevation", "fixed"]),
    "window_curtain_wall": (["window", "curtain"], ["tag"]),
    "furniture": (["furniture"], ["system", "tag"]),
    "furniture_system": (["furniture", "system"], ["tag"]),
    "casework": (["casework"], ["tag", "wall based"]),
    "casework_wall_based": (["casework", "wall"], ["tag"]),
    "plumbing_fixture": (["plumbing", "fixture"], ["tag", "wall", "face"]),
    "lighting_fixture": (["lighting", "fixture"], ["tag", "ceiling", "wall", "line", "face"]),
    "lighting_fixture_ceiling_based": (["lighting", "fixture", "ceiling"], ["tag"]),
    "mechanical_equipment": (["mechanical", "equipment"], ["tag", "wall", "face"]),
    "electrical_equipment": (["electrical", "equipment"], ["tag", "wall", "face"]),
    "electrical_fixture": (["electrical", "fixture"], ["tag", "wall", "face"]),
    "specialty_equipment": (["specialty", "equipment"], ["tag", "wall"]),
    "column": (["column"], ["structural", "tag", "curtain", "mullion"]),
    "structural_column": (["structural", "column"], ["tag"]),
    "structural_framing": (["structural", "framing", "beam"], ["tag", "complex"]),
    "structural_foundation": (["structural", "foundation"], ["tag"]),
    "structural_stiffener": (["structural", "stiffener"], ["tag"]),
    "structural_truss": (["structural", "truss"], ["tag"]),
    "entourage": (["entourage"], []),
    "planting": (["planting"], []),
    "site": (["site"], []),
    "parking": (["parking"], []),
    "profile": (["profile"], ["rail", "hosted", "mullion", "reveal", "stair", "door", "gutter", "fascia", "slab", "wall sweep"]),
    "profile_mullion": (["profile", "mullion"], []),
    "profile_rail": (["profile", "rail"], []),
    "profile_reveal": (["profile", "reveal"], []),
    "profile_hosted": (["profile", "hosted"], []),
    "detail_item": (["detail", "item"], ["line"]),
    "detail_item_line_based": (["detail", "item", "line"], []),
    "generic_annotation": (["generic", "annotation"], []),
    "door_tag": (["door", "tag"], []),
    "window_tag": (["window", "tag"], []),
    "room_tag": (["room", "tag"], []),
    "multi_category_tag": (["multi", "category", "tag"], []),
    "title_block": (["titleblock"], []),
    "rebar_shape": (["rebar", "shape"], []),
    "mass": (["mass"], ["adaptive"]),
    "railing_baluster": (["baluster"], ["panel", "post"]),
    "ceiling_based_generic": (["generic", "model", "ceiling"], []),
}

KIND_CATEGORY = {
    "generic_model": "OST_GenericModel",
    "door": "OST_Doors", "door_curtain_wall": "OST_Doors",
    "window": "OST_Windows", "window_curtain_wall": "OST_Windows",
    "furniture": "OST_Furniture", "furniture_system": "OST_FurnitureSystems",
    "casework": "OST_Casework", "casework_wall_based": "OST_Casework",
    "plumbing_fixture": "OST_PlumbingFixtures",
    "lighting_fixture": "OST_LightingFixtures", "lighting_fixture_ceiling_based": "OST_LightingFixtures",
    "mechanical_equipment": "OST_MechanicalEquipment",
    "electrical_equipment": "OST_ElectricalEquipment",
    "electrical_fixture": "OST_ElectricalFixtures",
    "specialty_equipment": "OST_SpecialityEquipment",
    "column": "OST_Columns", "structural_column": "OST_StructuralColumns",
    "structural_framing": "OST_StructuralFraming",
    "structural_foundation": "OST_StructuralFoundation",
    "entourage": "OST_Entourage", "planting": "OST_Planting", "site": "OST_Site",
    "parking": "OST_Parking", "detail_item": "OST_DetailComponents",
    "title_block": "OST_TitleBlocks", "mass": "OST_Mass",
}

UNIT_SYSTEM_HINTS = {
    "metric": ["metric", "m_"],
    "imperial": ["imperial", "us "],
}


def _parts(path):
    """Split on both separators: Windows paths must also work when tested on Linux."""
    return [x for x in re.split(r"[\\/]", path or "") if x]


def _normalise(name):
    parts = _parts(name)
    base = os.path.splitext(parts[-1] if parts else "")[0].lower()
    base = base.replace("_", " ").replace("-", " ")
    base = re.sub(r"\s+", " ", base)
    return " %s " % base


def _contains_word(text, keyword):
    # titleblock may be written as "title block"
    kw = keyword.lower()
    if kw == "titleblock":
        return "titleblock" in text.replace(" ", "")
    return kw in text


def score(path, kind, unit_system=None):
    """Return a match score (>0 means usable) for a template path."""
    if kind not in TEMPLATE_KINDS:
        return 0
    must, must_not = TEMPLATE_KINDS[kind]
    text = _normalise(path)
    parts = _parts(path)
    # Revit ships title blocks as "Titleblocks\A1 metric.rft": the folder name counts for the required words
    folder = _normalise(parts[-2]) if len(parts) > 1 else " "
    if not all(_contains_word(text, k) or _contains_word(folder, k) for k in must):
        return 0
    if any(_contains_word(text, k) for k in must_not):
        return 0
    s = 10
    # prefer shorter, more canonical names ("Metric Door.rft" over "Metric Door - Curtain...")
    s -= min(len(text.split()), 8) * 0.5
    if unit_system:
        hints = UNIT_SYSTEM_HINTS.get(unit_system, [])
        other = [h for us, hs in UNIT_SYSTEM_HINTS.items() if us != unit_system for h in hs]
        low = (parts[-1] if parts else "").lower()
        if any(h in low for h in hints):
            s += 3
        elif any(h in low for h in other):
            s -= 3
    return s


def match(paths, kind, unit_system=None):
    """Return candidate templates for a kind, best first."""
    scored = [(score(p, kind, unit_system), p) for p in paths]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [p for _, p in scored]


def find_template_files(dirs, max_files=5000):
    found = []
    seen = set()
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".rft"):
                    full = os.path.join(root, f)
                    key = full.lower()
                    if key not in seen:
                        seen.add(key)
                        found.append(full)
                        if len(found) >= max_files:
                            return found
    return found
