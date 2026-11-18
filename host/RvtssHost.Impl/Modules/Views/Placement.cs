using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Placement module: port of revit_mcp/placement.py.
/// Handles family placement and element creation functionality.
/// </summary>
public static class Placement
{
    /// <summary>Register all placement-related routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/place_family/", new[] { "POST" }, PlaceFamily, apiContext: true);
        api.Raw("/list_families/", new[] { "POST" }, ListFamilies, apiContext: true);
        api.Raw("/list_family_categories/", new[] { "GET" }, ListFamilyCategories, apiContext: true);
        api.Raw("/list_levels/", new[] { "GET" }, ListLevels, apiContext: true);
    }

    private static Response Error(string message, int status) => new(new Dict { ["error"] = message }, status);

    /// <summary>`k in container` for a request value: dict keys, list items, substring of a text.</summary>
    private static bool PyIn(string k, object? container) => container switch
    {
        Dict d => d.ContainsKey(k),
        Lst l => l.Any(x => x is string s && s == k),
        string s => s.IndexOf(k, StringComparison.Ordinal) >= 0,
        _ => false,
    };

    /// <summary>
    /// Place a family instance at a specified location in the model.
    ///
    /// Expected request data: family_name, type_name, location {x, y, z}, rotation, level_name,
    /// properties {name: value}, unit (default "ft"), host_id.
    /// </summary>
    public static Response PlaceFamily(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // Parse request data
            var data = request.Data;
            if (data == null)
            {
                // The body was not a JSON object: invalid text, or valid JSON that is not an object
                if (string.IsNullOrWhiteSpace(request.Body))
                    return Error("No data provided or invalid request format", 400);
                if (request.BodyError != null && request.BodyError.StartsWith("Request body must be", StringComparison.Ordinal))
                    return Error("Invalid data format - expected JSON object", 400);
                var detail = request.BodyError ?? "";
                const string prefix = "Invalid JSON body: ";
                if (detail.StartsWith(prefix, StringComparison.Ordinal))
                    detail = detail.Substring(prefix.Length);
                return Error("Invalid JSON format: " + detail, 400);
            }
            if (data.Count == 0)
                return Error("No data provided or invalid request format", 400);

            // Extract required fields
            var familyName = data.Get("family_name");
            var typeName = data.Get("type_name");
            var location = data.Get("location", new Dict());
            var rotation = data.Get("rotation", 0.0);
            var levelName = data.Get("level_name");
            var properties = data.Get("properties", new Dict());
            // Optional (RVTSS): coordinate unit and host element. Defaults keep the
            // original behaviour (decimal feet, unhosted placement).
            var unit = Py.Truthy(data.Get("unit")) ? Py.Str(data.Get("unit")) : "ft";
            var hostId = data.Get("host_id");

            // Basic validation
            if (!Py.Truthy(familyName))
                return Error("No family_name provided", 400);

            // Validate location
            if (!Py.Truthy(location) || !(PyIn("x", location) && PyIn("y", location) && PyIn("z", location)))
                return Error("Invalid location - must include x, y, z coordinates", 400);

            // Find the appropriate family symbol (type)
            var targetSymbol = Utils.FindFamilySymbolSafely(doc, familyName, typeName);

            if (targetSymbol == null)
            {
                // Get list of available families for better error message
                List<string> availableFamilies;
                try
                {
                    var symbols = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)).ToElements();
                    var familyNames = new HashSet<string>(StringComparer.Ordinal);
                    foreach (var element in symbols.Take(200))  // Limit to prevent overwhelming response
                    {
                        try
                        {
                            var familyNameSafe = Utils.NormalizeString(((DB.FamilySymbol)element).Family.Name);
                            familyNames.Add(familyNameSafe);
                        }
                        catch
                        {
                            continue;
                        }
                    }
                    availableFamilies = familyNames.OrderBy(x => x, StringComparer.Ordinal).ToList();
                }
                catch
                {
                    availableFamilies = new List<string> { "Could not retrieve family list" };
                }

                return new Response(new Dict
                {
                    ["error"] = $"Family type not found: {Py.Str(familyName)} - {(Py.Truthy(typeName) ? Py.Str(typeName) : "Any")}",
                    ["available_families"] = availableFamilies.Take(20).ToList(),  // Show first 20
                }, 404);
            }

            // Find level if specified
            DB.Level? targetLevel = null;
            if (Py.Truthy(levelName))
            {
                var levels = new DB.FilteredElementCollector(doc)
                    .OfCategory(DB.BuiltInCategory.OST_Levels)
                    .WhereElementIsNotElementType()
                    .ToElements();

                foreach (var level in levels)
                {
                    try
                    {
                        var levelNameSafe = Utils.GetElementName(level);
                        if (levelName is string ln && levelNameSafe == ln)
                        {
                            targetLevel = level as DB.Level;
                            break;
                        }
                    }
                    catch
                    {
                        continue;
                    }
                }

                if (targetLevel == null)
                    return Error($"Level not found: {Py.Str(levelName)}", 404);
            }

            // Create the location point
            DB.XYZ point;
            try
            {
                if (location is not Dict locDict)
                    throw new FormatException((location is string ? "string" : "list") + " indices must be integers, not str");
                point = new DB.XYZ(
                    Units.ToInternal(locDict["x"], unit),
                    Units.ToInternal(locDict["y"], unit),
                    Units.ToInternal(locDict["z"], unit));
            }
            catch (FormatException coordError)
            {
                return Error("Invalid coordinates: " + coordError.Message, 400);
            }

            // Start a transaction
            var refused = Core.ReadOnlyResponse("place_family");
            if (refused != null)
                return refused;
            var t = new DB.Transaction(doc, "Place Family Instance via MCP");
            t.Start();

            try
            {
                // Ensure the symbol is activated
                if (!targetSymbol.IsActive)
                {
                    targetSymbol.Activate();
                    doc.Regenerate();  // Ensure activation takes effect
                }

                DB.Element? host = null;
                if (hostId != null)
                {
                    host = doc.GetElement(Compat.MakeId(Py.ToInt(hostId)));
                    if (host == null)
                        throw new FormatException($"Host element {Py.Str(hostId)} not found");
                }

                // Create the instance
                DB.FamilyInstance newInstance;
                if (host != null && targetLevel != null)
                {
                    newInstance = doc.Create.NewFamilyInstance(
                        point, targetSymbol, host, targetLevel,
                        DB.Structure.StructuralType.NonStructural);
                }
                else if (host != null)
                {
                    newInstance = doc.Create.NewFamilyInstance(
                        point, targetSymbol, host,
                        DB.Structure.StructuralType.NonStructural);
                }
                else if (targetLevel != null)
                {
                    // Place on specific level
                    newInstance = doc.Create.NewFamilyInstance(
                        point, targetSymbol, targetLevel,
                        DB.Structure.StructuralType.NonStructural);
                }
                else
                {
                    // Place without level specification
                    newInstance = doc.Create.NewFamilyInstance(
                        point, targetSymbol, DB.Structure.StructuralType.NonStructural);
                }

                // Apply rotation if specified (rotation != 0)
                var rotationIsZero = rotation is long rl ? rl == 0 : rotation is double rd ? rd == 0.0 : rotation is bool rb && !rb;
                if (!rotationIsZero)
                {
                    try
                    {
                        var rotationRadians = Py.ToFloat(rotation) * Math.PI / 180.0;
                        var axis = DB.Line.CreateBound(point, point.Add(new DB.XYZ(0, 0, 1)));

                        var loc = newInstance.Location;
                        if (loc != null)
                        {
                            var success = loc.Rotate(axis, rotationRadians);
                            if (!success)
                                Log.Write("Rotation failed - element may not support rotation");
                        }
                    }
                    catch (Exception rotateErr)
                    {
                        Log.Write("Could not rotate element: " + rotateErr.Message);
                    }
                }

                // Set custom properties
                var propertiesSet = new List<string>();
                var propertiesFailed = new List<string>();

                if (properties is not Dict propsDict)
                    throw new InvalidOperationException($"'{(properties == null ? "NoneType" : properties is Lst ? "list" : properties is string ? "str" : properties.GetType().Name)}' object has no attribute 'items'");

                foreach (var kv in propsDict)
                {
                    var paramName = kv.Key;
                    var paramValue = kv.Value;
                    try
                    {
                        var param = newInstance.LookupParameter(paramName);
                        if (param != null && !param.IsReadOnly)
                        {
                            // Set parameter based on its storage type
                            if (param.StorageType == DB.StorageType.String)
                            {
                                param.Set(Py.Str(paramValue));
                                propertiesSet.Add(paramName);
                            }
                            else if (param.StorageType == DB.StorageType.Integer)
                            {
                                param.Set((int)Py.ToInt(paramValue));
                                propertiesSet.Add(paramName);
                            }
                            else if (param.StorageType == DB.StorageType.Double)
                            {
                                param.Set(Py.ToFloat(paramValue));
                                propertiesSet.Add(paramName);
                            }
                            else
                            {
                                propertiesFailed.Add($"{paramName} (unsupported type)");
                            }
                        }
                        else
                        {
                            if (param != null)
                                propertiesFailed.Add($"{paramName} (read-only)");
                            else
                                propertiesFailed.Add($"{paramName} (not found)");
                        }
                    }
                    catch (Exception paramError)
                    {
                        propertiesFailed.Add($"{paramName} (error: {paramError.Message})");
                    }
                }

                t.Commit();

                // Get actual placed location (may differ due to level constraints)
                Dict actualCoords;
                try
                {
                    var actualLocation = ((DB.LocationPoint)newInstance.Location).Point;
                    actualCoords = new Dict { ["x"] = actualLocation.X, ["y"] = actualLocation.Y, ["z"] = actualLocation.Z };
                }
                catch
                {
                    actualCoords = new Dict { ["x"] = point.X, ["y"] = point.Y, ["z"] = point.Z };
                }

                // Return information about the placed instance
                var responseData = new Dict
                {
                    ["status"] = "success",
                    ["element_id"] = Utils.ElementIdValue(newInstance.Id),
                    ["family_name"] = familyName,
                    ["type_name"] = typeName,
                    ["requested_location"] = new Dict { ["x"] = point.X, ["y"] = point.Y, ["z"] = point.Z },
                    ["actual_location"] = actualCoords,
                    ["rotation_degrees"] = rotation,
                    ["coordinate_unit"] = "ft",
                    ["host_id"] = hostId,
                    ["level"] = targetLevel != null ? levelName : null,
                    ["properties_set"] = propertiesSet,
                    ["properties_failed"] = propertiesFailed,
                };

                return new Response(responseData);
            }
            catch
            {
                // Roll back the transaction if something went wrong
                if (t.HasStarted() && !t.HasEnded())
                    t.RollBack();
                throw;
            }
        }
        catch (Exception e)
        {
            Log.Write("Failed to place family: " + e.Message);
            return new Response(new Dict { ["error"] = e.Message, ["traceback"] = e.ToString() }, 500);
        }
    }

    /// <summary>
    /// Get a flat list of family names and their types in the current Revit model.
    ///
    /// Optional POST body: "contains" (case-insensitive substring filter on family or type name),
    /// "limit" (max results, default 50). Each entry: family_name, type_name, category, is_active.
    /// </summary>
    public static Response ListFamilies(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // Parse optional filter params from JSON body
            object? containsFilter = null;
            long limit = 50;
            var body = request.Data;
            if (body != null && body.Count > 0)
            {
                try
                {
                    containsFilter = body.Get("contains");
                    limit = Py.ToInt(body.Get("limit", 50L));
                }
                catch
                {
                }
            }

            var symbols = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)).ToElements();
            var families = new List<Dict>();
            foreach (var element in symbols)
            {
                if (families.Count >= limit)
                    break;
                try
                {
                    var symbol = (DB.FamilySymbol)element;
                    var famName = Utils.NormalizeString(symbol.Family.Name);
                    var typeName = Utils.NormalizeString(Utils.GetElementName(symbol));
                    var category = symbol.Category != null ? symbol.Category.Name : "Unknown";
                    var isActive = symbol.IsActive;

                    // Apply contains filter (case-insensitive, matches family or type name)
                    if (Py.Truthy(containsFilter))
                    {
                        var needle = Utils.NormalizeString(containsFilter).ToLowerInvariant();
                        if (famName.ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0
                            && typeName.ToLowerInvariant().IndexOf(needle, StringComparison.Ordinal) < 0)
                            continue;
                    }

                    families.Add(new Dict
                    {
                        ["family_name"] = famName,
                        ["type_name"] = typeName,
                        ["category"] = category,
                        ["is_active"] = isActive,
                    });
                }
                catch
                {
                    continue;
                }
            }
            return new Response(new Dict
            {
                ["families"] = families,
                ["count"] = (long)families.Count,
                ["filtered_by"] = containsFilter,
                ["status"] = "success",
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to list families: " + e.Message);
            return Error("Failed to list families: " + e.Message, 500);
        }
    }

    /// <summary>Get a list of all family categories in the current Revit model, with family counts.</summary>
    public static Response ListFamilyCategories(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // Get all family symbols
            var symbols = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.FamilySymbol)).ToElements();

            var categories = new Dictionary<string, long>();

            foreach (var element in symbols)
            {
                try
                {
                    // Get category name
                    var categoryName = "Unknown";
                    try
                    {
                        if (element.Category != null)
                            categoryName = element.Category.Name;
                    }
                    catch
                    {
                    }

                    if (!categories.ContainsKey(categoryName))
                        categories[categoryName] = 0;

                    categories[categoryName] += 1;
                }
                catch (Exception e)
                {
                    Log.Write("Could not process family symbol: " + e.Message);
                    continue;
                }
            }

            // Sort by name
            var sortedCategories = new Dict();
            foreach (var kv in categories.OrderBy(x => x.Key, StringComparer.Ordinal))
                sortedCategories[kv.Key] = kv.Value;

            return new Response(new Dict
            {
                ["categories"] = sortedCategories,
                ["total_categories"] = (long)sortedCategories.Count,
                ["status"] = "success",
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to list family categories: " + e.Message);
            return Error("Failed to list family categories: " + e.Message, 500);
        }
    }

    /// <summary>Get a list of all levels in the current Revit model, with their elevations (decimal feet).</summary>
    public static Response ListLevels(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // Get all levels
            var levels = new DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_Levels)
                .WhereElementIsNotElementType()
                .ToElements();

            var levelsInfo = new List<(double elevation, Dict info)>();

            foreach (var element in levels)
            {
                try
                {
                    var level = (DB.Level)element;
                    var levelName = Utils.GetElementName(level);
                    var elevation = level.Elevation;
                    var rounded = Py.Round(elevation, 2);

                    levelsInfo.Add((rounded, new Dict
                    {
                        ["name"] = levelName,
                        ["elevation"] = rounded,
                        ["id"] = Utils.ElementIdValue(level.Id),
                    }));
                }
                catch (Exception e)
                {
                    Log.Write("Could not process level: " + e.Message);
                    continue;
                }
            }

            // Sort by elevation (stable)
            var sorted = levelsInfo.OrderBy(x => x.elevation).Select(x => x.info).ToList();

            return new Response(new Dict
            {
                ["levels"] = sorted,
                ["total_levels"] = (long)sorted.Count,
                ["status"] = "success",
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to list levels: " + e.Message);
            return Error("Failed to list levels: " + e.Message, 500);
        }
    }
}
