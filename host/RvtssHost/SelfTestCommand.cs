using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RvtssHost;

/// <summary>Ribbon button "Run Self-Test": the work is Entry.RunSelfTest in the routes assembly.</summary>
[Transaction(TransactionMode.Manual)]
public sealed class SelfTestCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        try
        {
            var loader = App.Loader ?? throw new InvalidOperationException("RVTSS Host did not start (see %APPDATA%/RVTSS/logs).");
            loader.InvokeEntry("RunSelfTest", commandData.Application);
            return Result.Succeeded;
        }
        catch (Exception e)
        {
            Log.Write("Self-test failed to run: " + e);
            message = "RVTSS self-test could not run: " + e.Message;
            return Result.Failed;
        }
    }
}
