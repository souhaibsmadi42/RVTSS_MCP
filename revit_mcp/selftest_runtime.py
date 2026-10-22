# -*- coding: UTF-8 -*-
"""In-Revit runner for the RVTSS self-test (used by the Run Self-Test button).

HTTP cannot be used from a pushbutton: the button runs on Revit's UI thread and
pyRevit Routes executes API requests through an ExternalEvent on that same
thread, so a request to localhost:48884 from here would wait for itself. The
route handlers are therefore registered again on a recorder and called
directly, with the same doc/uidoc/request arguments pyRevit would inject.
"""
import os
import io
import shutil
import tempfile
import inspect

from .registry import register_all
from .pure import selftest


class RecorderAPI(object):
    def __init__(self):
        self.routes = []

    def route(self, path, methods=None):
        def deco(func):
            self.routes.append({"path": path, "methods": methods or ["GET"], "func": func})
            return func
        return deco


class _Request(object):
    def __init__(self, data, params=None, query_params=None):
        self.data = data
        self.params = params or []
        self.query_params = query_params or {}
        self.headers = {}
        self.path = ""
        self.method = "POST"

    @property
    def callback_url(self):
        return None


def _arg_names(func):
    try:
        return list(inspect.getargspec(func).args)  # IronPython 2.7
    except (AttributeError, ValueError, TypeError):
        return list(inspect.signature(func).parameters)  # novermin (IronPython 3 path)


def make_transport(uiapp):
    api = RecorderAPI()
    errors = register_all(api)

    def transport(method, path, payload):
        route, url_params = selftest.match_route(api.routes, method, path)
        if route is None:
            return 404, {"status": "error", "error": "No route for %s %s" % (method, path)}
        uidoc = uiapp.ActiveUIDocument
        doc = uidoc.Document if uidoc is not None else None
        values = {"doc": doc, "uidoc": uidoc, "uiapp": uiapp,
                  "request": _Request(payload if method == "POST" else None, list(url_params.values()))}
        try:
            from urllib import unquote  # IronPython 2
        except ImportError:
            from urllib.parse import unquote  # novermin (py2 fallback above)
        for k, v in url_params.items():
            values[k] = unquote(v) if isinstance(v, str) else v
        kwargs = dict((a, values.get(a)) for a in _arg_names(route["func"]))
        res = route["func"](**kwargs)
        if hasattr(res, "status") and hasattr(res, "data"):
            return int(res.status), res.data
        return 200, res

    return transport, errors


def run(uiapp, groups=None, log=None):
    """Run the self-test on a copy of the bundled tests/test.rvt. Returns (report, json_path, md_path)."""
    scratch = os.path.join(tempfile.gettempdir(), "RVTSS_live")
    if not os.path.isdir(scratch):
        os.makedirs(scratch)
    ext_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def prepare_model(t):
        src = os.path.join(ext_root, "tests", "test.rvt")
        if not os.path.isfile(src):
            return None
        dst = os.path.join(scratch, "RVTSS_selftest_%s.rvt" % t.stamp)
        shutil.copy2(src, dst)
        return dst

    transport, errors = make_transport(uiapp)
    env = {"transport": "in-process (pyRevit button)"}
    if errors:
        env["route_registration_errors"] = errors
    report = selftest.run(transport, scratch, prepare_model, groups=groups, log=log, environment=env)
    json_path = os.path.join(scratch, "rvtss_live_report.json")
    md_path = os.path.join(scratch, "rvtss_live_report.md")
    with io.open(json_path, "w", encoding="utf-8") as fh:
        fh.write(u"%s" % selftest.to_json(report))
    with io.open(md_path, "w", encoding="utf-8") as fh:
        fh.write(u"%s" % selftest.to_markdown(report))
    return report, json_path, md_path
