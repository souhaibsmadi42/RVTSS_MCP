namespace RvtssHost.Pure;

/// <summary>
/// View, view-template, sheet and scope-box audit on plain data (filled by revit_mcp/qc.py).
///
/// views:       [{"id", "name", "view_type", "is_template", "template_id", "on_sheet", "scope_box_id",
///                "is_dependent", "printable"}]
/// sheets:      [{"id", "number", "name", "view_count", "is_placeholder"}]
/// scope_boxes: [{"id", "name"}]
/// datum_scope_box_ids: scope boxes used by grids / levels / reference planes
/// </summary>
public static class ViewAudit
{
    private static Dict Rec(object? r) => r as Dict ?? throw new InvalidCastException("record must be an object");

    private static List<Dict> Recs(IEnumerable<object?>? items) =>
        items == null ? new List<Dict>() : items.Select(Rec).ToList();

    private static Lst Field(IEnumerable<Dict> rows, string key) => new Lst(rows.Select(r => PyX.Item(r, key)));

    private static Lst Names(List<Dict> rows) => Field(PyX.Head(rows, 15), "name");

    public static List<Dict> Audit(IEnumerable<object?> views, IEnumerable<object?> sheets, IEnumerable<object?>? scopeBoxes,
        System.Collections.IEnumerable? datumScopeBoxIds = null, System.Collections.IEnumerable? requireTemplateTypes = null)
    {
        var res = new List<Dict>();
        var all = Recs(views);
        var templates = all.Where(v => Py.Truthy(v.Get("is_template"))).ToList();
        var real = all.Where(v => !Py.Truthy(v.Get("is_template"))).ToList();
        var printable = real.Where(v => Py.Truthy(v.Get("printable", true))).ToList();

        var kindList = PyX.Items(requireTemplateTypes);
        var kinds = kindList.Count > 0 ? new HashSet<object?>(kindList, PyX.KeyComparer.Instance) : null;
        var noTemplate = printable.Where(v => !Py.Truthy(v.Get("template_id"))
                                              && (kinds == null || kinds.Contains(v.Get("view_type")))).ToList();
        if (noTemplate.Count > 0)
        {
            var byType = new Dict();
            foreach (var v in noTemplate)
            {
                // a None key is "null" once the response is JSON
                var vt = v.Get("view_type");
                var key = vt == null ? "null" : PyX.Fmt(vt);
                byType[key] = Py.ToInt(byType.Get(key, 0L)) + 1;
            }
            res.Add(Rules.Finding("view_audit", "warning", noTemplate.Count + " views have no view template",
                Field(noTemplate, "id"),
                recommendation: "Assign the project's view templates (view_graphics / view template).",
                extra: new Dict { ["by_view_type"] = byType, ["examples"] = Names(noTemplate) }));
        }

        var used = new HashSet<object?>(real.Select(v => v.Get("template_id")).Where(Py.Truthy), PyX.KeyComparer.Instance);
        var unused = templates.Where(t => !used.Contains(PyX.Item(t, "id"))).ToList();
        if (unused.Count > 0)
            res.Add(Rules.Finding("view_audit", "info", unused.Count + " view templates are not used by any view",
                Field(unused, "id"),
                recommendation: "Delete unused templates after checking the office standard.",
                extra: new Dict { ["examples"] = Names(unused) }));

        var empty = Recs(sheets).Where(s => !Py.Truthy(s.Get("is_placeholder")) && !Py.Truthy(s.Get("view_count"))).ToList();
        if (empty.Count > 0)
            res.Add(Rules.Finding("view_audit", "warning", empty.Count + " sheets have no views",
                Field(empty, "id"),
                recommendation: "Place views or delete the empty sheets.",
                extra: new Dict
                {
                    ["examples"] = new Lst(PyX.Head(empty, 15)
                        .Select(s => (object?)(PyX.Fmt(s.Get("number")) + " - " + PyX.Fmt(s.Get("name"))))),
                }));

        var offSheet = printable.Where(v => !Py.Truthy(v.Get("on_sheet")) && !Py.Truthy(v.Get("is_dependent"))).ToList();
        if (offSheet.Count > 0)
            res.Add(Rules.Finding("view_audit", "info", offSheet.Count + " views are not placed on any sheet",
                Field(offSheet, "id"),
                recommendation: "Place them on sheets or delete working views before issue.",
                extra: new Dict { ["examples"] = Names(offSheet) }));

        var names = new Dictionary<string, List<Dict>>(StringComparer.Ordinal);
        var order = new List<string>();
        foreach (var v in real)
        {
            var key = Py.Str(Py.Truthy(v.Get("name")) ? v.Get("name") : "").Trim().ToLowerInvariant();
            if (!names.TryGetValue(key, out var vs))
            {
                names[key] = vs = new List<Dict>();
                order.Add(key);
            }
            vs.Add(v);
        }
        var dups = order.Where(k => k.Length > 0 && names[k].Count > 1).Select(k => names[k]).ToList();
        if (dups.Count > 0)
        {
            var ids = Field(dups.SelectMany(vs => vs), "id");
            res.Add(Rules.Finding("view_audit", "warning", dups.Count + " view names are used by more than one view",
                ids,
                recommendation: "Rename so view names are unique across view types (e.g. add 'RCP').",
                extra: new Dict
                {
                    ["examples"] = new Lst(PyX.Head(dups, 15).Select(vs => (object?)(
                        PyX.Fmt(PyX.Item(vs[0], "name")) + " (" + string.Join(", ", vs.Select(v => Py.Str(v.Get("view_type")))
                            .Distinct().OrderBy(x => x, StringComparer.Ordinal)) + ")"))),
                }));
        }

        var boxes = Recs(scopeBoxes);
        if (boxes.Count > 0)
        {
            var usedBoxes = new HashSet<object?>(all.Select(v => v.Get("scope_box_id")).Where(Py.Truthy), PyX.KeyComparer.Instance);
            foreach (var id in PyX.Items(datumScopeBoxIds))
                usedBoxes.Add(id);
            var idle = boxes.Where(b => !usedBoxes.Contains(PyX.Item(b, "id"))).ToList();
            if (idle.Count > 0)
                res.Add(Rules.Finding("view_audit", "info", idle.Count + " scope boxes are not used by views or datums",
                    Field(idle, "id"),
                    recommendation: "Delete unused scope boxes.",
                    extra: new Dict { ["examples"] = Names(idle) }));
        }
        return res;
    }
}
