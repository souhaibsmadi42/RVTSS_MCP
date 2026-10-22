# -*- coding: utf-8 -*-
"""Parameter mapping presets for map_parameters (IFC export overrides, IFC common psets, COBie).

A preset is a list of mappings {from, to, categories?, allow_type?, verified, note?}.
`verified` says whether the TARGET parameter name was confirmed in Autodesk
documentation / Autodesk-hosted material while building RVTSS v2.1:

* IFC exporter overrides IfcName, IfcLongName, IfcObjectType, IfcDescription, IfcTag
  (Autodesk University handout on the Revit IFC exporter).
* IFC common property sets: the exporter fills a common pset property from a
  parameter with exactly the property's name and data type (e.g. FireRating for
  Pset_DoorCommon / Pset_WallCommon) when "Export IFC common property sets" is on.
* COBie Extension: COBie.Type.Manufacturer, COBie.Component.SerialNumber (instance,
  text) and COBie.Component.InstallationDate were confirmed; the other COBie.* names
  follow the same scheme but were NOT confirmed - check them against the shared
  parameter file your COBie Extension created before relying on them.

map_parameters skips mappings whose target parameter does not exist on an
element, so an unconfirmed name can never write to the wrong parameter.
Office presets: %APPDATA%/RVTSS/presets/<name>.json with {"description", "mappings"}.
"""

IFC_OVERRIDES = [
    {"from": "Mark", "to": "IfcTag", "verified": True},
    {"from": "Comments", "to": "IfcDescription", "verified": True},
    {"from": "Number", "to": "IfcName", "categories": ["Rooms"], "verified": True,
     "note": "IFC IfcSpace Name = room number by convention"},
    {"from": "Name", "to": "IfcLongName", "categories": ["Rooms"], "verified": True},
    {"from": "Type Mark", "to": "IfcObjectType", "allow_type": True, "verified": True},
]

IFC_COMMON_PSETS = [
    {"from": "Fire Rating", "to": "FireRating", "categories": ["Doors", "Walls", "Windows", "Floors"],
     "verified": True, "note": "Pset_*Common.FireRating (IfcLabel): text parameter named FireRating"},
    {"from": "Acoustic Rating", "to": "AcousticRating", "categories": ["Doors", "Walls", "Windows"],
     "verified": True, "note": "Pset_DoorCommon / Pset_WallCommon.AcousticRating"},
    {"from": "Function", "to": "IsExternal", "categories": ["Walls"], "verified": False,
     "note": "IsExternal is a boolean: the source must be a Yes/No parameter; map your own 'Is External' flag"},
]

COBIE_TYPE = [
    {"from": "Manufacturer", "to": "COBie.Type.Manufacturer", "allow_type": True, "verified": True},
    {"from": "Model", "to": "COBie.Type.ModelNumber", "allow_type": True, "verified": False},
    {"from": "Description", "to": "COBie.Type.Description", "allow_type": True, "verified": False},
    {"from": "Assembly Code", "to": "COBie.Type.Category", "allow_type": True, "verified": False},
]

COBIE_COMPONENT = [
    {"from": "Serial Number", "to": "COBie.Component.SerialNumber", "verified": True,
     "note": "instance text parameter; 'Serial Number' is your own source parameter"},
    {"from": "Installation Date", "to": "COBie.Component.InstallationDate", "verified": True},
    {"from": "Mark", "to": "COBie.Component.TagNumber", "verified": False},
    {"from": "Comments", "to": "COBie.Component.Description", "verified": False},
]

COBIE_SPACE = [
    {"from": "Number", "to": "COBie.Space.Name", "categories": ["Rooms"], "verified": False},
    {"from": "Name", "to": "COBie.Space.Description", "categories": ["Rooms"], "verified": False},
]

PRESETS = {
    "ifc_overrides": {"description": "Revit IFC exporter override parameters (IfcName/IfcLongName/IfcDescription/"
                                     "IfcObjectType/IfcTag)", "mappings": IFC_OVERRIDES},
    "ifc_common_psets": {"description": "Parameters named like IFC common pset properties (FireRating, ...)",
                         "mappings": IFC_COMMON_PSETS},
    "cobie_type": {"description": "COBie Type sheet fields from type parameters", "mappings": COBIE_TYPE},
    "cobie_component": {"description": "COBie Component sheet fields from instance parameters",
                        "mappings": COBIE_COMPONENT},
    "cobie_space": {"description": "COBie Space sheet fields from rooms", "mappings": COBIE_SPACE},
}


class PresetError(ValueError):
    pass


def get_preset(name, user_presets=None):
    """Mappings of a built-in or office preset (office presets win). Returns a new list."""
    pool = dict(PRESETS)
    pool.update(user_presets or {})
    if name not in pool:
        raise PresetError("Unknown preset '%s'. Available: %s" % (name, ", ".join(sorted(pool))))
    mappings = pool[name].get("mappings") or []
    for m in mappings:
        if not m.get("from") or not m.get("to"):
            raise PresetError("Preset '%s' has a mapping without from/to: %s" % (name, m))
    return [dict(m) for m in mappings]


def preset_categories(mappings):
    cats = []
    for m in mappings:
        for c in m.get("categories") or []:
            if c not in cats:
                cats.append(c)
    return cats


def applies(mapping, category_name):
    cats = mapping.get("categories")
    if not cats:
        return True
    return (category_name or "").lower() in [c.lower() for c in cats]


def describe():
    return dict((k, {"description": v["description"], "mappings": len(v["mappings"]),
                     "unverified_targets": [m["to"] for m in v["mappings"] if not m.get("verified")]})
                for k, v in PRESETS.items())
