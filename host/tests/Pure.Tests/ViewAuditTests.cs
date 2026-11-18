namespace RvtssHost.Tests;

public static class ViewAuditTests
{
    public static void Run(T t)
    {
        var data = LaneC.Load(t, "view_audit");
        LaneC.RunCases(t, data, (fn, a) =>
        {
            if (fn != "audit")
                throw new InvalidOperationException("no such function " + fn);
            Lst views = LaneC.L(a[0]), sheets = LaneC.L(a[1]);
            var boxes = a[2] as Lst;
            if (!LaneC.Has(a, 3)) return ViewAudit.Audit(views, sheets, boxes);
            if (!LaneC.Has(a, 4)) return ViewAudit.Audit(views, sheets, boxes, a[3] as Lst);
            return ViewAudit.Audit(views, sheets, boxes, a[3] as Lst, a[4] as Lst);
        });

        // the route passes typed collections: a set of ids and a list of view type names
        var views2 = new List<Dict>
        {
            new Dict { ["id"] = 1L, ["name"] = "Plan", ["view_type"] = "FloorPlan", ["on_sheet"] = true, ["scope_box_id"] = 50L },
        };
        var boxes2 = new List<Dict>
        {
            new Dict { ["id"] = 50L, ["name"] = "A" }, new Dict { ["id"] = 51L, ["name"] = "B" }, new Dict { ["id"] = 52L, ["name"] = "C" },
        };
        var res = ViewAudit.Audit(views2, new List<Dict>(), boxes2, new HashSet<long> { 51 }, new List<string> { "FloorPlan" });
        t.Eq("typed inputs", new Lst { new Lst { 1L }, new Lst { 52L } }, res.Select(f => f["element_ids"]).ToList());
    }
}
