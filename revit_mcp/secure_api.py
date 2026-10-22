# -*- coding: UTF-8 -*-
"""Optional shared-secret protection for every revit_mcp route (RVTSS).

Settings (environment of the Revit process, or %APPDATA%/RVTSS/config.json):
    RVTSS_TOKEN / "token"                                 shared secret; unset = no token (default)
    RVTSS_ALLOW_CODE_EXECUTION / "allow_code_execution"   default allowed (backward compatible)
    RVTSS_ALLOW_REMOTE / "allow_remote"                   acknowledge a Routes server reachable beyond loopback

pyRevit Routes chooses API context and injects arguments by inspecting the
handler's argument names (routes/server/handler.py), so the protecting wrapper
is generated with exactly the handler's arguments plus `request`.
"""
import inspect
import logging
import os

from .pure import security as S

logger = logging.getLogger(__name__)


def _config():
    try:
        from .core import load_config

        return load_config()
    except Exception:
        return {}


def settings():
    cfg = _config()
    token = os.environ.get("RVTSS_TOKEN") or cfg.get("token") or None
    allow_code = S.parse_flag(os.environ.get("RVTSS_ALLOW_CODE_EXECUTION"),
                              S.parse_flag(cfg.get("allow_code_execution"), True))
    allow_remote = S.parse_flag(os.environ.get("RVTSS_ALLOW_REMOTE"), S.parse_flag(cfg.get("allow_remote"), False))
    return {"token": token, "allow_code_execution": allow_code, "allow_remote": allow_remote}


def routes_host():
    try:
        from pyrevit.userconfig import user_config

        return user_config.routes_host
    except Exception:
        return None


def security_status():
    """Public summary for /status/ and session info (never includes the token)."""
    st = settings()
    host = routes_host()
    exposed = S.binds_all_interfaces(host) or not S.is_loopback(host or "")
    warnings = []
    if exposed and not st["token"]:
        warnings.append("pyRevit Routes listens on '{}' (all interfaces / non-loopback) without an RVTSS token: "
                        "anyone who can reach port 48884 can drive Revit. Set pyRevit Settings > Routes > Host "
                        "to 127.0.0.1 or set RVTSS_TOKEN.".format(host or "0.0.0.0"))
    if exposed and not st["allow_remote"] and st["token"]:
        warnings.append("Routes is reachable beyond loopback; set RVTSS_ALLOW_REMOTE=1 to acknowledge (VM setups).")
    return {"token_required": bool(st["token"]), "code_execution_allowed": st["allow_code_execution"],
            "routes_host": host or "0.0.0.0 (all interfaces)", "reachable_beyond_loopback": exposed,
            "allow_remote": st["allow_remote"], "warnings": warnings}


def _arg_names(func):
    try:
        return list(inspect.getargspec(func).args)
    except (AttributeError, ValueError, TypeError):
        return list(inspect.signature(func).parameters)  # novermin (IronPython 3 path)


def _unauthorized():
    from pyrevit import routes

    return routes.make_response(data={
        "status": "error", "error": "RVTSS token missing or invalid",
        "hint": "Set the same RVTSS_TOKEN for the MCP server (main.py) and for Revit, then restart the MCP server."},
        status=401)


def make_checker(token):
    def check(request):
        data = getattr(request, "data", None)
        provided = S.extract_token(data if isinstance(data, dict) else None,
                                   getattr(request, "query_params", None), getattr(request, "headers", None))
        if isinstance(data, dict):
            data.pop(S.TOKEN_BODY_KEY, None)
        if not S.constant_time_equal(provided, token):
            return _unauthorized()
        return None
    return check


def protect(handler, check):
    """Wrap a handler, keeping its argument names (pyRevit injects by name)."""
    args = _arg_names(handler)
    params = list(args) + ([] if "request" in args else ["request"])
    src = ("def {name}({params}):\n"
           "    _denied = _check(request)\n"
           "    if _denied is not None:\n"
           "        return _denied\n"
           "    return _handler({call})\n").format(
        name=getattr(handler, "__name__", "handler"), params=", ".join(params),
        call=", ".join("{0}={0}".format(a) for a in args))
    ns = {"_check": check, "_handler": handler}
    exec(src, ns)
    wrapped = ns[getattr(handler, "__name__", "handler")]
    wrapped.__doc__ = handler.__doc__
    return wrapped


class SecureAPI(object):
    """Proxy for routes.API applying the token check to every route but /status/ and /ping/."""

    def __init__(self, api, token):
        self._api = api
        self._check = make_checker(token)

    def route(self, path, methods=None):
        real = self._api.route(path, methods=methods) if methods is not None else self._api.route(path)

        def deco(func):
            if path in S.UNPROTECTED_PATHS:
                return real(func)
            return real(protect(func, self._check))
        return deco

    def __getattr__(self, name):
        return getattr(self._api, name)


def secured(api):
    st = settings()
    if not st["token"]:
        return api
    logger.info("RVTSS token protection enabled for revit_mcp routes")
    return SecureAPI(api, st["token"])
