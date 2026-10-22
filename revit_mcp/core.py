# -*- coding: UTF-8 -*-
"""Shared infrastructure for RVTSS route modules.

* ``handle()``      - parse the request, resolve the target document, run the
                      implementation, convert errors into structured responses
                      and log timing. pyRevit Routes inspects handler argument
                      names (doc/uidoc/request) to decide whether to run in Revit
                      API context, so every route keeps an explicit signature and
                      delegates here.
* ``Ctx``           - typed accessors for request fields.
* ``run_transaction`` - Transaction with failure collection; ``dry_run`` wraps
                      it in a TransactionGroup that is rolled back, so Revit's
                      own commit-time validation still runs but nothing is kept.
* ``batch``         - per-item SubTransactions for non-atomic batches.
"""
import json
import os
import time
import difflib
import logging
import traceback

from pyrevit import routes, DB

from .compat import make_id, id_int, text_type, bic_from_category, is_valid_id
from .utils import normalize_string, get_element_name

logger = logging.getLogger(__name__)

try:
    basestring  # noqa: F821
except NameError:
    basestring = str

# Operations touching more elements than this need confirm=true.
CONFIRM_THRESHOLD = int(os.environ.get("RVTSS_CONFIRM_THRESHOLD", "100"))
MAX_LIMIT = 1000


def rvtss_home():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "RVTSS")
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def rvtss_subdir(name):
    path = os.path.join(rvtss_home(), name)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def load_config():
    """Optional %APPDATA%/RVTSS/config.json."""
    path = os.path.join(rvtss_home(), "config.json")
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception as e:
            logger.warning("Invalid RVTSS config.json: {}".format(e))
    return {}


def _audit_log(method, ok, duration, detail=""):
    try:
        logdir = rvtss_subdir("logs")
        fname = os.path.join(logdir, "rvtss-{}.log".format(time.strftime("%Y%m%d")))
        with open(fname, "a") as fh:
            fh.write("{}\t{}\t{}\t{:.0f}ms\t{}\n".format(
                time.strftime("%H:%M:%S"), method, "ok" if ok else "ERROR", duration * 1000.0,
                (detail or "").replace("\n", " ")[:300]))
    except Exception:
        pass


# ------------------------------------------------------------------------ errors
class RvtssError(Exception):
    """An expected, user-facing failure with an HTTP status and recovery hint."""

    def __init__(self, message, status=400, hint=None, **extra):
        Exception.__init__(self, message)
        self.message = message
        self.status = status
        self.hint = hint
        self.extra = extra


def not_found(what, name, choices=None, hint=None):
    extra = {}
    if choices is not None:
        choices = [c for c in choices if c]
        close = difflib.get_close_matches(text_type(name), choices, n=5, cutoff=0.5)
        extra["did_you_mean"] = close
        extra["available_sample"] = sorted(choices)[:25]
    return RvtssError("{} not found: {}".format(what, name), status=404, hint=hint, **extra)


# --------------------------------------------------------------------- responses
try:
    INTEGER_TYPES = (int, long)  # noqa: F821  IronPython 2: Int64 arrives as long
except NameError:
    INTEGER_TYPES = (int,)


def to_text(value):
    """Unicode text without stripping (normalize_string strips and renames None)."""
    if value is None:
        return None
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes) and not isinstance(value, text_type):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return text_type(value)


def _clean(value):
    """Make a value JSON-serialisable (no .NET objects, finite floats)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, INTEGER_TYPES):
        return int(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, basestring):
        return to_text(value)
    if isinstance(value, dict):
        return dict((to_text(k), _clean(v)) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return [_clean(v) for v in value]
    if isinstance(value, DB.ElementId):
        return id_int(value)
    return to_text(value)


def ok(data=None, **kwargs):
    payload = {"status": "success"}
    if data:
        payload.update(data)
    payload.update(kwargs)
    return routes.make_response(data=_clean(payload))


def respond(payload, status=200):
    return routes.make_response(data=_clean(payload), status=status)


def error_response(message, status=400, hint=None, **extra):
    payload = {"status": "error", "error": message}
    if hint:
        payload["hint"] = hint
    payload.update(extra)
    return routes.make_response(data=_clean(payload), status=status)


# ----------------------------------------------------------------------- request
class Ctx(object):
    def __init__(self, doc, uidoc, data):
        self.active_doc = doc
        self.uidoc = uidoc
        self.data = data or {}
        self.doc = resolve_document(doc, self.data.get("document"))
        self.warnings = []

    @property
    def app(self):
        return self.doc.Application

    def get(self, key, default=None):
        v = self.data.get(key, default)
        return default if v is None else v

    def require(self, key, what=None):
        v = self.data.get(key)
        if v is None or (isinstance(v, basestring) and not v.strip()) or v == []:
            raise RvtssError("Missing required field '{}'{}".format(key, " ({})".format(what) if what else ""))
        return v

    def bool(self, key, default=False):
        v = self.data.get(key, default)
        if isinstance(v, basestring):
            return v.strip().lower() in ("1", "true", "yes", "y")
        return bool(v)

    def int(self, key, default=None, minimum=None, maximum=None):
        v = self.data.get(key, default)
        if v is None:
            return None
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise RvtssError("Field '{}' must be an integer".format(key))
        if minimum is not None and v < minimum:
            v = minimum
        if maximum is not None and v > maximum:
            v = maximum
        return v

    def float(self, key, default=None):
        v = self.data.get(key, default)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise RvtssError("Field '{}' must be a number".format(key))

    def list(self, key, default=None):
        v = self.data.get(key, default)
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            return list(v)
        return [v]

    @property
    def unit(self):
        return self.data.get("unit") or "mm"

    @property
    def dry_run(self):
        return self.bool("dry_run", False)

    @property
    def confirmed(self):
        return self.bool("confirm", False)

    def warn(self, message):
        self.warnings.append(message)


def parse_request(request):
    if request is None:
        return {}
    data = getattr(request, "data", None)
    if data is None:
        return {}
    if isinstance(data, basestring):
        if not data.strip():
            return {}
        try:
            data = json.loads(data)
        except ValueError as e:
            raise RvtssError("Invalid JSON body: {}".format(e))
    if not isinstance(data, dict):
        raise RvtssError("Request body must be a JSON object")
    return data


def handle(doc, request, impl, uidoc=None, name=None, needs_doc=True):
    """Run ``impl(ctx)`` and turn its result / errors into a Routes response."""
    start = time.time()
    method = name or getattr(impl, "__name__", "rvtss")
    try:
        data = parse_request(request)
        if needs_doc and doc is None and not data.get("document"):
            raise RvtssError("No active Revit document", status=503,
                             hint="Open a project or family in Revit (open_document) and retry.")
        ctx = Ctx(doc, uidoc, data)
        result = impl(ctx)
        if result is None:
            result = {}
        if ctx.warnings:
            result.setdefault("warnings", []).extend(ctx.warnings)
        result.setdefault("status", "success")
        _audit_log(method, True, time.time() - start, result.get("status"))
        return respond(result)
    except RvtssError as e:
        _audit_log(method, False, time.time() - start, e.message)
        return error_response(e.message, status=e.status, hint=e.hint, **e.extra)
    except Exception as e:
        tb = traceback.format_exc()
        inner = getattr(e, "InnerException", None)
        logger.error("RVTSS {} failed: {}\n{}".format(method, e, tb))
        _audit_log(method, False, time.time() - start, text_type(e))
        return error_response(
            "{}: {}".format(type(e).__name__, normalize_string(text_type(e))), status=500,
            hint=revit_error_hint(e), traceback=tb[-3000:],
            inner_exception=text_type(inner) if inner else None)


def revit_error_hint(e):
    msg = text_type(e)
    name = type(e).__name__
    if "ModificationOutsideTransaction" in name or "outside of a transaction" in msg:
        return "This change needs a transaction; RVTSS tools open one automatically."
    if "ModificationForbidden" in name or "read-only" in msg.lower():
        return "The document is read-only or in a state that forbids modification (linked, being edited, or modal UI open)."
    if "ArgumentException" in name or "ArgumentOutOfRange" in name:
        return "Revit rejected one of the arguments. Re-check ids, names and units (lengths default to mm)."
    if "InvalidOperation" in name:
        return "Revit refused the operation in the current state. Inspect the element/document state and retry."
    return None


# --------------------------------------------------------------------- documents
def all_documents(doc):
    app = doc.Application if doc is not None else _host_app()
    return [d for d in app.Documents]


def _host_app():
    from pyrevit import HOST_APP

    return HOST_APP.app


def describe_document(d):
    return {
        "title": normalize_string(d.Title),
        "path": d.PathName or None,
        "is_family": d.IsFamilyDocument,
        "is_linked": d.IsLinked,
        "is_modified": d.IsModified,
        "is_workshared": d.IsWorkshared,
        "is_read_only": d.IsReadOnly,
        "family_category": (d.OwnerFamily.FamilyCategory.Name
                            if d.IsFamilyDocument and d.OwnerFamily.FamilyCategory else None),
    }


def resolve_document(active_doc, target):
    """Find an open document by title (with/without extension) or full path."""
    if not target or (isinstance(target, basestring) and target.lower() == "active"):
        if active_doc is None:
            raise RvtssError("No active Revit document", status=503)
        return active_doc
    t = text_type(target).strip().lower()
    docs = [d for d in all_documents(active_doc) if not d.IsLinked]
    for d in docs:
        title = (d.Title or "").lower()
        path = (d.PathName or "").lower()
        if t in (title, path) or t == os.path.splitext(title)[0] or \
                (path and t == os.path.splitext(os.path.basename(path))[0]):
            return d
    raise not_found("Open document", target, [d.Title for d in docs],
                    hint="Use get_revit_status to list open documents (family documents opened by "
                         "family_open/family_create stay open in the background).")


def require_project(doc):
    if doc.IsFamilyDocument:
        raise RvtssError("This operation needs a project document but '{}' is a family document".format(doc.Title),
                         hint="Pass document='<project title>' or activate the project.")


def require_family(doc):
    if not doc.IsFamilyDocument:
        raise RvtssError("'{}' is not a family document".format(doc.Title), status=400,
                         hint="Open the family first with family_open (path or loaded family name) "
                              "or family_create, then pass its title as 'document'.")
    return doc.FamilyManager


def check_modifiable(doc):
    if doc.IsReadOnly:
        raise RvtssError("Document '{}' is read-only".format(doc.Title), status=409)
    if doc.IsLinked:
        raise RvtssError("Linked documents cannot be modified", status=409,
                         hint="Open the linked file itself to edit it.")


# ----------------------------------------------------------------------- lookups
def get_element(doc, element_id, what="Element"):
    try:
        e = doc.GetElement(make_id(element_id))
    except Exception:
        e = None
    if e is None:
        raise RvtssError("{} id {} does not exist in '{}'".format(what, element_id, doc.Title), status=404,
                         hint="Ids are document specific; use find_elements to get current ids.")
    return e


def get_elements(doc, ids, what="Element"):
    out = []
    missing = []
    for i in ids:
        try:
            e = doc.GetElement(make_id(i))
        except Exception:
            e = None
        if e is None:
            missing.append(i)
        else:
            out.append(e)
    if missing:
        raise RvtssError("{} ids not found: {}".format(what, missing[:20]), status=404,
                         hint="Ids are document specific; use find_elements to get current ids.",
                         missing_ids=missing)
    return out


_CATEGORY_CACHE = {}


def _category_map(doc):
    key = doc.Title
    cached = _CATEGORY_CACHE.get(key)
    if cached is not None:
        return cached
    m = {}
    for c in doc.Settings.Categories:
        m[normalize_string(c.Name).lower()] = c
    _CATEGORY_CACHE[key] = m
    return m


def resolve_category(doc, name):
    """Category by display name ('Doors'), BuiltInCategory ('OST_Doors') or id."""
    if isinstance(name, DB.Category):
        return name
    if isinstance(name, int) or (isinstance(name, basestring) and name.lstrip("-").isdigit()):
        try:
            cat = DB.Category.GetCategory(doc, make_id(int(name)))
            if cat:
                return cat
        except Exception:
            pass
    s = text_type(name).strip()
    candidates = [s if s.upper().startswith("OST_") else None, "OST_" + s.replace(" ", "")]
    for cand in candidates:
        if not cand:
            continue
        bic = getattr(DB.BuiltInCategory, cand, None)
        if bic is not None:
            try:
                cat = DB.Category.GetCategory(doc, bic)
                if cat:
                    return cat
            except Exception:
                pass
    m = _category_map(doc)
    low = s.lower()
    for variant in (low, low + "s", low.rstrip("s"), low + "es"):
        if variant in m:
            return m[variant]
    _CATEGORY_CACHE.pop(doc.Title, None)
    raise not_found("Category", name, [c.Name for c in m.values()],
                    hint="Use the display name (e.g. 'Doors', 'Generic Models') or 'OST_Doors'.")


def category_info(cat):
    if cat is None:
        return None
    return {"name": normalize_string(cat.Name), "id": id_int(cat.Id), "builtin": bic_from_category(cat)}


def find_level(doc, level):
    if level is None:
        return None
    if isinstance(level, int) or (isinstance(level, basestring) and level.isdigit()):
        e = doc.GetElement(make_id(int(level)))
        if isinstance(e, DB.Level):
            return e
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    for lv in levels:
        if normalize_string(lv.Name).lower() == text_type(level).strip().lower():
            return lv
    raise not_found("Level", level, [lv.Name for lv in levels])


def find_view(doc, view, default_active=True, uidoc=None):
    if view in (None, "", "active"):
        if not default_active:
            return None
        v = doc.ActiveView if uidoc is None else uidoc.ActiveView
        if v is None:
            raise RvtssError("No active view", status=404)
        return v
    if isinstance(view, int) or (isinstance(view, basestring) and view.isdigit()):
        e = doc.GetElement(make_id(int(view)))
        if isinstance(e, DB.View):
            return e
    views = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if not v.IsTemplate]
    matches = [v for v in views if normalize_string(v.Name).lower() == text_type(view).strip().lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RvtssError("View name '{}' is ambiguous ({} views)".format(view, len(matches)), status=409,
                         hint="Pass the view id instead.",
                         candidates=[{"id": id_int(v), "type": str(v.ViewType)} for v in matches])
    raise not_found("View", view, [v.Name for v in views])


def find_type(doc, family=None, type_name=None, type_id=None, category=None, of_class=None):
    """Find an ElementType by id or family/type name (FamilySymbol and system types)."""
    if type_id is not None:
        e = get_element(doc, type_id, "Type")
        if not isinstance(e, DB.ElementType):
            raise RvtssError("Element {} is not a type".format(type_id))
        return e
    col = DB.FilteredElementCollector(doc).WhereElementIsElementType()
    if of_class is not None:
        col = col.OfClass(of_class)
    if category is not None:
        col = col.OfCategoryId(resolve_category(doc, category).Id)
    fam_l = text_type(family).strip().lower() if family else None
    typ_l = text_type(type_name).strip().lower() if type_name else None
    seen = []
    for t in col:
        fam = normalize_string(getattr(t, "FamilyName", "") or "")
        name = normalize_string(get_element_name(t))
        seen.append(u"{} : {}".format(fam, name))
        if fam_l and fam.lower() != fam_l:
            continue
        if typ_l and name.lower() != typ_l:
            continue
        if fam_l or typ_l:
            return t
    raise not_found("Type", u"{} : {}".format(family or "*", type_name or "*"), seen,
                    hint="Use list_families / find_elements(include_types=true) to see available types.")


# ------------------------------------------------------------------- element info
def element_brief(doc, e):
    info = {"id": id_int(e), "name": normalize_string(get_element_name(e) or "")}
    cat = e.Category
    info["category"] = normalize_string(cat.Name) if cat else None
    try:
        tid = e.GetTypeId()
        if is_valid_id(tid):
            t = doc.GetElement(tid)
            if t is not None:
                info["family"] = normalize_string(getattr(t, "FamilyName", "") or "")
                info["type"] = normalize_string(get_element_name(t))
                info["type_id"] = id_int(tid)
        elif isinstance(e, DB.ElementType):
            info["family"] = normalize_string(getattr(e, "FamilyName", "") or "")
    except Exception:
        pass
    return info


def element_level(doc, e):
    try:
        lid = e.LevelId
        if is_valid_id(lid):
            lv = doc.GetElement(lid)
            return normalize_string(lv.Name) if lv else None
    except Exception:
        pass
    for bip in ("FAMILY_LEVEL_PARAM", "INSTANCE_REFERENCE_LEVEL_PARAM", "WALL_BASE_CONSTRAINT",
                "SCHEDULE_LEVEL_PARAM", "LEVEL_PARAM"):
        try:
            p = e.get_Parameter(getattr(DB.BuiltInParameter, bip))
            if p and is_valid_id(p.AsElementId()):
                lv = doc.GetElement(p.AsElementId())
                if lv:
                    return normalize_string(lv.Name)
        except Exception:
            continue
    return None


def xyz_list(p, unit="mm", nd=1):
    from .pure.units import from_internal

    return [from_internal(p.X, unit, nd), from_internal(p.Y, unit, nd), from_internal(p.Z, unit, nd)]


def element_location(e, unit="mm"):
    from .pure.units import from_internal

    loc = e.Location
    if isinstance(loc, DB.LocationPoint):
        out = {"type": "point", "point": xyz_list(loc.Point, unit)}
        try:
            out["rotation_deg"] = round(loc.Rotation * 180.0 / 3.141592653589793, 3)
        except Exception:
            pass
        return out
    if isinstance(loc, DB.LocationCurve):
        c = loc.Curve
        return {"type": "curve", "start": xyz_list(c.GetEndPoint(0), unit),
                "end": xyz_list(c.GetEndPoint(1), unit), "length": from_internal(c.Length, unit, 1)}
    return None


def element_point(e):
    """Representative XYZ for an element (location point, curve midpoint or bbox centre)."""
    loc = e.Location
    if isinstance(loc, DB.LocationPoint):
        return loc.Point
    if isinstance(loc, DB.LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    bb = e.get_BoundingBox(None)
    if bb:
        return (bb.Min + bb.Max) * 0.5
    return None


def element_bbox(e, unit="mm", view=None):
    bb = e.get_BoundingBox(view)
    if bb is None:
        return None
    return {"min": xyz_list(bb.Min, unit), "max": xyz_list(bb.Max, unit)}


def to_id_list(ids):
    from System.Collections.Generic import List

    lst = List[DB.ElementId]()
    for i in ids:
        lst.Add(i if isinstance(i, DB.ElementId) else make_id(i))
    return lst


# ------------------------------------------------------------------ transactions
class FailureCollector(DB.IFailuresPreprocessor):
    """Collects warnings/errors raised while committing.

    Warnings are recorded and dismissed so they do not block the transaction or
    pop up dialogs; errors make the transaction roll back and are reported.
    """

    def __init__(self):
        self.messages = []
        self.has_errors = False

    def PreprocessFailures(self, failures_accessor):
        for f in failures_accessor.GetFailureMessages():
            sev = f.GetSeverity()
            try:
                ids = [id_int(i) for i in f.GetFailingElementIds()]
            except Exception:
                ids = []
            entry = {"severity": str(sev), "message": normalize_string(f.GetDescriptionText()),
                     "element_ids": ids[:20]}
            self.messages.append(entry)
            if sev == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(f)
            else:
                self.has_errors = True
        if self.has_errors:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _start_tx(doc, name):
    t = DB.Transaction(doc, name)
    collector = FailureCollector()
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(collector)
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)
    t.Start()
    return t, collector


def run_transaction(doc, name, func, dry_run=False):
    """Run func() inside a transaction. Returns (result, failure_messages).

    dry_run: commit inside a TransactionGroup and roll the group back, so the
    preview reflects Revit's own validation without keeping any change.
    If a transaction is already open on doc, func runs inside it.
    """
    check_modifiable(doc)
    if doc.IsModifiable:
        return func(), []
    name = "RVTSS: " + name
    group = None
    if dry_run:
        group = DB.TransactionGroup(doc, name + " (dry run)")
        group.Start()
    t = None
    try:
        t, collector = _start_tx(doc, name)
        result = func()
        status = t.Commit()
        if status != DB.TransactionStatus.Committed:
            errors = [m["message"] for m in collector.messages if m["severity"] != "Warning"]
            raise RvtssError("Revit rejected the change and rolled it back: {}".format(
                "; ".join(errors) or str(status)), status=409, failures=collector.messages,
                hint="Nothing was changed. Adjust the request to avoid the reported errors.")
        return result, collector.messages
    except Exception:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    finally:
        if group is not None and group.HasStarted() and not group.HasEnded():
            group.RollBack()


def batch(doc, items, func, atomic=True):
    """Apply func(item) to each item inside an open transaction.

    atomic=True: first failure aborts (caller's transaction rolls back).
    atomic=False: each item runs in a SubTransaction; failures are recorded
    and rolled back individually while the rest continue.
    Returns list of {"index", "ok", ...result | "error"}.
    """
    results = []
    for i, item in enumerate(items):
        if atomic:
            try:
                r = func(item) or {}
            except RvtssError as e:
                raise RvtssError("Item {} failed: {}".format(i, e.message), status=e.status,
                                 hint="Batch is atomic: nothing was changed. Fix the item or pass atomic=false.",
                                 failed_index=i, failed_item=item)
            except Exception as e:
                raise RvtssError("Item {} failed: {}".format(i, normalize_string(text_type(e))), status=400,
                                 hint="Batch is atomic: nothing was changed. Fix the item or pass atomic=false.",
                                 failed_index=i, failed_item=item)
            r.update({"index": i, "ok": True})
            results.append(r)
        else:
            st = DB.SubTransaction(doc)
            st.Start()
            try:
                r = func(item) or {}
                st.Commit()
                r.update({"index": i, "ok": True})
            except Exception as e:
                if st.HasStarted() and not st.HasEnded():
                    st.RollBack()
                msg = e.message if isinstance(e, RvtssError) else normalize_string(text_type(e))
                r = {"index": i, "ok": False, "error": msg}
            results.append(r)
    return results


def commit_result(result, failures, dry_run, extra=None):
    """Standard envelope for modifying operations."""
    out = {"status": "dry_run" if dry_run else "success", "committed": not dry_run}
    if dry_run:
        out["message"] = "Dry run: Revit validated the change and it was rolled back. Nothing was modified."
    if failures:
        out["revit_warnings"] = failures
    if result:
        out.update(result)
    if extra:
        out.update(extra)
    return out


def confirm_gate(ctx, count, action):
    """Big/destructive operations need confirm=true; otherwise force a dry run.

    Returns True when the operation must run as a preview.
    """
    if ctx.confirmed or ctx.dry_run:
        return ctx.dry_run
    if count > CONFIRM_THRESHOLD:
        ctx.warn("{} affects {} elements (> {}). Showing a preview; re-run with confirm=true to apply.".format(
            action, count, CONFIRM_THRESHOLD))
        return True
    return False


def preview_status(out, forced):
    if forced:
        out["status"] = "preview"
        out["requires_confirmation"] = True
        out["message"] = "Preview only - nothing was modified. Re-run with confirm=true to apply."
    return out
