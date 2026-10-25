# -*- coding: utf-8 -*-
"""v2.2 Revit side (stub pyRevit): batch transaction group, read-only mode, new routes, pure helpers."""
import importlib

import pytest

from .revit_stubs import revit_environment, FakeRequest
from revit_mcp.pure import spaces as SP
from revit_mcp.pure import exportnames as N
from revit_mcp.pure import filter_rules as FR


@pytest.fixture
def rv():
    with revit_environment():
        startup = importlib.import_module("startup")
        import revit_mcp
        from revit_mcp import batch, core

        yield startup.api, revit_mcp, batch, core


class FakeDoc(object):
    Title = "Tower"
    PathName = ""
    IsReadOnly = False
    IsLinked = False
    IsModifiable = False
    IsFamilyDocument = False


class FakeGroup(object):
    log = []

    def __init__(self, doc, name):
        self.name = name
        self.state = "new"

    def Start(self):
        self.state = "started"
        FakeGroup.log.append(("start", self.name))

    def Assimilate(self):
        self.state = "ended"
        FakeGroup.log.append(("assimilate", self.name))

    def RollBack(self):
        self.state = "ended"
        FakeGroup.log.append(("rollback", self.name))

    def HasStarted(self):
        return self.state != "new"

    def HasEnded(self):
        return self.state == "ended"


def _install(batch, monkeypatch, outcomes):
    """Replace two batchable route handlers with fakes answering from `outcomes` (list of data dicts)."""
    seen = []
    answers = list(outcomes)

    def fake_route(doc, request):
        seen.append(dict(request.data))
        return {"data": answers.pop(0), "status": 200}

    monkeypatch.setitem(batch.ROUTE_TABLE, "/set_parameters/", fake_route)
    monkeypatch.setitem(batch.ROUTE_TABLE, "/views/create/", fake_route)
    monkeypatch.setattr(batch.DB, "TransactionGroup", FakeGroup)
    FakeGroup.log = []
    return seen


def _cmds(n=2):
    eps = ["/set_parameters/", "/views/create/"]
    return [{"index": i, "tool": "t%d" % i, "endpoint": eps[i % 2], "payload": {"x": i, "dry_run": True}}
            for i in range(n)]


def _run(batch, core, data):
    return core.handle(FakeDoc(), FakeRequest(data), batch.run_batch, uidoc=None)


def test_route_table_records_every_route(rv):
    api, _rm, batch, _core = rv
    assert set(r["path"] for r in api.routes) == set(batch.ROUTE_TABLE)
    for ep in batch.BATCHABLE_ENDPOINTS:
        assert ep in batch.ROUTE_TABLE, ep


def test_batch_success_assimilates_one_undo_step(rv, monkeypatch):
    _api, _rm, batch, core = rv
    seen = _install(batch, monkeypatch, [{"status": "success", "a": 1}, {"status": "success", "b": 2}])
    res = _run(batch, core, {"commands": _cmds(), "name": "My batch"})
    data = res["data"]
    assert data["status"] == "success" and data["committed"] is True and data["succeeded"] == 2
    assert [k for k, _ in FakeGroup.log] == ["start", "assimilate"] and FakeGroup.log[0][1] == "RVTSS: My batch"
    assert all("dry_run" not in p for p in seen)


def test_batch_failure_rolls_everything_back_and_stops(rv, monkeypatch):
    _api, _rm, batch, core = rv
    seen = _install(batch, monkeypatch, [{"status": "error", "error": "bad"}, {"status": "success"}])
    data = _run(batch, core, {"commands": _cmds()})["data"]
    assert data["status"] == "error" and data["rolled_back"] is True and data["committed"] is False
    assert data["not_run"] == [1] and len(seen) == 1
    assert [k for k, _ in FakeGroup.log] == ["start", "rollback"]


def test_batch_continue_on_error_keeps_successes(rv, monkeypatch):
    _api, _rm, batch, core = rv
    _install(batch, monkeypatch, [{"status": "error", "error": "bad"}, {"status": "success"}])
    data = _run(batch, core, {"commands": _cmds(), "continue_on_error": True})["data"]
    assert data["status"] == "partial" and data["failed"] == 1 and data["succeeded"] == 1
    assert [k for k, _ in FakeGroup.log] == ["start", "assimilate"]


def test_batch_preview_counts_as_failure(rv, monkeypatch):
    _api, _rm, batch, core = rv
    _install(batch, monkeypatch, [{"status": "preview", "requires_confirmation": True}, {"status": "success"}])
    data = _run(batch, core, {"commands": _cmds()})["data"]
    assert data["results"][0]["outcome"] == "needs_confirmation" and data["rolled_back"] is True


def test_batch_dry_run_always_rolls_back(rv, monkeypatch):
    _api, _rm, batch, core = rv
    _install(batch, monkeypatch, [{"status": "success"}, {"status": "success"}])
    data = _run(batch, core, {"commands": _cmds(), "dry_run": True})["data"]
    assert data["status"] == "dry_run" and data["rolled_back"] is True
    assert [k for k, _ in FakeGroup.log] == ["start", "rollback"]


def test_batch_refuses_unknown_endpoint_and_too_many(rv, monkeypatch):
    _api, _rm, batch, core = rv
    _install(batch, monkeypatch, [])
    res = _run(batch, core, {"commands": [{"endpoint": "/execute_code/", "payload": {}}]})
    assert res["status"] == 400 and "not batchable" in res["data"]["error"]
    res = _run(batch, core, {"commands": _cmds(21)})
    assert res["status"] == 400 and "at most 20" in res["data"]["error"]
    assert FakeGroup.log == []


def test_read_only_mode_refuses_changes_but_allows_dry_run(rv, monkeypatch):
    _api, _rm, batch, core = rv
    monkeypatch.setenv("RVTSS_READ_ONLY", "1")
    with pytest.raises(core.RvtssError) as ei:
        core.run_transaction(FakeDoc(), "Edit", lambda: 1)
    assert ei.value.status == 403 and ei.value.extra.get("read_only") is True
    _install(batch, monkeypatch, [{"status": "success"}, {"status": "success"}])
    res = _run(batch, core, {"commands": _cmds()})
    assert res["status"] == 403
    assert _run(batch, core, {"commands": _cmds(), "dry_run": True})["data"]["status"] == "dry_run"
    assert core.read_only_response("save_document")["status"] == 403
    monkeypatch.delenv("RVTSS_READ_ONLY")
    assert core.read_only_response("save_document") is None


def test_unpack_response_handles_objects_and_stub_dicts(rv):
    _api, _rm, batch, _core = rv

    class Resp(object):
        status = 409
        data = {"status": "error"}

    assert batch.unpack_response(Resp()) == (409, {"status": "error"})
    assert batch.unpack_response({"data": {"status": "success"}, "status": 200}) == (200, {"status": "success"})
    assert batch.classify(200, {"status": "success"}) == "ok"
    assert batch.classify(500, {"status": "success"}) == "failed"


NEW_ROUTES = ["/batch/", "/rooms/list/", "/rooms/details/", "/materials/list/", "/materials/takeoff/",
              "/materials/manage/", "/annotation/untagged/", "/annotation/tag/", "/annotation/text/",
              "/export/settings/", "/export/run/", "/mep/systems/", "/mep/connectors/", "/mep/disconnects/",
              "/worksets/manage/", "/purge/", "/impact/survey/", "/coordinates/", "/spatial/query/",
              "/views/filters/", "/sheets/revisions/"]


def test_new_routes_registered(rv):
    api, revit_mcp, _b, _c = rv
    paths = set(r["path"] for r in api.routes)
    assert revit_mcp.REGISTRATION_ERRORS == {}
    for p in NEW_ROUTES:
        assert p in paths, p


@pytest.mark.parametrize("module,func,data,needle", [
    ("spaces", "list_spaces", {"kind": "office"}, "kind must be"),
    ("spaces", "space_details", {}, "element_ids"),
    ("materials", "takeoff", {}, "scope"),
    ("annotation", "untagged", {}, "categories"),
    ("exporting", "run_export", {"format": "jpg"}, "format must be"),
    ("mep", "connectors_of", {}, "element_ids"),
    ("impact", "survey", {}, "element_ids"),
    ("impact", "survey", {"element_ids": list(range(21))}, "At most 20"),
    ("spatial", "spatial_query", {"mode": "teleport"}, "mode must be"),
])
def test_input_validation_errors_are_structured(rv, module, func, data, needle):
    _api, _rm, _b, core = rv
    mod = importlib.import_module("revit_mcp." + module)

    class Doc(FakeDoc):
        IsFamilyDocument = False

    res = core.handle(Doc(), FakeRequest(data), getattr(mod, func))
    assert res["data"]["status"] == "error", res
    assert needle in res["data"]["error"], res["data"]


# ---------------------------------------------------------------- pure helpers
def test_spatial_status_and_warning_classification():
    assert SP.spatial_status(False, 0) == "unplaced"
    assert SP.spatial_status(True, 12.5) == "placed"
    assert SP.spatial_status(True, 0) == "not_enclosed_or_redundant"
    assert SP.spatial_status(True, 0, "redundant") == "redundant"
    assert SP.classify_warning("Room is not in a properly enclosed region") == "not_enclosed"
    assert SP.classify_warning("Multiple Rooms are in the same enclosed region.") == "redundant"
    assert SP.classify_warning("Highlighted walls overlap") is None


def test_wall_finish_never_negative():
    assert SP.wall_finish(5.0, 3.0, [(1.0, 2.0)]) == (15.0, 2.0, 13.0)
    assert SP.wall_finish(1.0, 1.0, [(5.0, 5.0)]) == (1.0, 1.0, 0.0)
    assert SP.wall_finish(None, 3.0) == (0.0, 0.0, 0.0)


def test_summarize_by():
    items = [{"level": "L1", "area": 10.0}, {"level": "L1", "area": 5.5}, {"level": None, "area": 1}]
    assert SP.summarize_by(items, "level") == {"L1": {"count": 2, "area": 15.5}, "(none)": {"count": 1, "area": 1.0}}


def test_export_names():
    assert N.render("{number} - {name}", {"number": "A101", "name": "Plan: Level 1"}) == "A101 - Plan_ Level 1"
    assert N.render("{number} - {name}", {"number": "A101", "name": ""}) == "A101"
    assert N.unique(["A", "a", "B", "A"]) == ["A", "a_2", "B", "A_3"]
    assert N.strip_extension("model.ifc", "ifc") == "model"
    with pytest.raises(N.NamingError):
        N.render("{sheet_no}", {})
    assert N.sanitize("  ") == "export"


def test_filter_rules():
    assert FR.validate_rule({"parameter": "Fire Rating", "op": "has_value"})["kind"] is None
    r = FR.validate_rule({"parameter": "Width", "op": "greater", "value": 900, "unit": "mm"})
    assert r["kind"] == "double" and r["value"] == 900.0
    assert FR.validate_rule({"parameter": "Mark", "op": "contains", "value": "D"})["kind"] == "string"
    assert FR.validate_rule({"parameter": "Is Fire", "value": True})["value"] == 1
    for bad in ({"op": "equals", "value": 1}, {"parameter": "x", "op": "near", "value": 1},
                {"parameter": "x", "op": "contains", "value": 5}, {"parameter": "x", "op": "equals"}):
        with pytest.raises(FR.RuleError):
            FR.validate_rule(bad)
