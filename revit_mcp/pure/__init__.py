# -*- coding: utf-8 -*-
"""Revit-independent helpers used by the route modules.

Nothing in this package may import pyrevit, clr or the Revit API: it must stay
importable from IronPython 2.7, IronPython 3.4 and CPython 3 so that it can be
unit-tested offline (see tests/unit/test_pure_*.py).
"""
