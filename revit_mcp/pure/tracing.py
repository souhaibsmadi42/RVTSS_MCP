# -*- coding: utf-8 -*-
"""Correlation ids: MCP server -> Routes request -> audit log -> response.

pyRevit Routes does not hand HTTP headers to handlers, so the id travels in the
JSON body (`_rvtss_request_id`, POST) or the query string (`rvtss_request_id`,
GET), like the RVTSS token.
"""
import re

REQUEST_ID_BODY_KEY = "_rvtss_request_id"
REQUEST_ID_QUERY_KEY = "rvtss_request_id"
_VALID = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")


def clean_request_id(value):
    """The id if it is a short safe token, else None (it ends up in log lines)."""
    if value is None:
        return None
    try:
        value = str(value).strip()
    except Exception:
        return None
    return value if _VALID.match(value) else None


def pop_request_id(data=None, query_params=None):
    """Take the id out of the body (so handlers never see it) or read it from the query."""
    rid = None
    if isinstance(data, dict) and REQUEST_ID_BODY_KEY in data:
        rid = data.pop(REQUEST_ID_BODY_KEY)
    if rid is None and query_params:
        try:
            rid = query_params.get(REQUEST_ID_QUERY_KEY)
        except Exception:
            rid = None
    return clean_request_id(rid)


def _payload(response):
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(response, dict):
        inner = response.get("data")
        # routes.make_response shape in the unit-test stubs: {"data": {...}, "status": 200}
        if isinstance(inner, dict) and set(response) == {"data", "status"}:
            return inner
        return response
    return None


def attach_request_id(response, request_id):
    """Add request_id to a Routes response / plain dict payload (no-op for other bodies)."""
    if not request_id:
        return response
    payload = _payload(response)
    if payload is not None and "request_id" not in payload:
        payload["request_id"] = request_id
    return response
