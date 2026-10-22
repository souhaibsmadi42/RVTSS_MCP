# -*- coding: utf-8 -*-
"""Security helpers: token comparison, secret redaction, loopback checks, env flags.

pyRevit Routes (checked in pyrevitlib/pyrevit/routes/server/server.py) builds the
handler Request from path, method, body and query string only - HTTP headers
and the client address never reach a route handler. The RVTSS token is
therefore accepted from the JSON body (`_rvtss_token`, POST) or the query
string (`rvtss_token`, GET); the X-RVTSS-Token header is also checked in case
a future pyRevit forwards headers.
"""
import re

TOKEN_BODY_KEY = "_rvtss_token"
TOKEN_QUERY_KEY = "rvtss_token"
TOKEN_HEADER = "X-RVTSS-Token"
UNPROTECTED_PATHS = ("/status/", "/ping/")

_SECRET_KEYS = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|apikey|authorization|bearer|"
                          r"connection[_-]?string|private[_-]?key|access[_-]?key)")
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)")
_KEY_VALUE = re.compile(r"""(?i)(["']?(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|"""
                        r"""authorization)["']?\s*[:=]\s*)(["']?)([^"'\s,}]+)""")
_LONG_OPAQUE = re.compile(r"\b[A-Za-z0-9+/=_\-]{40,}\b")
REDACTED = "[REDACTED]"


def parse_flag(value, default=None):
    """'1/true/yes/on' -> True, '0/false/no/off' -> False, None/'' -> default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on", "allow", "allowed"):
        return True
    if s in ("0", "false", "no", "off", "deny", "denied", "disabled"):
        return False
    return default


def constant_time_equal(a, b):
    if a is None or b is None:
        return False
    a, b = str(a), str(b)
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0


def extract_token(data=None, query_params=None, headers=None):
    if isinstance(data, dict) and data.get(TOKEN_BODY_KEY):
        return data.get(TOKEN_BODY_KEY)
    if query_params and query_params.get(TOKEN_QUERY_KEY):
        v = query_params.get(TOKEN_QUERY_KEY)
        return v[0] if isinstance(v, list) else v
    if headers:
        for k, v in headers.items():
            if str(k).lower() == TOKEN_HEADER.lower():
                return v
    return None


def is_loopback(host):
    h = (host or "").strip().lower().strip("[]")
    return h in ("127.0.0.1", "localhost", "::1") or h.startswith("127.")


def binds_all_interfaces(host):
    return (host or "").strip() in ("", "0.0.0.0", "::", "*")


def redact(text, max_len=None):
    """Mask secret-looking values (API keys, tokens, key=value secrets, long opaque strings)."""
    if text is None:
        return None
    s = u"%s" % (text,)
    s = _SECRET_VALUE.sub(REDACTED, s)
    s = _KEY_VALUE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, s)
    s = _LONG_OPAQUE.sub(lambda m: m.group(0) if re.match(r"^[0-9a-fA-F\-]{36}$", m.group(0)) else REDACTED, s)
    if max_len and len(s) > max_len:
        s = s[:max_len] + u"...[+%d chars]" % (len(s) - max_len)
    return s


def redact_mapping(data):
    """Copy of a dict/list with values under secret-looking keys masked (recursively)."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if _SECRET_KEYS.search(str(k)):
                out[k] = REDACTED
            else:
                out[k] = redact_mapping(v)
        return out
    if isinstance(data, list):
        return [redact_mapping(v) for v in data]
    if isinstance(data, (str, type(u""))):
        return redact(data)
    return data
