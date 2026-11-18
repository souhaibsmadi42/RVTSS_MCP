# -*- coding: utf-8 -*-
"""Recorder shared by the lane-c vector generators (gen_clash.py, gen_diff.py ...).

Each case is {"fn", "args", "expected"} or {"fn", "args", "error": exception type name, "message"}.
Arguments are copied before the call, so functions that change their input are recorded with the input as given.
"""
import copy
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class Recorder(object):
    def __init__(self, name):
        self.name = name
        self.cases = []
        self.extra = {}

    def call(self, fn_name, fn, *args):
        case = {"fn": fn_name, "args": copy.deepcopy(list(args))}
        try:
            case["expected"] = fn(*copy.deepcopy(list(args)))
        except Exception as ex:  # the error type is part of the contract
            case["error"] = type(ex).__name__
            case["message"] = "%s" % (ex,)
        self.cases.append(case)
        return case

    def save(self):
        data = dict(self.extra)
        data["cases"] = self.cases
        text = json.dumps(data, ensure_ascii=False, indent=1, allow_nan=False)
        json.loads(text)
        path = os.path.join(HERE, self.name + ".json")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        errors = len([c for c in self.cases if "error" in c])
        print("%s: %d cases (%d errors) -> %s" % (self.name, len(self.cases), errors, path))
