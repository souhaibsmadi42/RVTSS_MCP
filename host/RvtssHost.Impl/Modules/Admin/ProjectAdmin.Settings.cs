namespace RvtssHost.Modules;

// Project settings: information, units, starting view, location (project_admin.py, "project settings").
public static partial class ProjectAdmin
{
    private static readonly string[] InfoProps =
    {
        "Name", "Number", "ClientName", "Address", "Status", "IssueDate", "Author", "BuildingName",
        "OrganizationName", "OrganizationDescription",
    };

    private static readonly Dictionary<string, string> InfoKeys = BuildInfoKeys();

    private static Dictionary<string, string> BuildInfoKeys()
    {
        var keys = new Dictionary<string, string>();
        foreach (var p in InfoProps)
            keys[p.ToLowerInvariant()] = p;
        keys["project_name"] = "Name";
        keys["project_number"] = "Number";
        keys["client_name"] = "ClientName";
        keys["project_address"] = "Address";
        keys["project_status"] = "Status";
        keys["issue_date"] = "IssueDate";
        keys["project_issue_date"] = "IssueDate";
        keys["building_name"] = "BuildingName";
        keys["organization_name"] = "OrganizationName";
        keys["organization_description"] = "OrganizationDescription";
        return keys;
    }

    private static readonly string[] UnitSpecKeys = { "length", "area", "volume", "angle" };

    private static readonly Dictionary<string, (string unit, string attr)[]> UnitIds = new()
    {
        ["length"] = new[]
        {
            ("mm", "Millimeters"), ("cm", "Centimeters"), ("m", "Meters"), ("ft", "Feet"), ("in", "Inches"),
            ("ft_in", "FeetFractionalInches"), ("m_cm", "MetersCentimeters"),
        },
        ["area"] = new[] { ("m2", "SquareMeters"), ("ft2", "SquareFeet"), ("mm2", "SquareMillimeters"), ("cm2", "SquareCentimeters") },
        ["volume"] = new[] { ("m3", "CubicMeters"), ("ft3", "CubicFeet"), ("l", "Liters"), ("mm3", "CubicMillimeters") },
        ["angle"] = new[] { ("deg", "Degrees"), ("rad", "Radians"), ("dms", "DegreesMinutes"), ("grad", "Gradians") },
    };

    private static DB.ForgeTypeId SpecOf(string key) => key switch
    {
        "length" => DB.SpecTypeId.Length,
        "area" => DB.SpecTypeId.Area,
        "volume" => DB.SpecTypeId.Volume,
        _ => DB.SpecTypeId.Angle,
    };

    /// <summary>getattr(DB.UnitTypeId, attr, None)</summary>
    private static DB.ForgeTypeId? UnitTypeIdOf(string attr) => attr switch
    {
        "Millimeters" => DB.UnitTypeId.Millimeters,
        "Centimeters" => DB.UnitTypeId.Centimeters,
        "Meters" => DB.UnitTypeId.Meters,
        "Feet" => DB.UnitTypeId.Feet,
        "Inches" => DB.UnitTypeId.Inches,
        "FeetFractionalInches" => DB.UnitTypeId.FeetFractionalInches,
        "MetersCentimeters" => DB.UnitTypeId.MetersCentimeters,
        "SquareMeters" => DB.UnitTypeId.SquareMeters,
        "SquareFeet" => DB.UnitTypeId.SquareFeet,
        "SquareMillimeters" => DB.UnitTypeId.SquareMillimeters,
        "SquareCentimeters" => DB.UnitTypeId.SquareCentimeters,
        "CubicMeters" => DB.UnitTypeId.CubicMeters,
        "CubicFeet" => DB.UnitTypeId.CubicFeet,
        "Liters" => DB.UnitTypeId.Liters,
        "CubicMillimeters" => DB.UnitTypeId.CubicMillimeters,
        "Degrees" => DB.UnitTypeId.Degrees,
        "Radians" => DB.UnitTypeId.Radians,
        "DegreesMinutes" => DB.UnitTypeId.DegreesMinutes,
        "Gradians" => DB.UnitTypeId.Gradians,
        _ => null,
    };

    /// <summary>Project units need ForgeTypeId units (Revit 2021+); every supported version has them.</summary>
    private static void ForgeUnits()
    {
    }

    private static Dict UnitsInfo(DB.Document doc)
    {
        ForgeUnits();
        var units = doc.GetUnits();
        var result = new Dict();
        foreach (var key in UnitSpecKeys)
        {
            try
            {
                var fo = units.GetFormatOptions(SpecOf(key));
                var typeId = fo.GetUnitTypeId().TypeId;
                string? shortName = null;
                foreach (var (name, attr) in UnitIds[key])
                {
                    var uid = UnitTypeIdOf(attr);
                    if (uid != null && uid.TypeId == typeId)
                        shortName = name;
                }
                result[key] = new Dict { ["unit"] = shortName, ["unit_type_id"] = typeId, ["rounding"] = fo.Accuracy };
            }
            catch (Exception e)
            {
                result[key] = new Dict { ["error"] = Utils.NormalizeString(e.Message) };
            }
        }
        return result;
    }

    private static string? InfoGet(DB.ProjectInfo pi, string prop) => prop switch
    {
        "Name" => pi.Name,
        "Number" => pi.Number,
        "ClientName" => pi.ClientName,
        "Address" => pi.Address,
        "Status" => pi.Status,
        "IssueDate" => pi.IssueDate,
        "Author" => pi.Author,
        "BuildingName" => pi.BuildingName,
        "OrganizationName" => pi.OrganizationName,
        "OrganizationDescription" => pi.OrganizationDescription,
        _ => null,
    };

    private static void InfoSet(DB.ProjectInfo pi, string prop, string value)
    {
        switch (prop)
        {
            case "Name": pi.Name = value; break;
            case "Number": pi.Number = value; break;
            case "ClientName": pi.ClientName = value; break;
            case "Address": pi.Address = value; break;
            case "Status": pi.Status = value; break;
            case "IssueDate": pi.IssueDate = value; break;
            case "Author": pi.Author = value; break;
            case "BuildingName": pi.BuildingName = value; break;
            case "OrganizationName": pi.OrganizationName = value; break;
            case "OrganizationDescription": pi.OrganizationDescription = value; break;
        }
    }

    private static Dict Info(DB.Document doc)
    {
        var pi = doc.ProjectInformation;
        var props = new Dict();
        foreach (var prop in InfoProps)
        {
            try { props[prop] = Utils.NormalizeString(InfoGet(pi, prop) ?? ""); }
            catch { /* property not readable */ }
        }
        var extra = new Dict();
        foreach (DB.Parameter p in pi.Parameters)
        {
            try
            {
                if (p.StorageType == DB.StorageType.String && !p.IsReadOnly)
                {
                    var name = Utils.NormalizeString(p.Definition.Name);
                    extra[name] = Utils.NormalizeString(p.AsString() ?? "");
                }
            }
            catch { continue; }
        }
        return new Dict { ["properties"] = props, ["text_parameters"] = extra };
    }

    private static Dict StartingView(DB.Document doc)
    {
        try
        {
            var svs = DB.StartingViewSettings.GetStartingViewSettings(doc);
            var v = Compat.IsValidId(svs.ViewId) ? doc.GetElement(svs.ViewId) : null;
            return new Dict
            {
                ["view_id"] = v != null ? v.Id.Value : null, ["view"] = v != null ? Utils.NormalizeString(v.Name) : null,
                ["last_opened"] = v == null,
            };
        }
        catch (Exception e)
        {
            return new Dict { ["error"] = Utils.NormalizeString(e.Message) };
        }
    }

    // math.degrees / math.radians as CPython computes them
    private static double Degrees(double radians) => radians * (180.0 / Math.PI);

    private static double Radians(double degrees) => degrees * (Math.PI / 180.0);

    private static Dict Location(DB.Document doc, string unit)
    {
        var result = new Dict();
        try
        {
            var site = doc.SiteLocation;
            var lat = Py.Round(Degrees(site.Latitude), 6);
            var lon = Py.Round(Degrees(site.Longitude), 6);
            var tz = site.TimeZone;
            result["latitude_deg"] = lat;
            result["longitude_deg"] = lon;
            result["time_zone"] = tz;
            try { result["place_name"] = Utils.NormalizeString(site.PlaceName ?? ""); }
            catch { /* no place name */ }
        }
        catch (Exception e)
        {
            result["site_error"] = Utils.NormalizeString(e.Message);
        }
        try
        {
            var loc = doc.ActiveProjectLocation;
            var pos = loc.GetProjectPosition(DB.XYZ.Zero);
            var projectLocation = Utils.NormalizeString(loc.Name);
            var eastWest = Units.FromInternal(pos.EastWest, unit, 3);
            var northSouth = Units.FromInternal(pos.NorthSouth, unit, 3);
            var elevation = Units.FromInternal(pos.Elevation, unit, 3);
            var angle = Py.Round(Degrees(pos.Angle), 6);
            result["project_location"] = projectLocation;
            result["east_west"] = eastWest;
            result["north_south"] = northSouth;
            result["elevation"] = elevation;
            result["angle_to_true_north_deg"] = angle;
            result["unit"] = unit;
        }
        catch (Exception e)
        {
            result["position_error"] = Utils.NormalizeString(e.Message);
        }
        return result;
    }

    public static Dict? ProjectSettings(Ctx ctx)
    {
        var doc = ctx.Doc;
        Core.RequireProject(doc);
        var action = Py.Str(ctx.Get("action", "get"));
        var dry = ctx.DryRun;
        if (action == "get")
        {
            var include = ctx.List("include");
            var wanted = include.Count > 0
                ? new HashSet<string>(include.OfType<string>())
                : new HashSet<string> { "info", "units", "starting_view", "location" };
            var result = new Dict();
            if (wanted.Contains("info"))
                result["info"] = Info(doc);
            if (wanted.Contains("units"))
            {
                try { result["units"] = UnitsInfo(doc); }
                catch (RvtssError e) { result["units"] = new Dict { ["error"] = e.Message }; }
            }
            if (wanted.Contains("starting_view"))
                result["starting_view"] = StartingView(doc);
            if (wanted.Contains("location"))
                result["location"] = Location(doc, ctx.Unit);
            return result;
        }
        if (action == "set_info")
        {
            var values = ctx.Get("values") as Dict;
            if (values == null || values.Count == 0)
                throw new RvtssError("'values' is required: {\"Number\": \"P-001\", \"Client Name\": \"...\"}");
            var pi = doc.ProjectInformation;

            Dict Run()
            {
                var changed = new Lst();
                var failed = new Lst();
                foreach (var kv in values)
                {
                    var key = kv.Key;
                    var value = kv.Value == null ? "" : Py.Str(kv.Value);
                    var low = key.Trim().ToLowerInvariant();
                    if (!InfoKeys.TryGetValue(low.Replace(" ", "_"), out var prop))
                        InfoKeys.TryGetValue(low.Replace(" ", ""), out prop);
                    try
                    {
                        string old;
                        if (prop != null)
                        {
                            old = Utils.NormalizeString(InfoGet(pi, prop) ?? "");
                            InfoSet(pi, prop, value);
                        }
                        else
                        {
                            var p = pi.LookupParameter(key);
                            if (p == null)
                                throw new RvtssError("no such project information parameter");
                            if (p.IsReadOnly)
                                throw new RvtssError("parameter is read-only");
                            if (p.StorageType != DB.StorageType.String)
                                throw new RvtssError("only text parameters can be set here; use set_parameters with "
                                                     + $"element id {pi.Id.Value}");
                            old = Utils.NormalizeString(p.AsString() ?? "");
                            p.Set(value);
                        }
                        changed.Add(new Dict { ["name"] = key, ["old"] = old, ["new"] = Utils.NormalizeString(value) });
                    }
                    catch (Exception e)
                    {
                        failed.Add(new Dict { ["name"] = key, ["error"] = e is RvtssError ? e.Message : Utils.NormalizeString(e.Message) });
                    }
                }
                if (failed.Count > 0 && ctx.Bool("atomic", true))
                    throw new RvtssError("Some project information values could not be set; nothing was changed")
                        .With("failed", failed)
                        .With("available", ((Dict)Info(doc)["text_parameters"]!).Keys.OrderBy(x => x, StringComparer.Ordinal).ToList());
                return new Dict { ["changed"] = changed, ["failed"] = failed };
            }

            var (res, fails) = Core.RunTransaction(doc, "Project information", Run, dry);
            return Core.CommitResult(res, fails, dry);
        }
        if (action == "set_units")
        {
            ForgeUnits();
            var specUnits = ctx.Get("units") as Dict;
            if (specUnits == null || specUnits.Count == 0)
                throw new RvtssError("'units' is required: {\"length\": {\"unit\": \"mm\", \"rounding\": 1}, ...}");
            var plan = new List<(string k, object? unitName, object? rounding)>();
            foreach (var kv in specUnits)
            {
                var k = kv.Key.ToLowerInvariant();
                if (!UnitIds.ContainsKey(k))
                    throw new RvtssError($"Unknown quantity '{kv.Key}': use {string.Join(", ", UnitSpecKeys.OrderBy(x => x, StringComparer.Ordinal))}");
                var value = kv.Value as Dict ?? new Dict { ["unit"] = kv.Value };
                var unitName = value.Get("unit");
                if (unitName != null && !(unitName is string un && UnitIds[k].Any(u => u.unit == un)))
                    throw new RvtssError($"Unknown {k} unit '{Py.Str(unitName)}': use "
                                         + string.Join(", ", UnitIds[k].Select(u => u.unit).OrderBy(x => x, StringComparer.Ordinal)));
                plan.Add((k, unitName, value.Get("rounding")));
            }
            var before = UnitsInfo(doc);

            Dict Run()
            {
                var units = doc.GetUnits();
                foreach (var (k, unitName, rounding) in plan)
                {
                    var spec = SpecOf(k);
                    var fo = units.GetFormatOptions(spec);
                    if (unitName != null)
                    {
                        var attr = UnitIds[k].First(u => u.unit == (string)unitName).attr;
                        var uid = UnitTypeIdOf(attr);
                        if (uid == null)
                            throw new RvtssError($"This Revit version has no unit '{Py.Str(unitName)}'", status: 501);
                        fo = new DB.FormatOptions(uid);
                    }
                    fo.UseDefault = false;
                    if (rounding != null)
                    {
                        var acc = Py.ToFloat(rounding);
                        bool valid;
                        try { valid = fo.IsValidAccuracy(acc); }
                        catch { valid = true; }
                        if (!valid)
                        {
                            var shown = Py.Truthy(unitName) ? Py.Str(unitName) : Py.Str((before.Get(k) as Dict)?.Get("unit"));
                            throw new RvtssError($"Rounding {Py.Str(rounding)} is not valid for {k} in {shown}",
                                hint: "Use a decimal step such as 1, 0.1, 0.01; fractional feet and inches use "
                                      + "fractions of an inch expressed in feet.");
                        }
                        fo.Accuracy = acc;
                    }
                    units.SetFormatOptions(spec, fo);
                }
                doc.SetUnits(units);
                return new Dict { ["units"] = UnitsInfo(doc) };
            }

            var (res, fails) = Core.RunTransaction(doc, "Project units", Run, dry);
            return Core.CommitResult(res, fails, dry, new Dict { ["before"] = before });
        }
        if (action == "set_starting_view")
        {
            var reference = ctx.Get("view");
            var svs = DB.StartingViewSettings.GetStartingViewSettings(doc);
            DB.ElementId target;
            string? name;
            if (reference == null || (reference is string rs && (rs == "" || rs == "none" || rs == "last_opened")))
            {
                target = DB.ElementId.InvalidElementId;
                name = null;
            }
            else
            {
                var v = Core.FindView(doc, reference, defaultActive: false, uidoc: ctx.UiDoc)!;
                bool acceptable;
                try { acceptable = svs.IsAcceptableStartingView(v.Id); }
                catch { acceptable = true; }
                if (!acceptable)
                    throw new RvtssError($"View '{Utils.NormalizeString(v.Name)}' cannot be a starting view", status: 409);
                target = v.Id;
                name = Utils.NormalizeString(v.Name);
            }
            var before = StartingView(doc);

            Dict Run()
            {
                svs.ViewId = target;
                return new Dict { ["starting_view"] = name, ["last_opened"] = name == null };
            }

            var (res, fails) = Core.RunTransaction(doc, "Starting view", Run, dry);
            return Core.CommitResult(res, fails, dry, new Dict { ["before"] = before });
        }
        if (action == "set_location")
        {
            var lat = ctx.Float("latitude");
            var lon = ctx.Float("longitude");
            var angle = ctx.Float("true_north_angle");
            var ew = ctx.Float("east_west");
            var ns = ctx.Float("north_south");
            var elev = ctx.Float("elevation");
            if (lat == null && lon == null && angle == null && ew == null && ns == null && elev == null)
                throw new RvtssError("Give latitude / longitude (degrees), true_north_angle (degrees) or east_west / "
                                     + "north_south / elevation (in `unit`)");
            if (lat != null && !(-90 <= lat && lat <= 90))
                throw new RvtssError("latitude must be between -90 and 90 degrees");
            if (lon != null && !(-180 <= lon && lon <= 180))
                throw new RvtssError("longitude must be between -180 and 180 degrees");
            var before = Location(doc, ctx.Unit);

            Dict Run()
            {
                if (lat != null || lon != null)
                {
                    var site = doc.SiteLocation;
                    if (lat != null)
                        site.Latitude = Radians(lat.Value);
                    if (lon != null)
                        site.Longitude = Radians(lon.Value);
                }
                if (angle != null || ew != null || ns != null || elev != null)
                {
                    var loc = doc.ActiveProjectLocation;
                    var pos = loc.GetProjectPosition(DB.XYZ.Zero);
                    var created = new DB.ProjectPosition(
                        ew != null ? Units.ToInternal(ew.Value, ctx.Unit) : pos.EastWest,
                        ns != null ? Units.ToInternal(ns.Value, ctx.Unit) : pos.NorthSouth,
                        elev != null ? Units.ToInternal(elev.Value, ctx.Unit) : pos.Elevation,
                        angle != null ? Radians(angle.Value) : pos.Angle);
                    loc.SetProjectPosition(DB.XYZ.Zero, created);
                }
                return new Dict { ["location"] = Location(doc, ctx.Unit) };
            }

            var (res, fails) = Core.RunTransaction(doc, "Project location", Run, dry);
            return Core.CommitResult(res, fails, dry, new Dict { ["before"] = before });
        }
        throw new RvtssError("action must be get, set_info, set_units, set_starting_view or set_location");
    }
}
