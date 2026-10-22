# -*- coding: utf-8 -*-
"""QC findings, severities and configurable naming/parameter rules.

Rule file (JSON, optional; default location %APPDATA%/RVTSS/qc_rules.json):
{
  "naming": {
    "views":    {"pattern": "^[A-Z]{2}-", "severity": "warning", "description": "..."},
    "sheets":   {"pattern": "^[A-Z]-\\d{3}$", "field": "number"},
    "families": {"pattern": "^[A-Z]{3}_"},
    "types":    {"pattern": "..."},
    "levels":   {"pattern": "..."},
    "parameters": {"pattern": "^[A-Z][A-Za-z0-9 ]+$"}
  },
  "required_parameters": [
    {"categories": ["Doors"], "parameters": ["Fire Rating", "Mark"], "severity": "error"}
  ],
  "sheet_parameters": ["Drawn By", "Checked By"]
}
"""
import re

SEVERITIES = ("info", "warning", "error", "critical")


def severity_rank(sev):
    try:
        return SEVERITIES.index(sev)
    except ValueError:
        return 1


def finding(check, severity, message, element_ids=None, recommendation=None, count=None,
            max_ids=50, **extra):
    ids = list(element_ids or [])
    f = {
        "check": check,
        "severity": severity if severity in SEVERITIES else "warning",
        "message": message,
        "count": count if count is not None else len(ids),
        "element_ids": ids[:max_ids],
    }
    if len(ids) > max_ids:
        f["element_ids_truncated"] = True
    if recommendation:
        f["recommendation"] = recommendation
    f.update(extra)
    return f


def summarize(findings):
    by_sev = dict((s, 0) for s in SEVERITIES)
    by_check = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
    worst = None
    for f in findings:
        if worst is None or severity_rank(f["severity"]) > severity_rank(worst):
            worst = f["severity"]
    return {"total_findings": len(findings), "by_severity": by_sev, "by_check": by_check,
            "worst_severity": worst}


def sort_findings(findings):
    return sorted(findings, key=lambda f: (-severity_rank(f["severity"]), -f.get("count", 0)))


def check_names(items, rule, check_name, label):
    """items: [(id, name)]; rule: {"pattern", "severity", "description"}."""
    pattern = rule.get("pattern")
    if not pattern:
        return []
    try:
        rx = re.compile(pattern)
    except re.error as ex:
        return [finding(check_name, "error", "Invalid naming pattern for %s: %s" % (label, ex))]
    bad = [(i, n) for i, n in items if not rx.search(n or "")]
    if not bad:
        return []
    return [finding(
        check_name, rule.get("severity", "warning"),
        "%d %s do not match naming pattern %s" % (len(bad), label, pattern),
        element_ids=[i for i, _ in bad],
        recommendation=rule.get("description") or "Rename to match the project naming standard (see batch_rename).",
        examples=[n for _, n in bad[:10]],
    )]


def check_duplicate_names(items, check_name, label):
    seen = {}
    for i, n in items:
        seen.setdefault((n or "").strip().lower(), []).append(i)
    dups = dict((k, v) for k, v in seen.items() if len(v) > 1 and k)
    if not dups:
        return []
    ids = [i for v in dups.values() for i in v]
    return [finding(check_name, "warning", "%d %s names are used more than once" % (len(dups), label),
                    element_ids=ids, examples=sorted(dups)[:10],
                    recommendation="Make names unique so schedules, tags and exports stay unambiguous.")]


def similar_names(names, threshold=0.92):
    """Detect near-duplicate names (e.g. 'Door 900' vs 'Door_900'). O(n^2) - capped by caller."""
    import difflib

    def norm(s):
        return re.sub(r"[\s_\-\.]+", "", (s or "").lower())

    out = []
    normed = [(n, norm(n)) for n in names]
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            a, b = normed[i][1], normed[j][1]
            if not a or not b:
                continue
            if a == b or difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
                out.append((normed[i][0], normed[j][0]))
    return out
