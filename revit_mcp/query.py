# -*- coding: UTF-8 -*-
"""Element selection shared by find_elements, bulk updates, audits, exports and QC.

Query spec (all keys optional, combined with AND):
    element_ids      [int]           explicit ids (other filters still apply)
    selection        bool            current Revit selection (active document only)
    categories       [str]           'Doors', 'OST_Doors' or category id
    class_name       str             Revit API class, e.g. 'Wall', 'FamilyInstance'
    include_types    bool            return element types instead of instances
    view             id|name|active  only elements visible in that view
    level            id|name         elements associated with that level
    family, type     str             exact (case-insensitive) family / type name
    name_contains    str             substring of the element name
    text             str             all words must appear in category/family/type/name/mark
    param_filters    [{name, op, value, unit}]  see pure.filters.OPS
"""
from pyrevit import DB

from .compat import text_type, id_int
from .core import (RvtssError, resolve_category, find_level, find_view, get_elements,
                   to_id_list, element_brief)
from .params_util import find as find_param, raw_value
from .pure import filters as F
from .utils import normalize_string, get_element_name

QUERY_KEYS = ("element_ids", "selection", "categories", "class_name", "include_types", "view",
              "level", "family", "type", "name_contains", "text", "param_filters")


def query_spec(data, key="filter"):
    """Allow either a nested {"filter": {...}} or top-level query keys."""
    nested = data.get(key)
    if isinstance(nested, dict):
        return nested
    return dict((k, data[k]) for k in QUERY_KEYS if k in data)


def _api_class(name):
    cls = getattr(DB, name, None)
    if cls is None:
        try:
            cls = getattr(DB.Architecture, name, None) or getattr(DB.Mechanical, name, None) or \
                getattr(DB.Plumbing, name, None) or getattr(DB.Electrical, name, None) or \
                getattr(DB.Structure, name, None)
        except Exception:
            cls = None
    if cls is None:
        raise RvtssError("Unknown Revit API class '{}'".format(name),
                         hint="Examples: Wall, Floor, FamilyInstance, FamilySymbol, Level, Grid, View, "
                              "ViewSheet, Room (use categories for rooms), RevitLinkInstance, Group.")
    return cls


def selection_ids(ctx):
    if ctx.uidoc is None or ctx.uidoc.Document is None or not ctx.uidoc.Document.Equals(ctx.doc):
        raise RvtssError("Selection is only available for the active document", status=409)
    return list(ctx.uidoc.Selection.GetElementIds())


def collect(ctx, spec, max_scan=None):
    """Return the list of elements matching spec."""
    doc = ctx.doc
    for f in spec.get("param_filters") or []:
        try:
            F.validate_filter(f)
        except F.FilterError as e:
            raise RvtssError(str(e))
    include_types = bool(spec.get("include_types"))

    ids = list(spec.get("element_ids") or [])
    if spec.get("selection"):
        ids.extend(selection_ids(ctx))
        if not ids:
            return []
    if ids:
        elements = get_elements(doc, ids)
        native = False
        # explicit ids / selection: the collector filters below are applied here too
        cats = spec.get("categories") or []
        if isinstance(cats, (text_type, str)):
            cats = [cats]
        if cats:
            cat_ids = set(id_int(resolve_category(doc, c).Id) for c in cats)
            elements = [e for e in elements if e.Category is not None and id_int(e.Category.Id) in cat_ids]
        if spec.get("class_name"):
            cls = _api_class(spec["class_name"])
            elements = [e for e in elements if isinstance(e, cls)]
        if spec.get("level") is not None:
            lid = find_level(doc, spec["level"]).Id
            elements = [e for e in elements if getattr(e, "LevelId", None) is not None and e.LevelId == lid]
        view = spec.get("view")
        if view is not None and view != "":
            v = find_view(doc, view, uidoc=ctx.uidoc if view == "active" else None)
            visible = set(id_int(i) for i in DB.FilteredElementCollector(doc, v.Id).ToElementIds())
            elements = [e for e in elements if id_int(e) in visible]
    else:
        view = spec.get("view")
        if view is not None and view != "":
            v = find_view(doc, view, uidoc=ctx.uidoc if view == "active" else None)
            col = DB.FilteredElementCollector(doc, v.Id)
        else:
            col = DB.FilteredElementCollector(doc)
        col = col.WhereElementIsElementType() if include_types else col.WhereElementIsNotElementType()
        cats = spec.get("categories") or []
        if isinstance(cats, (text_type, str)):
            cats = [cats]
        if len(cats) == 1:
            col = col.OfCategoryId(resolve_category(doc, cats[0]).Id)
        elif len(cats) > 1:
            col = col.WherePasses(DB.ElementMulticategoryFilter(
                to_id_list([resolve_category(doc, c).Id for c in cats])))
        if spec.get("class_name"):
            col = col.OfClass(_api_class(spec["class_name"]))
        if spec.get("level") is not None and not include_types:
            col = col.WherePasses(DB.ElementLevelFilter(find_level(doc, spec["level"]).Id))
        elements = col
        native = True

    fam = (spec.get("family") or "").strip().lower() or None
    typ = (spec.get("type") or "").strip().lower() or None
    name_contains = (spec.get("name_contains") or "").strip().lower() or None
    text = spec.get("text")
    pfilters = spec.get("param_filters") or []
    need_cat = native and not spec.get("categories") and not spec.get("class_name")

    out = []
    scanned = 0
    for e in elements:
        scanned += 1
        if max_scan and scanned > max_scan:
            ctx.warn("Stopped after scanning {} elements; narrow the query.".format(max_scan))
            break
        if need_cat and e.Category is None:
            continue  # skip internal, uncategorised elements in broad queries
        if fam or typ or text:
            b = element_brief(doc, e)
            if fam and (b.get("family") or "").lower() != fam:
                continue
            if typ and (b.get("type") or "").lower() != typ and not (
                    include_types and (b.get("name") or "").lower() == typ):
                continue
            if text:
                mark = None
                try:
                    mp = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
                    mark = mp.AsString() if mp else None
                except Exception:
                    pass
                if not F.text_match(text, [b.get("category"), b.get("family"), b.get("type"),
                                           b.get("name"), mark]):
                    continue
        if name_contains:
            n = normalize_string(get_element_name(e) or "").lower()
            if name_contains not in n:
                continue
        if pfilters and not _passes_params(doc, e, pfilters):
            continue
        out.append(e)
    return out


def _passes_params(doc, e, pfilters):
    for f in pfilters:
        p, _owner = find_param(doc, e, f["name"], allow_type=True)
        exists = p is not None
        raw, display = None, None
        if exists:
            try:
                raw = raw_value(p, f.get("unit") or "mm")
            except Exception:
                raw = None
            try:
                display = p.AsValueString()
            except Exception:
                display = None
            if raw is None and display is None and p.StorageType == DB.StorageType.String:
                raw = ""
        if not F.match(f.get("op", "eq"), f.get("value"), raw, display, exists,
                       bool(f.get("case_sensitive"))):
            return False
    return True


def category_counts(elements):
    counts = {}
    for e in elements:
        c = e.Category
        n = normalize_string(c.Name) if c else "(none)"
        counts[n] = counts.get(n, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
