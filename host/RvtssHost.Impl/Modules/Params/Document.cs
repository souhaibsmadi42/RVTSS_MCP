namespace RvtssHost.Modules;

/// <summary>
/// Document Management Module for Revit MCP: port of revit_mcp/document.py.
/// Handles opening, closing, saving documents and syncing with central.
/// (The class is not called Document: that would clash with DB.Document usage.)
/// </summary>
public static class DocumentRoutes
{
    /// <summary>register_document_routes: register all document management routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        api.Raw("/open_document/", new[] { "POST" }, OpenDocument, apiContext: true);
        api.Raw("/close_document/", new[] { "POST" }, CloseDocument, apiContext: true);
        api.Raw("/save_document/", new[] { "POST" }, SaveDocument, apiContext: true);
        api.Raw("/sync_with_central/", new[] { "POST" }, SyncWithCentral, apiContext: true);
    }

    /// <summary>The Python read request.data and called data.get(...): without a JSON object that failed with an
    /// AttributeError, which the route's except clause turned into a 500 answer.</summary>
    private static Dict RequestData(Request request)
    {
        if (request.Data == null)
            throw new InvalidOperationException("'NoneType' object has no attribute 'get'");
        return request.Data;
    }

    private static Response Error(string text, int status) => new(new Dict { ["error"] = text }, status);

    private static string TitleOf(DB.Document doc) => !string.IsNullOrEmpty(doc.Title) ? doc.Title : "Untitled";

    /// <summary>
    /// Open a Revit document file.
    ///
    /// Expected payload:
    /// {
    ///     "file_path": "C:\\path\\to\\file.rvt",
    ///     "detach": false,
    ///     "audit": false
    /// }
    /// </summary>
    public static Response OpenDocument(Request request)
    {
        Dict? data = null;
        try
        {
            data = RequestData(request);
            var filePathValue = data.Get("file_path", "");
            var detach = data.Get("detach", false);
            var audit = data.Get("audit", false);

            if (!Py.Truthy(filePathValue))
                return Error("No file_path provided", 400);
            var filePath = Py.Str(filePathValue);

            // (the active document may be null when no document is open)
            var uiapp = request.UiApp ?? Hosting.UiApp!;

            // Convert string path to ModelPath
            var modelPath = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(filePath);

            // Build open options
            var openOptions = new DB.OpenOptions();

            if (Py.Truthy(detach))
                openOptions.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndPreserveWorksets;

            if (Py.Truthy(audit))
                openOptions.Audit = true;

            Log.Write($"Opening document: {filePath} (detach={Py.Str(detach)}, audit={Py.Str(audit)})");

            // Use OpenAndActivateDocument on UIApplication
            // This handles UI-thread marshalling and worksharing dialogs
            // Third param: False = don't close the existing active document
            uiapp.OpenAndActivateDocument(modelPath, openOptions, false);

            // After opening, get the now-active document
            var newDoc = uiapp.ActiveUIDocument?.Document;
            Dict result;
            if (newDoc != null)
            {
                result = new Dict
                {
                    ["status"] = "success",
                    ["document_title"] = TitleOf(newDoc),
                    ["file_path"] = filePath,
                    ["is_workshared"] = newDoc.IsWorkshared,
                };
                if (Py.Truthy(detach))
                {
                    result["detached"] = true;
                    result["message"] = "Document opened detached from central model.";
                }
                else if (newDoc.IsWorkshared)
                {
                    result["message"] = "Workshared document opened. A local copy has been created.";
                }
                else
                {
                    result["message"] = "Document opened successfully.";
                }
            }
            else
            {
                result = new Dict
                {
                    ["status"] = "success",
                    ["message"] = "Open command sent. Document may still be loading.",
                    ["file_path"] = filePath,
                };
            }
            return new Response(result);
        }
        catch (Exception e)
        {
            var errorTb = e.ToString();
            var inner = e.InnerException;
            var innerMsg = inner != null ? inner.ToString() : "None";
            Log.Write($"Failed to open document: {e.Message}\nInner exception: {innerMsg}\n{errorTb}");
            return new Response(new Dict
            {
                ["error"] = "Failed to open document: " + e.Message,
                ["inner_exception"] = innerMsg,
                ["traceback"] = errorTb,
                ["file_path"] = data != null ? data.Get("file_path", "") : "",
            }, 500);
        }
    }

    /// <summary>
    /// Close the active Revit document.
    ///
    /// Expected payload:
    /// {
    ///     "save": false
    /// }
    /// </summary>
    public static Response CloseDocument(Request request)
    {
        try
        {
            var data = RequestData(request);
            var save = data.Get("save", false);
            var doc = request.Doc;

            if (doc == null)
                return Error("No active document to close", 400);

            var docTitle = TitleOf(doc);

            Log.Write($"Closing document: {docTitle} (save={Py.Str(save)})");

            if (Py.Truthy(save))
            {
                var refused = Core.ReadOnlyResponse("close_document(save=true)")
                              ?? Core.FilePolicyResponse("save", "close_document(save=true)");
                if (refused != null)
                    return refused;
                try
                {
                    doc.Save();
                }
                catch (Exception saveErr)
                {
                    Log.Write("Save before close failed: " + saveErr.Message);
                }
            }

            // Use PostCommand to close the active document since
            // doc.Close() is not allowed on the active document from the API
            var uiapp = request.UiApp ?? Hosting.UiApp!;
            var closeCmd = RevitCommandId.LookupPostableCommandId(PostableCommand.Close);
            uiapp.PostCommand(closeCmd);

            return new Response(new Dict
            {
                ["status"] = "success",
                ["message"] = $"Document '{docTitle}' close command sent{(Py.Truthy(save) ? " (saved first)" : "")}.",
                ["document_title"] = docTitle,
                ["saved"] = save,
                ["note"] = "Revit may show a confirmation dialog if there are unsaved changes.",
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to close document: " + e.Message);
            return Error("Failed to close document: " + e.Message, 500);
        }
    }

    /// <summary>
    /// Save the active Revit document, optionally to a new path (Save As).
    ///
    /// Expected payload:
    /// {
    ///     "file_path": null
    /// }
    ///
    /// If file_path is null/omitted, saves in place.
    /// If file_path is provided, performs Save As to that location.
    /// </summary>
    public static Response SaveDocument(Request request)
    {
        try
        {
            var data = RequestData(request);
            var filePath = data.Get("file_path");
            var doc = request.Doc;

            if (doc == null)
                return Error("No active document to save", 400);

            var docTitle = TitleOf(doc);

            if (Py.Truthy(filePath))
            {
                // Save As
                var path = Py.Str(filePath);
                Log.Write($"Saving document '{docTitle}' as: {path}");
                var refused = Core.ReadOnlyResponse("save_document") ?? Core.FilePolicyResponse("save", "save_document");
                if (refused != null)
                    return refused;
                var saveAsOptions = new DB.SaveAsOptions { OverwriteExistingFile = true };

                // Workshared/detached docs require SaveAsCentral
                if (doc.IsWorkshared)
                {
                    var wsOptions = new DB.WorksharingSaveAsOptions { SaveAsCentral = true };
                    saveAsOptions.SetWorksharingOptions(wsOptions);
                }

                doc.SaveAs(path, saveAsOptions);

                return new Response(new Dict
                {
                    ["status"] = "success",
                    ["message"] = $"Document saved as '{path}'.",
                    ["document_title"] = docTitle,
                    ["saved_path"] = path,
                    ["save_type"] = "save_as",
                });
            }
            else
            {
                // Save in place
                Log.Write($"Saving document: {docTitle}");
                var refused = Core.ReadOnlyResponse("save_document") ?? Core.FilePolicyResponse("save", "save_document");
                if (refused != null)
                    return refused;
                doc.Save();

                return new Response(new Dict
                {
                    ["status"] = "success",
                    ["message"] = $"Document '{docTitle}' saved.",
                    ["document_title"] = docTitle,
                    ["save_type"] = "save",
                });
            }
        }
        catch (Exception e)
        {
            Log.Write("Failed to save document: " + e.Message);
            return Error("Failed to save document: " + e.Message, 500);
        }
    }

    /// <summary>
    /// Synchronize the active workshared document with central.
    ///
    /// Expected payload:
    /// {
    ///     "comment": "",
    ///     "compact": false,
    ///     "relinquish_all": true
    /// }
    /// </summary>
    public static Response SyncWithCentral(Request request)
    {
        try
        {
            var data = RequestData(request);
            var comment = data.Get("comment", "");
            var compact = data.Get("compact", false);
            var relinquishAll = data.Get("relinquish_all", true);
            var doc = request.Doc;

            if (doc == null)
                return Error("No active document", 400);

            if (!doc.IsWorkshared)
                return Error("Document is not workshared. Use save_document instead.", 400);

            var docTitle = TitleOf(doc);

            Log.Write($"Syncing '{docTitle}' with central (comment='{Py.Str(comment)}', compact={Py.Str(compact)})");

            var refused = Core.ReadOnlyResponse("sync_with_central") ?? Core.FilePolicyResponse("sync", "sync_with_central");
            if (refused != null)
                return refused;

            // Build transact options
            var transactOptions = new DB.TransactWithCentralOptions();

            // Build sync options
            var syncOptions = new DB.SynchronizeWithCentralOptions
            {
                Comment = Py.Str(comment),
                Compact = Py.Truthy(compact),
            };

            if (Py.Truthy(relinquishAll))
                syncOptions.SetRelinquishOptions(new DB.RelinquishOptions(true));

            // Perform sync
            doc.SynchronizeWithCentral(transactOptions, syncOptions);

            return new Response(new Dict
            {
                ["status"] = "success",
                ["message"] = $"Document '{docTitle}' synchronized with central.",
                ["document_title"] = docTitle,
                ["comment"] = comment,
                ["compacted"] = compact,
                ["relinquished_all"] = relinquishAll,
            });
        }
        catch (Exception e)
        {
            Log.Write("Failed to sync with central: " + e.Message);
            return Error("Failed to sync with central: " + e.Message, 500);
        }
    }
}
