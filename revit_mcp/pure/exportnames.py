# -*- coding: utf-8 -*-
"""File names for exports (RVTSS v2.2): templates, sanitising, uniqueness."""
import re

FORMATS = {
    "pdf": ".pdf", "dwg": ".dwg", "dxf": ".dxf", "ifc": ".ifc", "nwc": ".nwc", "csv": ".csv",
}
# formats exported once per model (not per view / sheet)
MODEL_FORMATS = ("ifc", "nwc")
_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FIELD = re.compile(r"\{(\w+)\}")
FIELDS = ("number", "name", "title", "revision", "view_type", "date", "document")


class NamingError(ValueError):
    pass


def default_template(is_sheet):
    return "{number} - {name}" if is_sheet else "{name}"


def sanitize(name, replacement="_", max_len=180):
    s = _INVALID.sub(replacement, name or "").strip().strip(".")
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "export"


def render(template, fields):
    """'{number} - {name}' + {'number': 'A101', 'name': 'Plan'} -> 'A101 - Plan' (sanitised)."""
    unknown = [f for f in _FIELD.findall(template or "") if f not in FIELDS]
    if unknown:
        raise NamingError("Unknown naming field(s) %s. Use: %s" % (", ".join(sorted(set(unknown))),
                                                                     ", ".join("{%s}" % f for f in FIELDS)))
    out = _FIELD.sub(lambda m: u"%s" % (fields.get(m.group(1)) or ""), template)
    out = re.sub(r"(\s*-\s*)+$", "", out)  # "A101 - " when name is empty
    out = re.sub(r"^(\s*-\s*)+", "", out)
    return sanitize(out)


def unique(names):
    """Make a list of stems unique (case-insensitive, as on Windows) by appending _2, _3..."""
    seen = {}
    out = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen[key] = 1
            out.append(n)
            continue
        i = seen[key] + 1
        while (u"%s_%d" % (n, i)).lower() in seen:
            i += 1
        seen[key] = i
        candidate = u"%s_%d" % (n, i)
        seen[candidate.lower()] = 1
        out.append(candidate)
    return out


def strip_extension(name, fmt):
    ext = FORMATS.get(fmt, "")
    if ext and (name or "").lower().endswith(ext):
        return name[: -len(ext)]
    return name
