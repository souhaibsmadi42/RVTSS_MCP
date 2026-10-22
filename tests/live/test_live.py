# -*- coding: utf-8 -*-
"""pytest entry point for the live smoke run (skipped when Revit is not reachable).

    uv run --extra test pytest tests/live -s
"""
import os

import httpx
import pytest

from tests.live.run_live import main

BASE = "http://%s:%s/%s" % (os.environ.get("REVIT_HOST", "127.0.0.1"), os.environ.get("REVIT_PORT", "48884"),
                            os.environ.get("REVIT_API_NAME", "revit_mcp"))


def _reachable():
    try:
        return httpx.get(BASE + "/status/", timeout=3).status_code < 500
    except Exception:
        return False


@pytest.mark.live
@pytest.mark.skipif(not _reachable(), reason="Revit / pyRevit Routes not reachable at " + BASE)
def test_live_smoke(tmp_path):
    assert main(["--out", str(tmp_path)]) == 0, (tmp_path / "rvtss_live_report.md").read_text(encoding="utf-8")
