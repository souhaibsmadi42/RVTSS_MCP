using System.Text.RegularExpressions;

namespace RvtssHost.Pure;

/// <summary>
/// Family template (.rft) discovery and matching.
///
/// Template file names differ between Revit versions and content packs
/// ("Metric Door.rft", "M_Door.rft", "Door.rft"...), so matching is done on
/// normalised keywords rather than exact names.
/// </summary>
public static class Templates
{
    private static (string[] must, string[] mustNot) K(string[] must, params string[] mustNot) => (must, mustNot);

    private static string[] W(params string[] words) => words;

    /// <summary>kind -> (keywords that must all appear, keywords that must not appear)</summary>
    public static readonly Dictionary<string, (string[] must, string[] mustNot)> TemplateKinds = new()
    {
        ["generic_model"] = K(W("generic", "model"), "face", "wall", "ceiling", "floor", "roof", "line", "pattern", "adaptive", "two level", "annotation"),
        ["generic_model_face_based"] = K(W("generic", "model", "face"), "adaptive"),
        ["generic_model_wall_based"] = K(W("generic", "model", "wall"), "adaptive"),
        ["generic_model_floor_based"] = K(W("generic", "model", "floor")),
        ["generic_model_ceiling_based"] = K(W("generic", "model", "ceiling")),
        ["generic_model_line_based"] = K(W("generic", "model", "line")),
        ["generic_model_adaptive"] = K(W("generic", "model", "adaptive")),
        ["door"] = K(W("door"), "tag", "curtain", "panel", "elevation", "garage"),
        ["door_curtain_wall"] = K(W("door", "curtain"), "tag"),
        ["window"] = K(W("window"), "tag", "curtain", "elevation", "fixed"),
        ["window_curtain_wall"] = K(W("window", "curtain"), "tag"),
        ["furniture"] = K(W("furniture"), "system", "tag"),
        ["furniture_system"] = K(W("furniture", "system"), "tag"),
        ["casework"] = K(W("casework"), "tag", "wall based"),
        ["casework_wall_based"] = K(W("casework", "wall"), "tag"),
        ["plumbing_fixture"] = K(W("plumbing", "fixture"), "tag", "wall", "face"),
        ["lighting_fixture"] = K(W("lighting", "fixture"), "tag", "ceiling", "wall", "line", "face"),
        ["lighting_fixture_ceiling_based"] = K(W("lighting", "fixture", "ceiling"), "tag"),
        ["mechanical_equipment"] = K(W("mechanical", "equipment"), "tag", "wall", "face"),
        ["electrical_equipment"] = K(W("electrical", "equipment"), "tag", "wall", "face"),
        ["electrical_fixture"] = K(W("electrical", "fixture"), "tag", "wall", "face"),
        ["specialty_equipment"] = K(W("specialty", "equipment"), "tag", "wall"),
        ["column"] = K(W("column"), "structural", "tag", "curtain", "mullion"),
        ["structural_column"] = K(W("structural", "column"), "tag"),
        ["structural_framing"] = K(W("structural", "framing", "beam"), "tag", "complex"),
        ["structural_foundation"] = K(W("structural", "foundation"), "tag"),
        ["structural_stiffener"] = K(W("structural", "stiffener"), "tag"),
        ["structural_truss"] = K(W("structural", "truss"), "tag"),
        ["entourage"] = K(W("entourage")),
        ["planting"] = K(W("planting")),
        ["site"] = K(W("site")),
        ["parking"] = K(W("parking")),
        ["profile"] = K(W("profile"), "rail", "hosted", "mullion", "reveal", "stair", "door", "gutter", "fascia", "slab", "wall sweep"),
        ["profile_mullion"] = K(W("profile", "mullion")),
        ["profile_rail"] = K(W("profile", "rail")),
        ["profile_reveal"] = K(W("profile", "reveal")),
        ["profile_hosted"] = K(W("profile", "hosted")),
        ["detail_item"] = K(W("detail", "item"), "line"),
        ["detail_item_line_based"] = K(W("detail", "item", "line")),
        ["generic_annotation"] = K(W("generic", "annotation")),
        ["door_tag"] = K(W("door", "tag")),
        ["window_tag"] = K(W("window", "tag")),
        ["room_tag"] = K(W("room", "tag")),
        ["multi_category_tag"] = K(W("multi", "category", "tag")),
        ["title_block"] = K(W("titleblock")),
        ["rebar_shape"] = K(W("rebar", "shape")),
        ["mass"] = K(W("mass"), "adaptive"),
        ["railing_baluster"] = K(W("baluster"), "panel", "post"),
        ["ceiling_based_generic"] = K(W("generic", "model", "ceiling")),
    };

    public static readonly Dictionary<string, string> KindCategory = new()
    {
        ["generic_model"] = "OST_GenericModel",
        ["door"] = "OST_Doors", ["door_curtain_wall"] = "OST_Doors",
        ["window"] = "OST_Windows", ["window_curtain_wall"] = "OST_Windows",
        ["furniture"] = "OST_Furniture", ["furniture_system"] = "OST_FurnitureSystems",
        ["casework"] = "OST_Casework", ["casework_wall_based"] = "OST_Casework",
        ["plumbing_fixture"] = "OST_PlumbingFixtures",
        ["lighting_fixture"] = "OST_LightingFixtures", ["lighting_fixture_ceiling_based"] = "OST_LightingFixtures",
        ["mechanical_equipment"] = "OST_MechanicalEquipment",
        ["electrical_equipment"] = "OST_ElectricalEquipment",
        ["electrical_fixture"] = "OST_ElectricalFixtures",
        ["specialty_equipment"] = "OST_SpecialityEquipment",
        ["column"] = "OST_Columns", ["structural_column"] = "OST_StructuralColumns",
        ["structural_framing"] = "OST_StructuralFraming",
        ["structural_foundation"] = "OST_StructuralFoundation",
        ["entourage"] = "OST_Entourage", ["planting"] = "OST_Planting", ["site"] = "OST_Site",
        ["parking"] = "OST_Parking", ["detail_item"] = "OST_DetailComponents",
        ["title_block"] = "OST_TitleBlocks", ["mass"] = "OST_Mass",
    };

    public static readonly Dictionary<string, string[]> UnitSystemHints = new()
    {
        ["metric"] = new[] { "metric", "m_" },
        ["imperial"] = new[] { "imperial", "us " },
    };

    private static readonly Regex Seps = new(@"[\\/]", RegexOptions.CultureInvariant);
    private static readonly Regex Spaces = new(@"\s+", RegexOptions.CultureInvariant);

    /// <summary>Split on both separators: Windows paths must also work when tested on Linux.</summary>
    private static List<string> Parts(string? path) =>
        Seps.Split(path ?? "").Where(x => x.Length > 0).ToList();

    private static string Normalise(string? name)
    {
        var parts = Parts(name);
        var b = PyX.Splitext(parts.Count > 0 ? parts[parts.Count - 1] : "").root.ToLowerInvariant();
        b = b.Replace("_", " ").Replace("-", " ");
        b = Spaces.Replace(b, " ");
        return " " + b + " ";
    }

    private static bool ContainsWord(string text, string keyword)
    {
        // titleblock may be written as "title block"
        var kw = keyword.ToLowerInvariant();
        if (kw == "titleblock")
            return text.Replace(" ", "").IndexOf("titleblock", StringComparison.Ordinal) >= 0;
        return text.IndexOf(kw, StringComparison.Ordinal) >= 0;
    }

    /// <summary>Return a match score (>0 means usable) for a template path.</summary>
    public static double Score(string? path, string kind, string? unitSystem = null)
    {
        if (kind == null || !TemplateKinds.TryGetValue(kind, out var words))
            return 0;
        var text = Normalise(path);
        var parts = Parts(path);
        // Revit ships title blocks as "Titleblocks\A1 metric.rft": the folder name counts for the required words
        var folder = parts.Count > 1 ? Normalise(parts[parts.Count - 2]) : " ";
        if (!words.must.All(k => ContainsWord(text, k) || ContainsWord(folder, k)))
            return 0;
        if (words.mustNot.Any(k => ContainsWord(text, k)))
            return 0;
        var s = 10.0;
        // prefer shorter, more canonical names ("Metric Door.rft" over "Metric Door - Curtain...")
        s -= Math.Min(PyX.SplitWs(text).Count, 8) * 0.5;
        if (!string.IsNullOrEmpty(unitSystem))
        {
            var hints = UnitSystemHints.TryGetValue(unitSystem!, out var h) ? h : Array.Empty<string>();
            var other = UnitSystemHints.Where(kv => kv.Key != unitSystem).SelectMany(kv => kv.Value).ToList();
            var low = (parts.Count > 0 ? parts[parts.Count - 1] : "").ToLowerInvariant();
            if (hints.Any(x => low.IndexOf(x, StringComparison.Ordinal) >= 0))
                s += 3;
            else if (other.Any(x => low.IndexOf(x, StringComparison.Ordinal) >= 0))
                s -= 3;
        }
        return s;
    }

    /// <summary>Return candidate templates for a kind, best first.</summary>
    public static List<string> Match(IEnumerable<string> paths, string kind, string? unitSystem = null)
    {
        return paths.Select(p => (score: Score(p, kind, unitSystem), path: p))
            .Where(x => x.score > 0)
            .OrderBy(x => -x.score).ThenBy(x => x.path.Length)
            .Select(x => x.path).ToList();
    }

    public static List<string> FindTemplateFiles(IEnumerable<string?> dirs, long maxFiles = 5000)
    {
        var found = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var d in dirs)
        {
            if (string.IsNullOrEmpty(d) || !Directory.Exists(d))
                continue;
            if (Walk(d!, found, seen, maxFiles))
                return found;
        }
        return found;
    }

    /// <summary>os.walk order: the files of a folder, then its sub-folders. True when max_files is reached.</summary>
    private static bool Walk(string root, List<string> found, HashSet<string> seen, long maxFiles)
    {
        string[] files, dirs;
        try
        {
            // os.walk ignores folders it cannot list
            files = Directory.GetFiles(root);
            dirs = Directory.GetDirectories(root);
        }
        catch (Exception)
        {
            return false;
        }
        foreach (var file in files)
        {
            var f = Path.GetFileName(file);
            if (!f.ToLowerInvariant().EndsWith(".rft", StringComparison.Ordinal))
                continue;
            var full = PyX.Join(root, f);
            if (seen.Add(full.ToLowerInvariant()))
            {
                found.Add(full);
                if (found.Count >= maxFiles)
                    return true;
            }
        }
        foreach (var dir in dirs)
        {
            if (Walk(PyX.Join(root, Path.GetFileName(dir)), found, seen, maxFiles))
                return true;
        }
        return false;
    }
}
