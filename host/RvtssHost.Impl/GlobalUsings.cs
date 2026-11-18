global using System;
global using System.Collections.Generic;
global using System.IO;
global using System.Linq;
global using System.Text;
global using System.Threading;
global using System.Threading.Tasks;
global using Autodesk.Revit.UI;
global using RvtssHost.Pure;
// DB.Wall, DB.FilteredElementCollector ... exactly as the Python code writes them.
global using DB = Autodesk.Revit.DB;
// JSON object / JSON array as plain CLR collections (Python dict / list).
global using Dict = System.Collections.Generic.Dictionary<string, object?>;
global using Lst = System.Collections.Generic.List<object?>;
