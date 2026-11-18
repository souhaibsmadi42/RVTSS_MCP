using System.Globalization;

namespace RvtssHost.Modules;

/// <summary>
/// Views module: port of revit_mcp/views.py.
/// Handles view export and image generation functionality.
/// </summary>
public static class Views
{
    /// <summary>Register all view-related routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/get_view/<view_name>", new[] { "GET" }, GetView, apiContext: true);
        api.Raw("/list_views/", new[] { "GET" }, ListViews, apiContext: true);
        api.Raw("/current_view_info/", new[] { "GET" }, GetCurrentViewInfo, apiContext: true);
        api.Raw("/current_view_elements/", new[] { "POST" }, GetCurrentViewElements, apiContext: true);
    }

    private static Response Error(string message, int status) => new(new Dict { ["error"] = message }, status);

    /// <summary>str.isdigit() for a non-empty string.</summary>
    private static bool IsDigits(string s)
    {
        if (s.Length == 0)
            return false;
        foreach (var c in s)
            if (!char.IsDigit(c))
                return false;
        return true;
    }

    /// <summary>
    /// Export a named Revit view as a PNG image and return the image data.
    /// Returns a dict with base64 encoded image data and content type, or an error message.
    /// </summary>
    public static Response GetView(Request request)
    {
        string viewName = "";
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // The route table already URL-decoded the path segment (the pyRevit router did not: unquote there).
            viewName = Py.Str(request.UrlParams.Get("view_name"));
            // Normalize the view name
            viewName = Utils.NormalizeString(viewName);

            // Optional query options (RVTSS v2.1): image_format=png|jpg, pixel_size=128..4096
            var query = request.Query;
            var imageFormat = (Py.Truthy(query.Get("image_format")) ? Py.Str(query.Get("image_format")) : "png").ToLowerInvariant();
            if (imageFormat != "png" && imageFormat != "jpg" && imageFormat != "jpeg")
                return Error("image_format must be png or jpg", 400);
            var isJpeg = imageFormat != "png";
            long pixelSize;
            try
            {
                var raw = query.Get("pixel_size");
                pixelSize = Math.Max(128, Math.Min(4096, Py.ToInt(Py.Truthy(raw) ? raw : (object)1024L)));
            }
            catch (FormatException)
            {
                pixelSize = 1024;
            }

            // Define output folder in temp directory
            var outputFolder = Path.Combine(Path.GetTempPath(), "RevitMCPExports");

            // Create output folder if it doesn't exist
            if (!Directory.Exists(outputFolder))
                Directory.CreateDirectory(outputFolder);

            // Unique filename prefix per export. The old fixed "export" prefix plus
            // "newest PNG in the folder" lookup could return a stale image from an
            // earlier export when the current export produced nothing.
            var exportPrefix = "export_" + Guid.NewGuid().ToString("N").Substring(0, 12);
            var filePathPrefix = Path.Combine(outputFolder, exportPrefix);

            // Find the view by name
            DB.View? targetView = null;
            var allViews = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).ToElements();

            foreach (var element in allViews)
            {
                try
                {
                    // Use safe name access
                    var currentViewName = Utils.NormalizeString(Utils.GetElementName(element));
                    if (currentViewName == viewName)
                    {
                        targetView = element as DB.View;
                        break;
                    }
                }
                catch
                {
                    continue;
                }
            }

            // Allow an element id ("12345") so views with duplicate names
            // (e.g. a floor plan and a ceiling plan both called "Level 1")
            // can be addressed unambiguously.
            if (targetView == null && IsDigits(viewName))
            {
                try
                {
                    var candidate = doc.GetElement(Compat.MakeId(Py.ToInt(viewName)));
                    if (candidate is DB.View cv)
                        targetView = cv;
                }
                catch (Exception e)
                {
                    Log.Write("View id lookup failed: " + e.Message);
                }
            }

            if (targetView == null)
            {
                // Get list of available views for better error message
                var availableViews = new List<string>();
                foreach (var element in allViews)
                {
                    try
                    {
                        var view = (DB.View)element;
                        var viewNameSafe = Utils.NormalizeString(Utils.GetElementName(view));
                        // Filter out system views and templates
                        if (!view.IsTemplate
                            && view.ViewType != DB.ViewType.Internal
                            && view.ViewType != DB.ViewType.ProjectBrowser)
                            availableViews.Add(viewNameSafe);
                    }
                    catch
                    {
                        continue;
                    }
                }

                return new Response(new Dict
                {
                    ["error"] = $"View '{viewName}' not found",
                    ["available_views"] = availableViews.Take(20).ToList(), // Limit to first 20 for readability
                }, 404);
            }

            // Check if view can be exported
            try
            {
                if (targetView.IsTemplate)
                    return Error("Cannot export view templates", 400);

                if (targetView.ViewType == DB.ViewType.Internal)
                    return Error("Cannot export internal views", 400);
            }
            catch (Exception e)
            {
                Log.Write("Could not check view properties: " + e.Message);
            }

            // Set up export options
            var ieo = new DB.ImageExportOptions();
            ieo.ExportRange = DB.ExportRange.SetOfViews;

            // Create list of view IDs to export
            var viewIds = new List<DB.ElementId> { targetView.Id };
            ieo.SetViewsAndSheets(viewIds);

            ieo.FilePath = filePathPrefix;
            var fileType = isJpeg ? DB.ImageFileType.JPEGMedium : DB.ImageFileType.PNG;
            ieo.HLRandWFViewsFileType = fileType;
            ieo.ShadowViewsFileType = fileType;
            ieo.ImageResolution = DB.ImageResolution.DPI_150;
            ieo.ZoomType = DB.ZoomFitType.FitToPage;
            ieo.PixelSize = (int)pixelSize;

            // Export the image
            doc.ExportImage(ieo);

            // Find the exported file (most recent image with our prefix)
            var matchingFiles = new List<string>();
            try
            {
                foreach (var f in Directory.GetFiles(outputFolder).Select(Path.GetFileName))
                {
                    var lower = f!.ToLowerInvariant();
                    var okExt = isJpeg ? (lower.EndsWith(".jpg") || lower.EndsWith(".jpeg")) : lower.EndsWith(".png");
                    if (f.StartsWith(exportPrefix, StringComparison.Ordinal) && okExt)
                        matchingFiles.Add(Path.Combine(outputFolder, f));
                }
                matchingFiles = matchingFiles.OrderByDescending(x => File.GetCreationTimeUtc(x)).ToList();
            }
            catch (Exception e)
            {
                Log.Write("Could not list exported files: " + e.Message);
                return Error("Could not access export folder", 500);
            }

            if (matchingFiles.Count == 0)
                return Error("Export failed - no image file was created", 500);

            var exportedFile = matchingFiles[0];

            // Read and encode the image
            byte[] imgData;
            string encodedData;
            try
            {
                imgData = File.ReadAllBytes(exportedFile);
                encodedData = Convert.ToBase64String(imgData);
            }
            catch (Exception e)
            {
                Log.Write("Could not read/encode image file: " + e.Message);
                return Error("Could not read exported image file", 500);
            }
            finally
            {
                // Clean up the file
                try
                {
                    if (File.Exists(exportedFile))
                        File.Delete(exportedFile);
                }
                catch (Exception e)
                {
                    Log.Write("Could not clean up temporary file: " + e.Message);
                }
            }

            return new Response(new Dict
            {
                ["image_data"] = encodedData,
                ["content_type"] = isJpeg ? "image/jpeg" : "image/png",
                ["pixel_size"] = pixelSize,
                ["view_name"] = viewName,
                ["file_size_bytes"] = (long)imgData.Length,
                ["export_success"] = true,
            });
        }
        catch (Exception e)
        {
            Log.Write($"Failed to export view '{viewName}': {e.Message}");
            return Error("Failed to export view: " + e.Message, 500);
        }
    }

    /// <summary>Get a list of all exportable views in the current Revit model, organized by type.</summary>
    public static Response ListViews(Request request)
    {
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return Error("No active Revit document", 503);

            // Get all views
            var allViews = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).ToElements();

            var viewsByType = new Dictionary<string, List<string>>
            {
                ["floor_plans"] = new List<string>(),
                ["ceiling_plans"] = new List<string>(),
                ["elevations"] = new List<string>(),
                ["sections"] = new List<string>(),
                ["3d_views"] = new List<string>(),
                ["drafting_views"] = new List<string>(),
                ["schedules"] = new List<string>(),
                ["other"] = new List<string>(),
            };

            foreach (var element in allViews)
            {
                try
                {
                    var view = (DB.View)element;
                    // Skip templates and internal views
                    if (view.IsTemplate)
                        continue;

                    if (view.ViewType == DB.ViewType.Internal || view.ViewType == DB.ViewType.ProjectBrowser)
                        continue;

                    var viewName = Utils.NormalizeString(Utils.GetElementName(view));
                    var viewType = view.ViewType;

                    // Categorize views
                    if (viewType == DB.ViewType.FloorPlan)
                        viewsByType["floor_plans"].Add(viewName);
                    else if (viewType == DB.ViewType.CeilingPlan)
                        viewsByType["ceiling_plans"].Add(viewName);
                    else if (viewType == DB.ViewType.Elevation)
                        viewsByType["elevations"].Add(viewName);
                    else if (viewType == DB.ViewType.Section)
                        viewsByType["sections"].Add(viewName);
                    else if (viewType == DB.ViewType.ThreeD)
                        viewsByType["3d_views"].Add(viewName);
                    else if (viewType == DB.ViewType.DraftingView)
                        viewsByType["drafting_views"].Add(viewName);
                    else if (viewType == DB.ViewType.Schedule)
                        viewsByType["schedules"].Add(viewName);
                    else
                        viewsByType["other"].Add(viewName);
                }
                catch (Exception e)
                {
                    Log.Write("Could not process view: " + e.Message);
                    continue;
                }
            }

            // Sort all lists alphabetically
            foreach (var viewList in viewsByType.Values)
                viewList.Sort(StringComparer.Ordinal);

            // Count total exportable views
            long totalViews = viewsByType.Values.Sum(l => l.Count);

            var viewsOut = new Dict();
            foreach (var kv in viewsByType)
                viewsOut[kv.Key] = kv.Value;

            return new Response(new Dict
            {
                ["views_by_type"] = viewsOut,
                ["total_exportable_views"] = totalViews,
                ["status"] = "success",
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to list views: " + e.Message);
            return Error("Failed to list views: " + e.Message, 500);
        }
    }

    /// <summary>Get detailed information about the currently active view.</summary>
    public static Response GetCurrentViewInfo(Request request)
    {
        try
        {
            var uidoc = request.UiDoc;
            if (uidoc == null || uidoc.Document == null)
                return Error("No active Revit document", 503);

            var currentView = uidoc.ActiveView;
            if (currentView == null)
                return Error("No active view found", 404);

            // Get basic view information
            var viewInfo = new Dict
            {
                ["view_name"] = Utils.NormalizeString(Utils.GetElementName(currentView)),
                ["view_type"] = currentView.ViewType.ToString(),
                ["view_id"] = Utils.ElementIdValue(currentView.Id),
                ["is_template"] = currentView.IsTemplate,
            };

            // Add scale information if available
            try { viewInfo["scale"] = (long)currentView.Scale; }
            catch { viewInfo["scale"] = null; }

            // Add crop box information if available
            try { viewInfo["crop_box_active"] = currentView.CropBoxActive; }
            catch { viewInfo["crop_box_active"] = false; }

            // Add view family type if available
            try
            {
                var viewFamilyType = currentView.Document.GetElement(currentView.GetTypeId());
                if (viewFamilyType != null)
                    viewInfo["view_family_type"] = Utils.NormalizeString(Utils.GetElementName(viewFamilyType));
                else
                    viewInfo["view_family_type"] = "Unknown";
            }
            catch
            {
                viewInfo["view_family_type"] = "Unknown";
            }

            // Add detail level if available
            try { viewInfo["detail_level"] = currentView.DetailLevel.ToString(); }
            catch { viewInfo["detail_level"] = "Unknown"; }

            // Add view discipline if available
            try { viewInfo["discipline"] = currentView.Discipline.ToString(); }
            catch { viewInfo["discipline"] = "Unknown"; }

            return new Response(new Dict { ["status"] = "success", ["view_info"] = viewInfo });
        }
        catch (Exception e)
        {
            Log.Write("Get current view info failed: " + e.Message);
            return Error("Failed to get current view info: " + e.Message, 500);
        }
    }

    /// <summary>
    /// Get all elements visible in the current view.
    ///
    /// Expected JSON payload (all fields optional):
    /// { "limit": 5000, "include_levels": false, "include_location": false }
    /// </summary>
    public static Response GetCurrentViewElements(Request request)
    {
        try
        {
            var doc = request.Doc;
            var uidoc = request.UiDoc;
            if (doc == null || uidoc == null)
                return Error("No active Revit document", 503);

            var currentView = uidoc.ActiveView;
            if (currentView == null)
                return Error("No active view found", 404);

            // Parse optional parameters from request body
            long limit = 5000;
            var includeLevels = false;
            var includeLocation = false;
            try
            {
                var data = request.Data;
                if (data != null && data.Count > 0)
                {
                    limit = Py.ToInt(data.Get("limit", 5000L));
                    includeLevels = Py.Truthy(data.Get("include_levels", false));
                    includeLocation = Py.Truthy(data.Get("include_location", false));
                }
            }
            catch
            {
                // Use defaults if parsing fails
            }

            // Get all elements in the current view
            var collector = new DB.FilteredElementCollector(doc, currentView.Id);
            var elements = collector.WhereElementIsNotElementType().ToElements();

            // Level cache to avoid redundant doc.GetElement() calls
            var levelCache = new Dictionary<long, (string name, long id)>();

            // Process elements, tracking category counts for ALL elements
            var elementsInfo = new List<Dict>();
            var categoryCounts = new Dict();
            long totalElements = 0;

            foreach (var elem in elements)
            {
                try
                {
                    // Get category name for counting (always counted, even beyond limit)
                    var cat = elem.Category;
                    string catName = cat != null ? cat.Name : "Unknown";

                    if (categoryCounts.TryGetValue(catName, out var cnt))
                        categoryCounts[catName] = (long)cnt! + 1;
                    else
                        categoryCounts[catName] = 1L;
                    totalElements++;

                    // Only build full element info up to the limit
                    if (elementsInfo.Count >= limit)
                        continue;

                    var elementInfo = new Dict
                    {
                        ["element_id"] = Utils.ElementIdValue(elem.Id),
                        ["name"] = Utils.NormalizeString(Utils.GetElementName(elem)),
                        ["category"] = catName,
                    };

                    if (cat != null)
                        elementInfo["category_id"] = Utils.ElementIdValue(cat.Id);
                    else
                        elementInfo["category_id"] = null;

                    // Add level information only if requested (opt-in)
                    if (includeLevels)
                    {
                        try
                        {
                            var levelParam = elem.get_Parameter(DB.BuiltInParameter.FAMILY_LEVEL_PARAM);
                            if (levelParam != null)
                            {
                                var levelId = levelParam.AsElementId();
                                if (levelId != null && levelId != DB.ElementId.InvalidElementId)
                                {
                                    var lid = Utils.ElementIdValue(levelId);
                                    if (levelCache.TryGetValue(lid, out var cached))
                                    {
                                        elementInfo["level"] = cached.name;
                                        elementInfo["level_id"] = cached.id;
                                    }
                                    else
                                    {
                                        var levelElem = doc.GetElement(levelId);
                                        if (levelElem == null)
                                            throw new InvalidOperationException("level element not found");
                                        var lname = Utils.NormalizeString(Utils.GetElementName(levelElem));
                                        levelCache[lid] = (lname, lid);
                                        elementInfo["level"] = lname;
                                        elementInfo["level_id"] = lid;
                                    }
                                }
                                else
                                {
                                    elementInfo["level"] = null;
                                    elementInfo["level_id"] = null;
                                }
                            }
                            else
                            {
                                elementInfo["level"] = null;
                                elementInfo["level_id"] = null;
                            }
                        }
                        catch
                        {
                            elementInfo["level"] = null;
                            elementInfo["level_id"] = null;
                        }
                    }

                    // Add location information only if requested (opt-in)
                    if (includeLocation)
                    {
                        try
                        {
                            var location = elem.Location;
                            if (location is DB.LocationPoint lp)
                            {
                                var pt = lp.Point;
                                elementInfo["location"] = new Dict
                                {
                                    ["type"] = "point",
                                    ["x"] = pt.X,
                                    ["y"] = pt.Y,
                                    ["z"] = pt.Z,
                                };
                            }
                            else if (location is DB.LocationCurve lc)
                            {
                                var curve = lc.Curve;
                                var start = curve.GetEndPoint(0);
                                var end = curve.GetEndPoint(1);
                                elementInfo["location"] = new Dict
                                {
                                    ["type"] = "curve",
                                    ["start"] = new Dict { ["x"] = start.X, ["y"] = start.Y, ["z"] = start.Z },
                                    ["end"] = new Dict { ["x"] = end.X, ["y"] = end.Y, ["z"] = end.Z },
                                };
                            }
                            else
                            {
                                elementInfo["location"] = new Dict { ["type"] = "unknown" };
                            }
                        }
                        catch
                        {
                            elementInfo["location"] = new Dict { ["type"] = "unknown" };
                        }
                    }

                    elementsInfo.Add(elementInfo);
                }
                catch (Exception elemError)
                {
                    Log.Write("Could not process element: " + elemError.Message);
                    continue;
                }
            }

            var truncated = totalElements > elementsInfo.Count;

            var result = new Dict
            {
                ["status"] = "success",
                ["view_name"] = Utils.NormalizeString(Utils.GetElementName(currentView)),
                ["view_id"] = Utils.ElementIdValue(currentView.Id),
                ["total_elements"] = totalElements,
                ["returned_elements"] = (long)elementsInfo.Count,
                ["limit"] = limit,
                ["truncated"] = truncated,
                ["elements"] = elementsInfo,
                ["category_counts"] = categoryCounts,
            };

            if (truncated)
                result["message"] = string.Format(CultureInfo.InvariantCulture,
                    "Results truncated: showing {0} of {1} elements. Use limit parameter to retrieve more.",
                    elementsInfo.Count, totalElements);

            return new Response(result);
        }
        catch (Exception e)
        {
            Log.Write("Get current view elements failed: " + e.Message);
            return Error("Failed to get current view elements: " + e.Message, 500);
        }
    }
}
