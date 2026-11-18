namespace RvtssHost.Modules;

/// <summary>Helpers shared by the family editor route modules: port of revit_mcp/family_utils.py.</summary>
public static class FamilyUtils
{
    public static readonly (string kind, string cls)[] FormClasses =
    {
        ("extrusion", "Extrusion"), ("blend", "Blend"), ("revolution", "Revolution"),
        ("sweep", "Sweep"), ("swept_blend", "SweptBlend"),
    };

    /// <summary>getattr(DB, cls_name): the form classes of FormClasses.</summary>
    private static Type? FormClass(string clsName) => clsName switch
    {
        "Extrusion" => typeof(DB.Extrusion),
        "Blend" => typeof(DB.Blend),
        "Revolution" => typeof(DB.Revolution),
        "Sweep" => typeof(DB.Sweep),
        "SweptBlend" => typeof(DB.SweptBlend),
        _ => null,
    };

    public static DB.Family OwnerFamily(DB.Document doc) => doc.OwnerFamily;

    public static string FamilyName(DB.Document doc)
    {
        if (!string.IsNullOrEmpty(doc.PathName))
            return PyX.Splitext(PyX.Basename(doc.PathName)).root;
        return PyX.Splitext(Utils.NormalizeString(doc.Title)).root;
    }

    public static DB.Level? RefLevel(DB.Document doc)
    {
        var levels = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Level)).Cast<DB.Level>().ToList();
        if (levels.Count == 0)
            return null;
        foreach (var lv in levels)
        {
            if (Utils.NormalizeString(lv.Name).ToLowerInvariant().Contains("ref"))
                return lv;
        }
        return levels[0];
    }

    public static DB.ViewPlan PlanView(DB.Document doc)
    {
        var lv = RefLevel(doc);
        var plans = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ViewPlan)).Cast<DB.ViewPlan>()
            .Where(v => !v.IsTemplate && (v.ViewType == DB.ViewType.FloorPlan || v.ViewType == DB.ViewType.EngineeringPlan))
            .ToList();
        if (lv != null)
        {
            foreach (var v in plans)
            {
                try
                {
                    if (v.GenLevel != null && v.GenLevel.Id == lv.Id)
                        return v;
                }
                catch { continue; }
            }
        }
        if (plans.Count > 0)
            return plans[0];
        throw new RvtssError("This family template has no plan view", status: 409,
            hint: "Plan-based operations (dimensions, alignments of vertical faces) need a plan view.");
    }

    /// <summary>Front elevation looks towards +Y (view direction points to the viewer: -Y).</summary>
    public static DB.View ElevationView(DB.Document doc, string side = "front")
    {
        var wanted = side switch
        {
            "front" => new DB.XYZ(0, -1, 0),
            "back" => new DB.XYZ(0, 1, 0),
            "left" => new DB.XYZ(-1, 0, 0),
            "right" => new DB.XYZ(1, 0, 0),
            _ => throw new KeyNotFoundException("'" + side + "'"),
        };
        var elevs = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).Cast<DB.View>()
            .Where(v => !v.IsTemplate && v.ViewType == DB.ViewType.Elevation).ToList();
        foreach (var v in elevs)
        {
            try
            {
                if (v.ViewDirection.IsAlmostEqualTo(wanted))
                    return v;
            }
            catch { continue; }
        }
        foreach (var v in elevs)
        {
            if (Utils.NormalizeString(v.Name).ToLowerInvariant() == side)
                return v;
        }
        if (elevs.Count > 0)
            return elevs[0];
        throw new RvtssError("This family template has no elevation view", status: 409);
    }

    public static List<DB.ReferencePlane> ReferencePlanes(DB.Document doc) =>
        new DB.FilteredElementCollector(doc).OfClass(typeof(DB.ReferencePlane)).Cast<DB.ReferencePlane>().ToList();

    public static string PlaneOrientation(DB.ReferencePlane rp)
    {
        var n = rp.Normal;
        if (Math.Abs(n.X) > 0.999)
            return "x";
        if (Math.Abs(n.Y) > 0.999)
            return "y";
        if (Math.Abs(n.Z) > 0.999)
            return "z";
        return "skew";
    }

    /// <summary>Signed position of an axis-aligned plane along its normal axis (internal units).</summary>
    public static double? PlaneOffset(DB.ReferencePlane rp)
    {
        var o = PlaneOrientation(rp);
        var p = rp.BubbleEnd;
        return o switch { "x" => p.X, "y" => p.Y, "z" => p.Z, _ => null };
    }

    /// <summary>Reference plane by name, or 'Ref. Level' / 'level' returning the Level.</summary>
    public static DB.Element? FindRefPlane(DB.Document doc, object? name, bool required = true)
    {
        if (name == null)
            return null;
        var low = Utils.NormalizeString(name).ToLowerInvariant();
        if (low == "ref. level" || low == "ref level" || low == "level" || low == "reference level")
        {
            var lv = RefLevel(doc);
            if (lv != null)
                return lv;
        }
        var planes = ReferencePlanes(doc);
        foreach (var rp in planes)
        {
            if (Utils.NormalizeString(rp.Name).ToLowerInvariant() == low)
                return rp;
        }
        // isinstance(name, int) is also true for a Python bool
        if (Py.IsInt(name) || name is bool || IsDigit(Py.Str(name)))
        {
            var e = doc.GetElement(Compat.MakeId(Py.ToInt(name)));
            if (e is DB.ReferencePlane || e is DB.Level)
                return e;
        }
        if (required)
            throw Core.NotFound("Reference plane", name, planes.Select(rp => (string?)rp.Name).Concat(new string?[] { "Ref. Level" }));
        return null;
    }

    public static DB.Reference DatumReference(DB.Element datum) =>
        datum is DB.Level level ? level.GetPlaneReference() : ((DB.ReferencePlane)datum).GetReference();

    public static string DatumOrientation(DB.Element datum) =>
        datum is DB.Level ? "z" : PlaneOrientation((DB.ReferencePlane)datum);

    public static double? DatumOffset(DB.Element datum) =>
        datum is DB.Level level ? level.Elevation : PlaneOffset((DB.ReferencePlane)datum);

    public static readonly string[] IsReferenceValues =
    {
        "NotAReference", "Left", "CenterLeftRight", "Right", "Front", "CenterFrontBack",
        "Back", "Bottom", "CenterElevation", "Top", "StrongReference", "WeakReference",
    };

    public static string? IsReferenceLabel(DB.ReferencePlane rp)
    {
        try
        {
            var p = rp.get_Parameter(DB.BuiltInParameter.ELEM_REFERENCE_NAME);
            if (p != null)
                return Utils.NormalizeString(p.AsValueString() ?? "");
        }
        catch { /* no label */ }
        return null;
    }

    /// <summary>Best effort: set the 'Is Reference' property of a reference plane.</summary>
    public static void SetIsReference(DB.ReferencePlane rp, object? value)
    {
        var member = Py.EnumOrNull<DB.FamilyInstanceReferenceType>(value as string);
        if (member == null)
            throw new RvtssError($"Unknown is_reference '{Py.Str(value)}'. Use one of: {string.Join(", ", IsReferenceValues)}");
        var p = rp.get_Parameter(DB.BuiltInParameter.ELEM_REFERENCE_NAME);
        if (p == null || p.IsReadOnly)
            throw new RvtssError("This reference plane's 'Is Reference' cannot be set");
        p.Set((int)member.Value);
    }

    public static Dict DescribeRefPlane(DB.ReferencePlane rp, string unit)
    {
        var o = PlaneOrientation(rp);
        var off = PlaneOffset(rp);
        return new Dict
        {
            ["id"] = Compat.IdInt(rp), ["name"] = Utils.NormalizeString(rp.Name), ["orientation"] = o,
            ["offset"] = off != null ? Units.FromInternal(off.Value, unit, 3) : null,
            ["is_reference"] = IsReferenceLabel(rp),
        };
    }

    public static List<(string kind, DB.GenericForm f)> Forms(DB.Document doc)
    {
        var o = new List<(string kind, DB.GenericForm f)>();
        foreach (var (kind, clsName) in FormClasses)
        {
            var cls = FormClass(clsName);
            if (cls == null)
                continue;
            foreach (var f in new DB.FilteredElementCollector(doc).OfClass(cls))
                o.Add((kind, (DB.GenericForm)f));
        }
        return o;
    }

    private static readonly (string bip, string label)[] FormAssociations =
    {
        ("MATERIAL_ID_PARAM", "material"), ("IS_VISIBLE_PARAM", "visible"),
        ("EXTRUSION_END_PARAM", "extrusion_end"), ("EXTRUSION_START_PARAM", "extrusion_start"),
    };

    public static Dict DescribeForm(DB.Document doc, string kind, DB.GenericForm f, string unit, DB.FamilyManager? fm = null)
    {
        var d = new Dict { ["id"] = Compat.IdInt(f), ["kind"] = kind, ["solid"] = f.IsSolid };
        try { d["subcategory"] = f.Subcategory != null ? Utils.NormalizeString(f.Subcategory.Name) : null; }
        catch { /* not available */ }
        try
        {
            var vis = f.GetVisibility();
            d["visibility"] = new Dict
            {
                ["coarse"] = vis.IsShownInCoarse, ["medium"] = vis.IsShownInMedium, ["fine"] = vis.IsShownInFine,
            };
        }
        catch { /* not available */ }
        var bb = f.get_BoundingBox(null);
        if (bb != null)
            d["size"] = new Lst
            {
                Units.FromInternal(bb.Max.X - bb.Min.X, unit, 2), Units.FromInternal(bb.Max.Y - bb.Min.Y, unit, 2),
                Units.FromInternal(bb.Max.Z - bb.Min.Z, unit, 2),
            };
        if (fm != null)
        {
            var assoc = new Dict();
            foreach (var (bip, label) in FormAssociations)
            {
                try
                {
                    var p = f.get_Parameter((DB.BuiltInParameter)Enum.Parse(typeof(DB.BuiltInParameter), bip));
                    if (p == null)
                        continue;
                    var fp = fm.GetAssociatedFamilyParameter(p);
                    if (fp != null)
                        assoc[label] = Utils.NormalizeString(fp.Definition.Name);
                }
                catch { continue; }
            }
            if (assoc.Count > 0)
                d["associated_parameters"] = assoc;
        }
        if (kind == "extrusion")
        {
            try
            {
                var ext = (DB.Extrusion)f;
                d["start"] = Units.FromInternal(ext.StartOffset, unit, 3);
                d["end"] = Units.FromInternal(ext.EndOffset, unit, 3);
            }
            catch { /* not available */ }
        }
        return d;
    }

    /// <summary>{family parameter name: [dimension ids]}</summary>
    public static Dict LabeledDimensions(DB.Document doc)
    {
        var o = new Dict();
        foreach (var e in new DB.FilteredElementCollector(doc).OfClass(typeof(DB.Dimension)))
        {
            var dim = (DB.Dimension)e;
            DB.FamilyParameter? lbl;
            try { lbl = dim.FamilyLabel; }
            catch { lbl = null; }
            if (lbl != null)
                ((Lst)o.SetDefault(Utils.NormalizeString(lbl.Definition.Name), new Lst())!).Add(Compat.IdInt(dim));
        }
        return o;
    }

    public static Dict DescribeDimension(DB.Dimension dim, string unit)
    {
        var d = new Dict { ["id"] = Compat.IdInt(dim) };
        try { d["label"] = dim.FamilyLabel != null ? Utils.NormalizeString(dim.FamilyLabel.Definition.Name) : null; }
        catch { d["label"] = null; }
        try
        {
            var v = dim.Value;
            d["value"] = v != null ? Units.FromInternal(v.Value, unit, 3) : null;
        }
        catch { /* multi-segment dimensions have no single value */ }
        try
        {
            d["references"] = (long)dim.References.Size;
            d["segments"] = (long)dim.NumberOfSegments;
            d["locked"] = dim.IsLocked;
        }
        catch { /* not available */ }
        try { d["equality"] = dim.AreSegmentsEqual; }
        catch { /* not available */ }
        try { d["view"] = dim.View != null ? Utils.NormalizeString(dim.View.Name) : null; }
        catch { /* not available */ }
        return d;
    }

    public static Dict FamilyParamInfo(DB.Document doc, DB.FamilyManager fm, DB.FamilyParameter fp, string unit = "mm", Dict? labels = null)
    {
        var (spec, kind) = Compat.DefinitionSpec(fp.Definition);
        var name = Utils.NormalizeString(fp.Definition.Name);
        var d = new Dict
        {
            ["name"] = name,
            ["id"] = Compat.IdInt(fp.Id),
            ["instance"] = fp.IsInstance,
            ["spec"] = spec,
            ["group"] = Compat.DefinitionGroup(fp.Definition),
            ["shared"] = fp.IsShared,
            ["formula"] = string.IsNullOrEmpty(fp.Formula) ? null : fp.Formula,
            ["reporting"] = fp.IsReporting,
            ["read_only"] = fp.IsReadOnly,
            ["associated_element_parameters"] = (long)fp.AssociatedParameters.Size,
        };
        if (fp.IsShared)
        {
            try { d["guid"] = fp.GUID.ToString(); }
            catch { /* not available */ }
        }
        if (labels != null)
            d["labels_dimensions"] = (long)PyX.Len(labels.Get(name));
        try
        {
            if (fm.CurrentType != null)
                d["current_value"] = ParamsUtil.FamilyTypeValue(fm, fm.CurrentType, fp, unit);
        }
        catch { /* no value */ }
        if (kind == "length" || kind == "area" || kind == "volume")
            d["unit"] = Units.LengthUnitFor(kind, unit);
        else if (kind == "angle")
            d["unit"] = "deg";
        try
        {
            // only internal definitions have a BuiltInParameter
            if (fp.Definition is DB.InternalDefinition internalDefinition)
            {
                var bip = internalDefinition.BuiltInParameter;
                if (bip != DB.BuiltInParameter.INVALID)
                    d["builtin"] = bip.ToString();
            }
        }
        catch { /* not available */ }
        return d;
    }

    public static bool IsBuiltin(DB.FamilyParameter fp)
    {
        try
        {
            return fp.Definition is DB.InternalDefinition internalDefinition
                   && internalDefinition.BuiltInParameter != DB.BuiltInParameter.INVALID;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// User parameters plus built-in parameters that drive the family.
    ///
    /// Door/window templates expose Width, Height, Thickness... as *built-in* family
    /// parameters, so filtering out every built-in would hide the most important
    /// ones. Only built-in text/identity data (Type Mark, Keynote, URL, ...) is noise.
    /// </summary>
    public static bool IsRelevant(DB.FamilyParameter fp, bool includeAllBuiltin = false)
    {
        if (includeAllBuiltin || !IsBuiltin(fp))
            return true;
        if (fp.StorageType == DB.StorageType.String)
            return false;
        var group = (Compat.DefinitionGroup(fp.Definition) ?? "").ToLowerInvariant();
        return !group.Contains("identity") && !group.Contains("ifc");
    }

    /// <summary>Families without types cannot hold parameter values; create one if needed.</summary>
    public static DB.FamilyType EnsureCurrentType(DB.FamilyManager fm, string defaultName = "Default")
    {
        if (fm.CurrentType == null)
            fm.NewType(defaultName);
        return fm.CurrentType!;
    }

    public static DB.FamilyType FindFamilyType(DB.FamilyManager fm, object? name)
    {
        var low = Py.Truthy(name) ? Py.Str(name).ToLowerInvariant() : "";
        foreach (DB.FamilyType t in fm.Types)
        {
            var n = Utils.NormalizeString(t.Name);
            if ((name is string s && n == s) || n.ToLowerInvariant() == low)
                return t;
        }
        throw Core.NotFound("Family type", name, fm.Types.Cast<DB.FamilyType>().Select(t => (string?)Utils.NormalizeString(t.Name)));
    }

    public static List<DB.PlanarFace> SolidFaces(DB.Element form)
    {
        var opt = new DB.Options { ComputeReferences = true, IncludeNonVisibleObjects = true };
        var geom = form.get_Geometry(opt);
        var faces = new List<DB.PlanarFace>();
        if (geom == null)
            return faces;
        foreach (var obj in geom)
        {
            if (obj is DB.Solid solid && solid.Faces.Size > 0)
            {
                foreach (DB.Face f in solid.Faces)
                {
                    if (f is DB.PlanarFace pf)
                        faces.Add(pf);
                }
            }
        }
        return faces;
    }

    public static (double[] mins, double[] maxs)? CombinedBbox(DB.Document doc, bool solidsOnly = true)
    {
        double[]? mins = null, maxs = null;
        foreach (var (_, f) in Forms(doc))
        {
            if (solidsOnly && !f.IsSolid)
                continue;
            var bb = f.get_BoundingBox(null);
            if (bb == null)
                continue;
            if (mins == null || maxs == null)
            {
                mins = new[] { bb.Min.X, bb.Min.Y, bb.Min.Z };
                maxs = new[] { bb.Max.X, bb.Max.Y, bb.Max.Z };
            }
            else
            {
                mins = new[] { Math.Min(mins[0], bb.Min.X), Math.Min(mins[1], bb.Min.Y), Math.Min(mins[2], bb.Min.Z) };
                maxs = new[] { Math.Max(maxs[0], bb.Max.X), Math.Max(maxs[1], bb.Max.Y), Math.Max(maxs[2], bb.Max.Z) };
            }
        }
        if (mins == null || maxs == null)
            return null;
        return (mins, maxs);
    }

    // ------------------------------------------------------- porting helpers
    // Not in family_utils.py: small pieces of Python behaviour the three family route modules share.

    /// <summary>str.isdigit()</summary>
    internal static bool IsDigit(string s) => s.Length > 0 && s.All(char.IsDigit);

    /// <summary>A request list item that the Python code uses as a dict (item.get(...)).</summary>
    internal static Dict AsItem(object? item) =>
        item as Dict ?? throw new FormatException("'" + Py.TypeName(item) + "' object has no attribute 'get'");

    /// <summary>d[key] with Python's KeyError text.</summary>
    internal static object? Req(Dict d, string key) =>
        d.TryGetValue(key, out var v) ? v : throw new KeyNotFoundException("'" + key + "'");

    /// <summary>A request "unit" value for the unit-taking helpers: null stays null.</summary>
    internal static string? UnitOf(object? unit) => unit == null ? null : Py.Str(unit);

    /// <summary>normalize_string(text_type(e))</summary>
    internal static string ErrText(Exception e) => Utils.NormalizeString(e.Message);

    /// <summary>os.path.exists</summary>
    internal static bool PathExists(string path) => File.Exists(path) || Directory.Exists(path);

    /// <summary>os.path.dirname (ntpath).</summary>
    internal static string Dirname(string p)
    {
        var drive = p.Length >= 2 && p[1] == ':' ? p.Substring(0, 2) : "";
        var rest = p.Substring(drive.Length);
        var i = Math.Max(rest.LastIndexOf('\\'), rest.LastIndexOf('/')) + 1;
        var head = rest.Substring(0, i);
        var stripped = head.TrimEnd('\\', '/');
        return drive + (stripped.Length > 0 ? stripped : head);
    }

    /// <summary>os.path.normcase(os.path.abspath(path))</summary>
    internal static string NormCasePath(string path)
    {
        string full;
        try { full = Path.GetFullPath(path); }
        catch { full = path; } // cloud model paths are not file system paths
        return full.Replace('/', '\\').ToLowerInvariant();
    }

    /// <summary>os.path.relpath(path, start) (ntpath).</summary>
    internal static string Relpath(string path, string start)
    {
        var p = Path.GetFullPath(path).TrimEnd('\\').Split(new[] { '\\' });
        var s = Path.GetFullPath(start).TrimEnd('\\').Split(new[] { '\\' });
        if (!string.Equals(p[0], s[0], StringComparison.OrdinalIgnoreCase))
            throw new FormatException("path is on mount '" + p[0] + "', start on mount '" + s[0] + "'");
        var i = 0;
        while (i < p.Length && i < s.Length && string.Equals(p[i], s[i], StringComparison.OrdinalIgnoreCase))
            i++;
        var parts = Enumerable.Repeat("..", s.Length - i).Concat(p.Skip(i)).ToList();
        return parts.Count == 0 ? "." : string.Join("\\", parts);
    }
}
