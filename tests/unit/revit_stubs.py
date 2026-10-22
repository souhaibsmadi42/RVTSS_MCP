# -*- coding: utf-8 -*-
"""Minimal stand-ins for pyRevit / the Revit API so the Revit-side modules can be
imported and their routes registered under CPython (no Revit available).

The stubs are permissive: any attribute access returns another stub class, so
module-level code (class definitions deriving from Revit interfaces, enum
lookups...) executes. They are NOT a Revit simulator - behaviour that needs
the real API is verified in a live Revit session.
"""
import sys
import types
from contextlib import contextmanager


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        sub = _Meta(name, (_Stub,), {})
        setattr(cls, name, sub)
        return sub


class _Stub(object, metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __iter__(self):
        return iter(())


class StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        cls = _Meta(name, (_Stub,), {})
        setattr(self, name, cls)
        return cls


class FakeAPI(object):
    """Records routes like pyrevit.routes.API."""

    def __init__(self, name):
        self.name = name
        self.routes = []

    def route(self, path, methods=None):
        def deco(func):
            self.routes.append({"path": path, "methods": methods or ["GET"], "func": func})
            return func
        return deco


def make_response(data=None, status=200, headers=None):
    return {"data": data, "status": status}


class FakeRequest(object):
    def __init__(self, data):
        self.data = data


def build_modules():
    mods = {}
    pyrevit = StubModule("pyrevit")
    routes = types.ModuleType("pyrevit.routes")
    routes.API = FakeAPI
    routes.make_response = make_response
    pyrevit.routes = routes
    pyrevit.DB = StubModule("Autodesk.Revit.DB")
    pyrevit.HOST_APP = _Stub()
    revit = StubModule("pyrevit.revit")
    revit.doc = None
    revit.HOST_APP = _Stub()
    revit_db = StubModule("pyrevit.revit.db")
    revit_db_query = StubModule("pyrevit.revit.db.query")
    revit.db = revit_db
    revit_db.query = revit_db_query
    pyrevit.revit = revit
    mods.update({
        "pyrevit": pyrevit, "pyrevit.routes": routes, "pyrevit.revit": revit,
        "pyrevit.revit.db": revit_db, "pyrevit.revit.db.query": revit_db_query,
        "System": StubModule("System"),
        "System.Collections": StubModule("System.Collections"),
        "System.Collections.Generic": StubModule("System.Collections.Generic"),
        "Autodesk": StubModule("Autodesk"), "Autodesk.Revit": StubModule("Autodesk.Revit"),
        "Autodesk.Revit.UI": StubModule("Autodesk.Revit.UI"),
        "Autodesk.Revit.DB": pyrevit.DB,
    })
    sio = types.ModuleType("StringIO")
    import io
    sio.StringIO = io.StringIO
    mods["StringIO"] = sio
    return mods


@contextmanager
def revit_environment():
    """Install the stubs, yield, then remove them and every revit_mcp/startup module."""
    saved = dict(sys.modules)
    sys.modules.update(build_modules())
    for name in list(sys.modules):
        if name == "startup" or name == "revit_mcp" or name.startswith("revit_mcp."):
            del sys.modules[name]
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in saved:
                del sys.modules[name]
        sys.modules.update(saved)
