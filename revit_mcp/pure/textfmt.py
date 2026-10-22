# -*- coding: utf-8 -*-
"""Value templates used by bulk parameter updates and batch renaming.

Template syntax (any text outside braces is kept verbatim):
    {n}           running sequence number (start/step configurable)
    {n:03}        zero padded sequence number
    {id}          element id
    {value}       current value of the target parameter / current name
    {Any Param}   display value of another parameter on the same element
                  (falls back to the type parameter when not found on the instance)
    {{ and }}     literal braces
"""
import re

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}:]+)(?::([^{}]*))?\}")


class TemplateError(ValueError):
    pass


def _format_number(n, spec):
    if not spec:
        return str(n)
    try:
        return format(n, spec if spec[0] in "0123456789<>^=+- " else "")
    except ValueError:
        raise TemplateError("Bad number format '%s'" % spec)


def tokens(template):
    """Return the names of the tokens referenced by a template (excluding n/id/value)."""
    out = []
    for m in _TOKEN.finditer(template):
        name = m.group(1)
        if name is None:
            continue
        name = name.strip()
        if name not in ("n", "id", "value") and name not in out:
            out.append(name)
    return out


def render(template, resolver, n=None, element_id=None, current=None):
    """Render a template.

    resolver(name) -> string or None. Missing values raise TemplateError so a
    bulk update never silently writes half-filled values.
    """
    def repl(m):
        raw = m.group(0)
        if raw == "{{":
            return "{"
        if raw == "}}":
            return "}"
        name = m.group(1).strip()
        spec = m.group(2)
        if name == "n":
            if n is None:
                raise TemplateError("{n} used but no sequence number available")
            return _format_number(n, spec)
        if name == "id":
            return str(element_id)
        if name == "value":
            return "" if current is None else u"%s" % current
        val = resolver(name)
        if val is None:
            raise TemplateError("Parameter '%s' referenced in template has no value" % name)
        return u"%s" % val

    return _TOKEN.sub(repl, template)


def apply_rename(name, find=None, replace="", regex=False, prefix="", suffix="",
                 case=None):
    """Apply a rename rule to a single string. Returns the new string."""
    out = name
    if find:
        if regex:
            try:
                out = re.sub(find, replace or "", out)
            except re.error as ex:
                raise TemplateError("Invalid regex '%s': %s" % (find, ex))
        else:
            out = out.replace(find, replace or "")
    if case == "upper":
        out = out.upper()
    elif case == "lower":
        out = out.lower()
    elif case == "title":
        out = out.title()
    return u"%s%s%s" % (prefix or "", out, suffix or "")


# Characters Revit refuses in names of views, sheets, families, types, etc.
INVALID_NAME_CHARS = u'\\:{}[]|;<>?`~'


def invalid_name_chars(name):
    return sorted(set(c for c in name if c in INVALID_NAME_CHARS))
