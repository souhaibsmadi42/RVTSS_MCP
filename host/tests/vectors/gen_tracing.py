# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/tracing.py -> tracing.json."""
import copy

from _lane_b import Recorder, plain
from revit_mcp.pure import tracing as T

r = Recorder(T)
r.extra["constants"] = {"REQUEST_ID_BODY_KEY": T.REQUEST_ID_BODY_KEY, "REQUEST_ID_QUERY_KEY": T.REQUEST_ID_QUERY_KEY}

for v in [None, "abc-123_x.y:z", "a b", "x" * 64, "x" * 65, "x\nINJECTED", "", " ", "  padded  ", "a", "A.B:C-D_E", "a/b",
          "a\\b", "a,b", "a;b", u"é", "id\n", "\tid\t", 123, 0, 1.5, True, False, "a=b", "a+b", "a%20b", "{}", "[x]",
          "x" * 63 + " ", "00000000-0000-0000-0000-000000000000", "req:2026-01-01T00.00.00", "a\u0000b"]:
    r.call("clean_request_id", v)


def pop(data, query):
    """Returns [id, data after the call] so the removal from the body is checked too."""
    rid = T.pop_request_id(data, query)
    return [rid, data]


for data, query in [({"_rvtss_request_id": "r1", "a": 1}, None), ({}, {"rvtss_request_id": "q1"}), (None, None), ({}, {}),
                    ({"_rvtss_request_id": "bad id", "a": 1}, {"rvtss_request_id": "q1"}),
                    ({"_rvtss_request_id": None, "a": 1}, {"rvtss_request_id": "q1"}),
                    ({"_rvtss_request_id": "", "a": 1}, {"rvtss_request_id": "q1"}),
                    ({"_rvtss_request_id": "body"}, {"rvtss_request_id": "query"}), ({"a": 1}, {"other": "x"}),
                    (None, {"rvtss_request_id": "q2"}), ({"a": 1}, None), (None, {"rvtss_request_id": " q3 "}),
                    (None, {"rvtss_request_id": "bad id"}), ({"_rvtss_request_id": 42}, None),
                    ({"_rvtss_request_id": 0}, {"rvtss_request_id": "q"}), ({"rvtss_request_id": "wrong-place"}, None),
                    (None, {"_rvtss_request_id": "wrong-place"}), (None, {"rvtss_request_id": 7})]:
    r.call_as("pop_request_id", pop, (data, query), {})


class Resp(object):
    def __init__(self, data):
        self.data = data


def attach(kind, body, rid):
    """kind "plain": the body itself; "object": a response object with a .data attribute.
    Returns the body after the call (and whether the same response came back)."""
    response = Resp(body) if kind == "object" else body
    back = T.attach_request_id(response, rid)
    return {"same": back is response, "body": plain(body)}


BODIES = [{"status": "success"}, {"data": {"x": 1}, "status": 200}, {"data": {"x": 1}, "status": 200, "more": 1},
          {"data": {"x": 1}}, {"data": "text", "status": 200}, {"request_id": "keep"},
          {"data": {"request_id": "keep"}, "status": 200}, "text body", None, 5, [1, 2], {}, {"data": {}, "status": 500},
          {"data": None, "status": 200}, {"data": [1], "status": 200}, {"request_id": None}]
for body in BODIES:
    for kind in ("plain", "object"):
        for rid in ("r1", "", None):
            r.call_as("attach_request_id", attach, (kind, copy.deepcopy(body), rid), {})
r.write("tracing")
