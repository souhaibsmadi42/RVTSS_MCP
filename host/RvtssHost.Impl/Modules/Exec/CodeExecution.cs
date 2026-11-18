namespace RvtssHost.Modules;

/// <summary>
/// Code Execution Module for Revit MCP: port of revit_mcp/code_execution.py.
/// Handles direct execution of Python code in Revit context.
///
/// pyRevit ran the code in its IronPython 2.7; the C# host has no pyRevit and embeds an IronPython 3.4 engine
/// (PyEngine.cs). The request fields, the policy checks and the response keys are those of the Python route.
/// The class _ReadOnlyDB of the Python module lives in the engine's bootstrap code (PyEngine.Bootstrap).
/// </summary>
public static class CodeExecution
{
    /// <summary>Register code execution routes with the API.</summary>
    public static void Register(RouteTable api)
    {
        // The implementation is loaded from bytes (no Location): the add-in folder is where the shell lies.
        var home = Path.GetDirectoryName(typeof(RevitDispatcher).Assembly.Location);
        if (string.IsNullOrEmpty(home))
            home = AppDomain.CurrentDomain.BaseDirectory;
        // RevitAPI / RevitAPIUI as Revit loaded them: scripts import from these very assemblies.
        PyEngine.Configure(home!, new[] { typeof(DB.Document).Assembly, typeof(UIApplication).Assembly });
        // The engine must not outlive this load of the implementation assembly.
        Entry.OnStop(PyEngine.Shutdown);

        api.Raw("/execute_code/", new[] { "POST" }, ExecuteCode, apiContext: true);
        Log.Write("Code execution routes registered successfully.");
    }

    /// <summary>
    /// Execute Python code in Revit context.
    ///
    /// Expected payload:
    /// {
    ///     "code": "python code as string",
    ///     "description": "optional description of what the code does",
    ///     "transaction_mode": "none" | "auto" | "dry_run" | "read_only"
    /// }
    ///
    /// transaction_mode (RVTSS):
    ///     none     - (default, original behaviour) no transaction is opened; the
    ///                code manages its own transactions. Required for UI operations.
    ///     auto     - the code runs inside one transaction that is committed on
    ///                success and rolled back if the code raises.
    ///     dry_run  - the code runs inside a transaction that is always rolled
    ///                back; use it to test modifying code safely.
    ///     read_only - (RVTSS 2.1) no transaction; the code may not open one
    ///                (DB.Transaction/SubTransaction/TransactionGroup are blocked) and
    ///                anything it changes anyway is rolled back and reported.
    ///
    /// Security (RVTSS 2.1): refused when RVTSS_ALLOW_CODE_EXECUTION=0 (or
    /// "allow_code_execution": false in %APPDATA%/RVTSS/config.json); every call is
    /// logged as a warning and the code is written to %APPDATA%/RVTSS/logs/code-*.log
    /// with secret-looking values redacted.
    /// </summary>
    public static Response ExecuteCode(Request request)
    {
        try
        {
            // Parse the request data
            var data = request.Data;
            if (data == null)   // Python: data.get on a body that is not a JSON object
                return new Response(new Dict { ["error"] = "'NoneType' object has no attribute 'get'" }, 500);
            var codeToExecute = data.Get("code", "");
            var description = data.Get("description", "Code execution");
            var modeValue = data.Get("transaction_mode");
            var transactionMode = (Py.Truthy(modeValue) ? Py.Str(modeValue) : "none").ToLowerInvariant();
            if (transactionMode != "none" && transactionMode != "auto" && transactionMode != "dry_run" && transactionMode != "read_only")
                return new Response(new Dict { ["error"] = "transaction_mode must be none, auto, dry_run or read_only" }, 400);

            var securitySettings = SecureApi.Settings();
            if (!Py.Truthy(securitySettings["allow_code_execution"]))
                return new Response(new Dict
                {
                    ["status"] = "error", ["error"] = "Code execution is disabled on this Revit machine",
                    ["hint"] = "RVTSS_ALLOW_CODE_EXECUTION=0 (or allow_code_execution=false in "
                               + "%APPDATA%/RVTSS/config.json). Use the dedicated RVTSS tools instead.",
                }, 403);
            if (Py.Truthy(securitySettings.Get("read_only")) && transactionMode != "read_only" && transactionMode != "dry_run")
                return new Response(new Dict
                {
                    ["status"] = "error", ["read_only"] = true,
                    ["error"] = "RVTSS runs in read-only mode: only transaction_mode 'read_only' or "
                                + "'dry_run' is allowed",
                    ["hint"] = "Both modes roll every change back. Unset RVTSS_READ_ONLY to allow changes.",
                }, 403);
            var descriptionText = Py.Str(description);
            Log.Write($"execute_revit_code called ({transactionMode}): {descriptionText}");
            Core.AuditCode(description == null ? null : descriptionText, transactionMode, codeToExecute == null ? null : Py.Str(codeToExecute));

            if (!Py.Truthy(codeToExecute))
                return new Response(new Dict { ["error"] = "No code provided" }, 400);

            return Run(request, codeToExecute!, description, descriptionText, transactionMode);
        }
        catch (Exception e)
        {
            Log.Write("Execute code request failed: " + e);
            return new Response(new Dict { ["error"] = e.Message }, 500);
        }
    }

    /// <summary>The part of the Python route from "sys.stdout = captured_output" on.</summary>
    private static Response Run(Request request, object code, object? description, string descriptionText, string transactionMode)
    {
        var doc = request.Doc;
        using var session = PyEngine.Begin(doc, request.UiDoc, request.UiApp, request.UiApp?.Application, transactionMode == "read_only");

        PyFailure? failure = null;
        var failures = new Lst();
        var codeText = code as string;
        if (codeText == null)
        {
            // exec(<not a string>, namespace)
            failure = new PyFailure { ErrorType = "TypeError", Message = "exec() arg 1 must be a string, bytes or code object" };
            failure.Traceback = HostTraceback(failure.ErrorType, failure.Message);
        }
        else if (transactionMode == "none")
        {
            failure = session.Run(codeText);
        }
        else if (transactionMode == "read_only")
        {
            long changed;
            (changed, failure) = RunReadOnly(doc, session, codeText);
            if (failure == null && changed != 0)
                return new Response(new Dict
                {
                    ["status"] = "error",
                    ["error"] = $"read_only code modified the model ({changed} element(s)); the change was "
                                + "rolled back",
                    ["hint"] = "Use transaction_mode='dry_run' or 'auto' for modifying code.",
                }, 409);
        }
        else
        {
            try
            {
                failures = Core.RunTransaction(doc!, descriptionText, () =>
                {
                    // the code raised: leave through an exception so that the transaction is rolled back
                    var f = session.Run(codeText);
                    if (f != null)
                        throw new UserCodeFailed(f);
                }, dryRun: transactionMode == "dry_run");
            }
            catch (UserCodeFailed e)
            {
                failure = e.Failure;
            }
            catch (Exception e)
            {
                // raised by run_transaction itself (read-only document, Revit rejected the commit ...)
                failure = HostFailure(e);
            }
        }

        if (failure == null)
        {
            var output = session.Output();
            return new Response(new Dict
            {
                ["status"] = transactionMode == "dry_run" ? "dry_run" : "success",
                ["transaction_mode"] = transactionMode,
                ["committed"] = transactionMode == "none" ? null : transactionMode == "auto",
                ["revit_warnings"] = failures,
                ["description"] = description,
                ["output"] = output.Length > 0 ? output : "Code executed successfully (no output)",
                ["code_executed"] = code,
            });
        }

        var partialOutput = session.Output();
        var errorType = failure.ErrorType;
        var errorMsg = failure.Message;
        var enhancedMessage = $"{errorType}: {errorMsg}";

        var hints = new Lst();
        if (errorType == "AttributeError")
        {
            if (errorMsg.IndexOf("Name", StringComparison.Ordinal) >= 0)
                hints.Add("The 'Name' property may not be directly accessible in IronPython. "
                          + "Try getattr(element, 'Name', 'N/A') or "
                          + "element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()");
            else
                hints.Add("Some Revit API properties are not directly accessible in IronPython. "
                          + "Try getattr(obj, 'property_name', default_value) for safe access.");
        }
        // IronPython reports .NET exceptions as "Exception" / "SystemError" (pyRevit's 2.7 did too, so the two .NET
        // names below never matched there): the .NET class name of the exception is checked as well.
        else if (errorType == "NullReferenceException" || failure.ClrType == "NullReferenceException"
                 || errorMsg.IndexOf("NoneType", StringComparison.Ordinal) >= 0)
        {
            hints.Add("An object is None/null. Check if elements exist before "
                      + "accessing their properties: 'if element:'");
        }
        else if (errorType == "InvalidOperationException" || failure.ClrType == "InvalidOperationException")
        {
            hints.Add("This operation may require a transaction. Wrap model-modifying "
                      + "code in: t = DB.Transaction(doc, 'desc'); t.Start(); ...; t.Commit()");
        }
        // Not in the Python route: the engine is IronPython 3 now, code written for the old tool may be Python 2.
        foreach (var hint in PyEngine.Python3Hints(errorType, errorMsg, codeText ?? ""))
            hints.Add(hint);
        if ((errorType == "ImportError" || errorType == "ModuleNotFoundError") && !PyEngine.HasStandardLibrary)
            hints.Add("The Python standard library was not found next to the add-in (" + PyEngine.StdLibZip
                      + "): only built-in modules and .NET namespaces can be imported. Reinstall / redeploy the RVTSS host.");

        Log.Write("Code execution failed: " + enhancedMessage);

        var responseData = new Dict
        {
            ["status"] = "error",
            ["error"] = enhancedMessage,
            ["error_type"] = errorType,
            ["traceback"] = failure.Traceback,
            ["code_attempted"] = code,
        };

        if (partialOutput.Length > 0)
            responseData["partial_output"] = partialOutput;

        if (hints.Count > 0)
            responseData["hints"] = hints;

        return new Response(responseData, 500);
    }

    /// <summary>
    /// Execute code inside a TransactionGroup that is always rolled back.
    ///
    /// Returns the number of elements Revit reported as changed (0 = read only).
    /// The rollback is the safety net for code that reaches the API another way.
    /// </summary>
    private static (long changed, PyFailure? failure) RunReadOnly(DB.Document? doc, PyEngine.Session session, string code)
    {
        if (doc == null)   // Python: app = doc.Application
        {
            const string message = "'NoneType' object has no attribute 'Application'";
            return (0, new PyFailure { ErrorType = "AttributeError", Message = message, Traceback = HostTraceback("AttributeError", message) });
        }
        long changed = 0;

        void OnChanged(object? sender, DB.Events.DocumentChangedEventArgs args)
        {
            try
            {
                changed += args.GetAddedElementIds().Count + args.GetModifiedElementIds().Count
                           + args.GetDeletedElementIds().Count;
            }
            catch
            {
                changed += 1;
            }
        }

        var app = doc.Application;
        DB.TransactionGroup? group = null;
        var subscribed = false;
        PyFailure? failure;
        try
        {
            app.DocumentChanged += OnChanged;
            subscribed = true;
        }
        catch { /* pass */ }
        try
        {
            if (!doc.IsModifiable && !doc.IsReadOnly)
            {
                group = new DB.TransactionGroup(doc, "RVTSS read_only code");
                group.Start();
            }
            failure = session.Run(code);
        }
        catch (Exception e)
        {
            failure = HostFailure(e);
        }
        finally
        {
            try
            {
                if (group != null && group.HasStarted() && !group.HasEnded())
                    group.RollBack();
            }
            catch (Exception e)
            {
                Log.Write("read_only code: rolling back failed: " + e.Message);
            }
            group?.Dispose();
            if (subscribed)
            {
                try { app.DocumentChanged -= OnChanged; }
                catch { /* pass */ }
            }
        }
        return (changed, failure);
    }

    /// <summary>Carries what the user's code raised out of Core.RunTransaction (which then rolls back).</summary>
    private sealed class UserCodeFailed(PyFailure failure) : Exception(failure.Message)
    {
        public PyFailure Failure { get; } = failure;
    }

    /// <summary>An exception of the host itself (not of the user's code), in the shape of the Python error branch:
    /// type(e).__name__ / str(e) / traceback. RvtssError has the same name in Python.</summary>
    private static PyFailure HostFailure(Exception e)
    {
        var name = e.GetType().Name;
        return new PyFailure { ErrorType = name, Message = e.Message, Traceback = HostTraceback(name, e.Message), ClrType = e is RvtssError ? "" : name };
    }

    private static string HostTraceback(string errorType, string message) =>
        "Traceback (most recent call last):\n  File \"<RVTSS host>\", in execute_code\n" + errorType + ": " + message + "\n";
}
