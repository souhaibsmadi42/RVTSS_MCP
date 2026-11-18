# -*- coding: utf-8 -*-
"""Shared by the gen_<module>.py vector generators of the pure modules ported in lane b.

Each generator imports the ORIGINAL module from revit_mcp/pure, calls its functions and writes
host/tests/vectors/<module>.json: {"cases": [{"fn", "args", "kwargs", "out" | "err", ...}], ...}.
Run from the repo root:  uv run --project . python host/tests/vectors/gen_<module>.py
"""
import copy
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def plain(value):
    """JSON form of a result: tuples and sets become lists, non-finite floats become strings."""
    if isinstance(value, dict):
        return dict((k if isinstance(k, str) else str(k), plain(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return repr(value)
    return value


class Recorder(object):
    def __init__(self, module):
        self.module = module
        self.cases = []
        self.extra = {}

    def call(self, fn, *args, **kwargs):
        """Record one call of module.fn; arguments are stored as they were before the call."""
        return self.call_as(fn, getattr(self.module, fn), args, kwargs)

    def call_as(self, fn, func, args, kwargs, shown_args=None, shown_kwargs=None, **more):
        case = {"fn": fn, "args": plain(copy.deepcopy(list(args if shown_args is None else shown_args))),
                "kwargs": plain(copy.deepcopy(dict(kwargs if shown_kwargs is None else shown_kwargs)))}
        case.update(more)
        try:
            case["out"] = plain(func(*args, **kwargs))
        except Exception as e:  # the exception type is the expected result
            case["err"] = type(e).__name__
            case["msg"] = str(e)
        self.cases.append(case)
        return case

    def write(self, name):
        path = os.path.join(HERE, name + ".json")
        data = {"cases": self.cases}
        data.update(self.extra)
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, ensure_ascii=True, indent=1))
            fh.write(u"\n")
        errs = len([c for c in self.cases if "err" in c])
        print("%s: %d cases (%d raising) -> %s" % (name, len(self.cases), errs, path))
