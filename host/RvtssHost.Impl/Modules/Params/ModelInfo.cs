namespace RvtssHost.Modules;

/// <summary>
/// Model Info Module for Revit MCP: port of revit_mcp/model_info.py.
/// Provides comprehensive model information for architects and designers.
/// Legacy module: the Python used pyrevit helpers (ProjectInfo wrapper, query.get_linked_model_instances,
/// query.get_rvt_link_instance_name); the same values are read with direct Revit API calls here.
/// </summary>
public static class ModelInfo
{
    /// <summary>register_model_info_routes: register all model information routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/model_info/", new[] { "GET" }, GetModelInfo, apiContext: true);
    }

    private static long CountOf(DB.Document doc, DB.BuiltInCategory category) =>
        new DB.FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType().GetElementCount();

    /// <summary>
    /// Get comprehensive information about the current Revit model.
    ///
    /// Returns architect-focused information including:
    /// - Project details (name, number, client)
    /// - Element counts by major categories
    /// - Basic warnings count
    /// - Views and sheets overview
    /// - Room information with levels
    /// - Link status
    /// </summary>
    public static Response GetModelInfo(Request request)
    {
        // request.Doc is the active document, injected like pyRevit Routes injected `doc`
        // (the handler runs in Revit API context).
        try
        {
            var doc = request.Doc;
            if (doc == null)
                return new Response(new Dict { ["error"] = "No active Revit document" }, 503);

            // ============ PROJECT INFORMATION ============
            Dict projectInfo;
            try
            {
                // pyrevit.revit.db.ProjectInfo: '' for family documents, else ProjectInformation properties
                var pi = doc.IsFamilyDocument ? null : doc.ProjectInformation;
                projectInfo = new Dict
                {
                    ["name"] = Utils.NormalizeString(pi != null ? pi.Name : ""),
                    ["number"] = Utils.NormalizeString(pi != null ? pi.Number : ""),
                    ["client"] = Utils.NormalizeString(pi != null ? pi.ClientName : ""),
                    ["file_name"] = Utils.NormalizeString(doc.Title),
                };
                if (pi == null && !doc.IsFamilyDocument)
                    throw new InvalidOperationException("no project information");
            }
            catch (Exception e)
            {
                Log.Write("Could not get full project info: " + e.Message);
                projectInfo = new Dict
                {
                    ["name"] = Utils.NormalizeString(doc.Title),
                    ["number"] = "Not Set",
                    ["client"] = "Not Set",
                    ["file_name"] = Utils.NormalizeString(doc.Title),
                };
            }

            // ============ ELEMENT COUNTS ============
            var elementCategories = new List<(string name, DB.BuiltInCategory category)>
            {
                ("Walls", DB.BuiltInCategory.OST_Walls),
                ("Floors", DB.BuiltInCategory.OST_Floors),
                ("Ceilings", DB.BuiltInCategory.OST_Ceilings),
                ("Roofs", DB.BuiltInCategory.OST_Roofs),
                ("Doors", DB.BuiltInCategory.OST_Doors),
                ("Windows", DB.BuiltInCategory.OST_Windows),
                ("Stairs", DB.BuiltInCategory.OST_Stairs),
                ("Railings", DB.BuiltInCategory.OST_Railings),
                ("Columns", DB.BuiltInCategory.OST_Columns),
                ("Structural_Framing", DB.BuiltInCategory.OST_StructuralFraming),
                ("Furniture", DB.BuiltInCategory.OST_Furniture),
                ("Lighting_Fixtures", DB.BuiltInCategory.OST_LightingFixtures),
                ("Plumbing_Fixtures", DB.BuiltInCategory.OST_PlumbingFixtures),
            };
            var elementCounts = new Dict();
            long totalElements = 0;
            foreach (var (name, category) in elementCategories)
            {
                try
                {
                    var count = CountOf(doc, category);
                    elementCounts[name] = count;
                    totalElements += count;
                }
                catch
                {
                    elementCounts[name] = 0L;
                }
            }

            // ============ WARNINGS ============
            long warningsCount, criticalWarnings;
            try
            {
                var warnings = doc.GetWarnings();
                warningsCount = warnings.Count;
                // Count critical warnings (simplified check)
                criticalWarnings = warnings.Count(w => w.GetSeverity() != DB.FailureSeverity.Warning);
            }
            catch (Exception e)
            {
                Log.Write("Could not read warnings: " + e.Message);
                warningsCount = 0;
                criticalWarnings = 0;
            }

            // ============ LEVELS ============
            List<Dict> levelsInfo;
            try
            {
                var levelsCollector = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels)
                    .WhereElementIsNotElementType().ToElements();
                levelsInfo = new List<Dict>();
                foreach (var level in levelsCollector)
                {
                    var levelName = Utils.GetElementName(level);
                    try
                    {
                        var elevation = ((DB.Level)level).Elevation;
                        levelsInfo.Add(new Dict { ["name"] = Utils.NormalizeString(levelName), ["elevation"] = Py.Round(elevation, 2) });
                    }
                    catch
                    {
                        levelsInfo.Add(new Dict { ["name"] = Utils.NormalizeString(levelName), ["elevation"] = "Unknown" });
                    }
                }
                // Sort by elevation if available
                try
                {
                    levelsInfo = levelsInfo.OrderBy(x => x["elevation"] is double d ? d : 0.0).ToList();
                }
                catch { /* keep the unsorted list */ }
            }
            catch (Exception e)
            {
                Log.Write("Could not get levels: " + e.Message);
                levelsInfo = new List<Dict>();
            }

            // ============ ROOMS ============
            List<Dict> roomsInfo;
            long unplacedRooms;
            try
            {
                var roomsCollector = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType().ToElements();
                roomsInfo = new List<Dict>();
                unplacedRooms = 0;
                foreach (var room in roomsCollector)
                {
                    try
                    {
                        // Get room name safely
                        var nameParam = room.LookupParameter("Name");
                        var roomName = nameParam != null && nameParam.HasValue ? nameParam.AsString() : "Unnamed Room";

                        // Get room number safely
                        var numberParam = room.LookupParameter("Number");
                        var roomNumber = numberParam != null && numberParam.HasValue ? numberParam.AsString() : "";

                        // Get room level
                        var levelName = "Unknown Level";
                        try
                        {
                            var level = doc.GetElement(room.LevelId);
                            if (level != null)
                                levelName = Utils.GetElementName(level);
                        }
                        catch { /* keep "Unknown Level" */ }

                        // Check if room is placed
                        double area = 0;
                        bool isPlaced;
                        try
                        {
                            area = ((DB.SpatialElement)room).Area;
                            isPlaced = area > 0;
                            if (!isPlaced)
                                unplacedRooms++;
                        }
                        catch
                        {
                            isPlaced = false;
                            unplacedRooms++;
                        }

                        var roomInfo = new Dict
                        {
                            ["name"] = Utils.NormalizeString(roomName),
                            ["number"] = Utils.NormalizeString(roomNumber),
                            ["level"] = Utils.NormalizeString(levelName),
                            ["is_placed"] = isPlaced,
                        };
                        if (isPlaced)
                        {
                            try { roomInfo["area"] = Py.Round(area, 2); }
                            catch { roomInfo["area"] = "Unknown"; }
                        }
                        roomsInfo.Add(roomInfo);
                    }
                    catch (Exception e)
                    {
                        Log.Write("Could not process room: " + e.Message);
                        continue;
                    }
                }
            }
            catch (Exception e)
            {
                Log.Write("Could not get rooms: " + e.Message);
                roomsInfo = new List<Dict>();
                unplacedRooms = 0;
            }

            // ============ VIEWS AND SHEETS ============
            long sheetsCount, viewsCount, floorPlans, elevations, sections, threedViews, schedules;
            try
            {
                // Get sheets
                sheetsCount = CountOf(doc, DB.BuiltInCategory.OST_Sheets);

                // Get views (excluding templates and invalid types)
                var allViews = new DB.FilteredElementCollector(doc).OfClass(typeof(DB.View)).ToElements();
                var validViews = allViews.Cast<DB.View>()
                    .Where(v => !v.IsTemplate && v.ViewType != DB.ViewType.Internal && v.ViewType != DB.ViewType.ProjectBrowser)
                    .ToList();
                viewsCount = validViews.Count;

                // Count major view types
                floorPlans = validViews.Count(v => v.ViewType == DB.ViewType.FloorPlan);
                elevations = validViews.Count(v => v.ViewType == DB.ViewType.Elevation);
                sections = validViews.Count(v => v.ViewType == DB.ViewType.Section);
                threedViews = validViews.Count(v => v.ViewType == DB.ViewType.ThreeD);
                schedules = validViews.Count(v => v.ViewType == DB.ViewType.Schedule);
            }
            catch (Exception e)
            {
                Log.Write("Could not get views/sheets: " + e.Message);
                sheetsCount = 0;
                viewsCount = 0;
                floorPlans = elevations = sections = threedViews = schedules = 0;
            }

            // ============ LINKED MODELS ============
            List<Dict> linkedModels;
            try
            {
                linkedModels = new List<Dict>();
                var rvtLinks = new DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_RvtLinks)
                    .WhereElementIsNotElementType().ToElements();
                foreach (var element in rvtLinks)
                {
                    try
                    {
                        var linkInstance = (DB.RevitLinkInstance)element;
                        var linkDoc = linkInstance.GetLinkDocument();
                        // pyrevit.revit.db.query.get_rvt_link_instance_name: element name split at " : "
                        var linkName = linkInstance.Name.Split(new[] { " : " }, StringSplitOptions.None)[1];

                        // Get load status
                        var linkType = doc.GetElement(linkInstance.GetTypeId());
                        var statusText = linkType != null ? ((DB.RevitLinkType)linkType).GetLinkedFileStatus().ToString() : "Unknown";
                        var status = Utils.NormalizeString(statusText.Split(new[] { '.' }).Last());

                        // Check if pinned
                        var isPinned = linkInstance.Pinned;

                        linkedModels.Add(new Dict
                        {
                            ["name"] = Utils.NormalizeString(linkName),
                            ["status"] = status,
                            ["is_loaded"] = linkDoc != null,
                            ["is_pinned"] = isPinned,
                        });
                    }
                    catch (Exception e)
                    {
                        Log.Write("Could not process linked model: " + e.Message);
                        continue;
                    }
                }
            }
            catch (Exception e)
            {
                Log.Write("Could not get linked models: " + e.Message);
                linkedModels = new List<Dict>();
            }

            // ============ COMPILE RESPONSE ============
            var modelData = new Dict
            {
                ["status"] = "success",
                ["units"] = new Dict { ["elevation"] = "ft", ["area"] = "ft2", ["note"] = "Revit internal units" },
                ["project_info"] = projectInfo,
                ["element_summary"] = new Dict { ["total_elements"] = totalElements, ["by_category"] = elementCounts },
                ["model_health"] = new Dict
                {
                    ["total_warnings"] = warningsCount, ["critical_warnings"] = criticalWarnings, ["unplaced_rooms"] = unplacedRooms,
                },
                ["spatial_organization"] = new Dict
                {
                    ["levels"] = levelsInfo, ["rooms"] = roomsInfo, ["room_count"] = (long)roomsInfo.Count,
                },
                ["documentation"] = new Dict
                {
                    ["total_views"] = viewsCount,
                    ["view_breakdown"] = new Dict
                    {
                        ["floor_plans"] = floorPlans, ["elevations"] = elevations, ["sections"] = sections,
                        ["3d_views"] = threedViews, ["schedules"] = schedules,
                    },
                    ["sheets_count"] = sheetsCount,
                },
                ["linked_models"] = new Dict { ["count"] = (long)linkedModels.Count, ["models"] = linkedModels },
            };
            return new Response(modelData);
        }
        catch (Exception e)
        {
            Log.Write("Failed to get model info: " + e.Message);
            return new Response(new Dict { ["error"] = "Failed to retrieve model information: " + e.Message }, 500);
        }
    }
}
