# -*- coding: utf-8 -*-
"""RVTSS live self-test (see revit_mcp/pure/selftest.py)."""
import os
import sys

# make the extension root (which holds the revit_mcp package) importable
EXT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if EXT_ROOT not in sys.path:
    sys.path.insert(0, EXT_ROOT)

from pyrevit import script, forms  # noqa: E402

from revit_mcp import selftest_runtime  # noqa: E402

output = script.get_output()
output.print_md("## RVTSS self-test\nRunning on a copy of `tests/test.rvt` ...")

if not forms.alert("Run the RVTSS self-test?\n\nA copy of the bundled test model will be opened and "
                   "modified, and test families are written to %TEMP%\\RVTSS_live.",
                   ok=False, yes=True, no=True):
    script.exit()

report, json_path, md_path = selftest_runtime.run(__revit__, log=lambda m: output.print_md("`%s`" % m))  # noqa: F821
s = report["summary"]
output.print_md("**{} passed, {} failed, {} skipped** in {} s".format(s["pass"], s["fail"], s["skip"],
                                                                        report["duration_s"]))
output.print_md("Report: `{}`".format(md_path))
try:
    os.startfile(md_path)
except Exception:
    pass
