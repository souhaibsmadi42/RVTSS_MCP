# -*- coding: utf-8 -*-
"""Minimal RFC 4180 CSV writer/reader that behaves the same on IronPython 2/3 and CPython."""
import csv
import io


def _cell(value):
    if value is None:
        return u""
    if isinstance(value, bool):
        return u"Yes" if value else u"No"
    s = value if isinstance(value, type(u"")) else u"%s" % (value,)
    if any(c in s for c in (u",", u'"', u"\n", u"\r")):
        s = u'"' + s.replace(u'"', u'""') + u'"'
    return s


def to_csv(header, rows):
    lines = [u",".join(_cell(h) for h in header)]
    for r in rows:
        lines.append(u",".join(_cell(v) for v in r))
    return u"\r\n".join(lines) + u"\r\n"


def parse_csv(text):
    """Return (header, rows as dicts). Strips a UTF-8 BOM and blank lines."""
    if text and text[0] == u"﻿":
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or u"").strip() for c in r)]
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        r = list(r) + [u""] * (len(header) - len(r))
        out.append(dict(zip(header, r)))
    return header, out


def write_file(path, text):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(text)


def read_file(path):
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return fh.read()
