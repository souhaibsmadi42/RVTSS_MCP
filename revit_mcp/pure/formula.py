# -*- coding: utf-8 -*-
"""Static analysis of Revit family formulas.

This is a pre-check only: Revit's FamilyManager.SetFormula (run inside a
rolled-back transaction) is the authoritative validator. The analysis here
finds parameter references, references to unknown names and dependency
cycles across a whole family, which Revit only reports one formula at a time.
"""
import re

FUNCTIONS = set([
    "if", "and", "or", "not", "sin", "cos", "tan", "asin", "acos", "atan",
    "exp", "abs", "sqrt", "round", "roundup", "rounddown", "log", "ln", "pi",
    "size_lookup", "e",
])
UNIT_WORDS = set([
    "mm", "cm", "m", "ft", "in", "deg", "rad", "sf", "sm", "m2", "m3", "ft2", "ft3",
    "mm2", "mm3", "cm2", "cm3", "kg", "n", "kn", "pa", "kpa", "w", "kw", "l", "s",
    "yes", "no", "true", "false", "degree", "degrees",
])

_STRING = re.compile(r'"[^"]*"')


def _strip_strings(formula):
    return _STRING.sub(" ", formula or "")


def references(formula, known_names):
    """Return the known parameter names referenced by a formula.

    Parameter names may contain spaces and symbols, so matching is done
    longest-name-first against the list of known names.
    """
    text = _strip_strings(formula)
    found = []
    for name in sorted(known_names, key=len, reverse=True):
        if not name:
            continue
        pat = r"(?<![\w])" + re.escape(name) + r"(?![\w])"
        if re.search(pat, text):
            found.append(name)
            text = re.sub(pat, " ", text)
    return found


def unknown_identifiers(formula, known_names):
    """Words in a formula that are not known parameters, functions, units or numbers."""
    text = _strip_strings(formula)
    for name in sorted(known_names, key=len, reverse=True):
        if name:
            text = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])", " ", text)
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text)
    out = []
    for w in words:
        lw = w.lower()
        if lw in FUNCTIONS or lw in UNIT_WORDS:
            continue
        if w not in out:
            out.append(w)
    return out


def check_balance(formula):
    depth = 0
    for ch in _strip_strings(formula):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return "Unbalanced ')'"
    if depth:
        return "Missing ')'"
    if (formula or "").count('"') % 2:
        return "Unterminated string literal"
    return None


def find_cycles(formulas, known_names):
    """formulas: {param_name: formula}. Returns list of cycles (lists of names)."""
    graph = {}
    for name, f in formulas.items():
        if f:
            graph[name] = [r for r in references(f, known_names) if r != name]
            if name in references(f, known_names):
                graph[name].append(name)
    cycles = []
    state = {}
    stack = []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if state.get(m) == 1:
                cyc = stack[stack.index(m):] + [m]
                key = tuple(sorted(set(cyc)))
                if key not in [tuple(sorted(set(c))) for c in cycles]:
                    cycles.append(cyc)
            elif not state.get(m):
                visit(m)
        stack.pop()
        state[n] = 2

    for n in list(graph):
        if not state.get(n):
            visit(n)
    return cycles


def analyse(formulas, known_names):
    """Full-family analysis. Returns a list of issues."""
    issues = []
    for name, f in sorted(formulas.items()):
        if not f:
            continue
        bal = check_balance(f)
        if bal:
            issues.append({"parameter": name, "severity": "error", "issue": bal, "formula": f})
        unknown = unknown_identifiers(f, known_names)
        if unknown:
            issues.append({"parameter": name, "severity": "warning",
                           "issue": "Formula references unknown names: %s" % ", ".join(unknown),
                           "formula": f})
    for cyc in find_cycles(formulas, known_names):
        issues.append({"parameter": cyc[0], "severity": "error",
                       "issue": "Circular formula reference: %s" % " -> ".join(cyc)})
    return issues
