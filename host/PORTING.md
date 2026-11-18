# Porting RVTSS from pyRevit (IronPython) to C#

Goal: the C# add-in answers every `/revit_mcp/...` route exactly as the pyRevit extension does (same paths,
same request fields, same response keys, values, status codes and error texts), so `main.py` and `tools/*.py`
keep working unchanged. Python source of truth: `revit_mcp/*.py`. Do not edit the Python files.

## Layout

```
host/Directory.Build.props      build settings for every project, per Revit year
host/RvtssHost/                 shell add-in (HTTP server, dispatcher, loader). Do not edit.
host/RvtssHost.Impl/
  Core/      shared infrastructure, namespace RvtssHost       (core, compat, utils, query, params_util, secure_api)
  Pure/      Revit-free logic,      namespace RvtssHost.Pure  (revit_mcp/pure/*.py)
  Modules/<Group>/  route modules,  namespace RvtssHost.Modules
host/tests/Pure.Tests/          console tests for Pure/ against vectors from the Python originals
```

## Naming (deterministic, so files written in parallel fit together)

* One Python module -> one `public static class` in one file, PascalCase of the module name:
  `family_utils.py` -> `FamilyUtils` in `FamilyUtils.cs`; `pure/units.py` -> `Units` in `Pure/Units.cs`.
  The Python aliases map as `U` -> `Units`, `F` -> `Filters`, `R` -> `Rules`, `VA` -> `ViewAudit`, `P`/`PU` -> `ParamsUtil`.
* Function `snake_case` -> `PascalCase` method, **same parameter order, same defaults**. Leading-underscore
  helpers become `private` (or `internal` when another module calls them), without the underscore.
* Module constants `UPPER_CASE` -> `PascalCase` (`MAX_COMMANDS` -> `MaxCommands`).
* Keep every function, including ones that look unused: other modules call them by this convention.
* Keep the Python docstrings as `///` summaries and keep comments that explain why.

## Data model

Request and response data are plain values: `Dict` (= `Dictionary<string, object?>`), `Lst` (= `List<object?>`),
`string`, `long`, `double`, `bool`, `null`. JSON integers arrive as `long`, never `int`.

* Build responses with `new Dict { ["key"] = value }` and `new Lst { ... }`. Never anonymous objects or tuples.
  Keep the key order of the Python dict literal.
* Anything put in a response is cleaned on the way out (`Py.Clean`): `ElementId` -> integer, enums -> name,
  NaN/inf -> null, any other object -> `ToString()`. Typed lists (`List<string>`, `List<Dict>`) are fine in responses.
* Function signatures: use real types where the Python value has one type (`string unit`, `DB.Document doc`,
  `DB.Element e`, `bool`, `double`); use `object?` for values that come straight from the request and may be an
  id or a name (`object? level`, `object? view`, `object? category`).
* Return types: `Dict` / `Lst` / typed lists / Revit types. A Python function returning a tuple returns a C#
  tuple `(A a, B b)`.

`Py` (Core/Py.cs) has the Python-flavoured helpers. Read it before porting. The main ones:
`d.Get(key, default)`, `d.SetDefault`, `d.Update`, `d.Pop`, `Py.Truthy(v)`, `Py.Str(v)` (Python `str()`),
`Py.ToInt/ToFloat/TryInt/TryFloat`, `Py.IsStr/IsInt/IsNum`, `Py.AsDict/AsList/ListOf`, `Py.Round(v, nd)`
(always use it for Python `round`), `Py.GetAttr/HasAttr`, `Py.EnumOrNull<T>(name)` (for `getattr(DB.Enum, name, None)`),
`Py.CloseMatches` (difflib), `Py.JsonLoads/JsonDumps`.

Python semantics to preserve:
* `x or default`, `if x:` on request values -> `Py.Truthy`. `dict.get(k)` -> `d.Get(k)`; missing key is null, not an exception.
* `str(x)` of a number/None/bool in a message or key -> `Py.Str(x)`. `"{}".format(revit_enum)` -> `.ToString()`.
* `.lower()/.upper()` -> `ToLowerInvariant()/ToUpperInvariant()`. Number parsing and formatting: `CultureInfo.InvariantCulture`.
* `sorted(...)` on strings -> `OrderBy(x => x, StringComparer.Ordinal)`.
* Integer division, `%` on negatives, slicing with negative indexes: write them out carefully.
* `isinstance(v, basestring)` -> `v is string`; `isinstance(v, (int, long))` -> `Py.IsInt(v)`; `isinstance(v, dict)` -> `v is Dict`.
* A bare `except Exception: pass/continue` stays a `try { } catch { }` at the same place: many Revit calls throw.

## Revit API

* `DB.` works as in Python (`global using DB = Autodesk.Revit.DB`): `DB.Wall`, `new DB.FilteredElementCollector(doc)`.
* `isinstance(e, DB.Wall)` -> `e is DB.Wall w`. `OfClass(DB.Level)` -> `OfClass(typeof(DB.Level))`.
* `getattr(obj, "Prop", None)` on Revit objects: use a type test (`(t as DB.ElementType)?.FamilyName`) when you can
  tell the type; `Py.GetAttr` only when it is truly dynamic.
* Element ids: `e.Id.Value` (long). `Compat.MakeId(object)` -> `ElementId`, `Compat.IdInt(...)`, `Compat.IsValidId(id)`.
* Iterating `ParameterSet`, `CategoryNameMap`, `DocumentSet`...: `foreach (DB.Parameter p in e.Parameters)` or `.Cast<T>()`.
* The code must compile for Revit 2024, 2025, 2026 and 2027. Drop the Python shims for Revit 2023 and older
  (ParameterType, BuiltInParameterGroup, Int32 ElementId, `IntegerValue`): use `ForgeTypeId` / `SpecTypeId` /
  `GroupTypeId` / `ElementId.Value` only. Where the API differs between these four years use
  `#if REVIT2024`, `#if REVIT2025_OR_GREATER`, `#if REVIT2026_OR_GREATER`, `#if REVIT2027_OR_GREATER`.
* pyRevit helpers (`pyrevit.revit`, `HOST_APP`, `revit.doc`, `routes`, `forms`) do not exist. Use
  `Hosting.UiApp` / `Hosting.App` / `Hosting.RevitYear`, `ctx.UiApp`, `ctx.App`, `request.Doc`, `request.UiDoc`.

## Routes

A module with routes has `public static void Register(RouteTable api)`; it is found by reflection (no central list).
Keep the exact route paths and HTTP methods.

Python `handle()` routes:

```python
@api.route("/find_elements/", methods=["POST"])
def find_elements_route(doc, uidoc, request):
    return handle(doc, request, find_elements, uidoc=uidoc)
```
```csharp
api.Post("/find_elements/", FindElements, "find_elements");        // name = the Python impl function name
public static Dict? FindElements(Ctx ctx) { ... }                   // was: def find_elements(ctx)
```
`needs_doc=False` -> `needsDoc: false`; `name="x"` -> that name. `ctx.uidoc` is always available as `ctx.UiDoc`.

`Ctx` (Core/Ctx.cs): `ctx.Doc`, `ctx.UiDoc`, `ctx.ActiveDoc`, `ctx.Data`, `ctx.Get(key, def)`, `ctx.Require(key)`,
`ctx.Bool(key, def)`, `ctx.Int(key, def, min, max)` (`long?`), `ctx.I(key, def, min, max)` (`int`, when there is a
default), `ctx.Float(key, def)` (`double?`), `ctx.F(key, def)` (`double`), `ctx.List(key)`, `ctx.Str(key, def)`,
`ctx.Unit`, `ctx.DryRun`, `ctx.Confirmed`, `ctx.Warn(msg)`.

Legacy routes that build their own response (`routes.make_response(data=..., status=...)`):

```csharp
api.Raw("/status/", new[] { "GET" }, request => new Response(new Dict { ... }, 200), apiContext: true);
```
`apiContext: true` when the Python handler takes `doc` and/or `uidoc` (it then runs on Revit's main thread and
`request.Doc` / `request.UiDoc` / `request.UiApp` are set); `false` when it takes only `request` or nothing.
`request.Data` is the parsed JSON body (`Dict`, null if the body is not a JSON object), `request.Query` the query string.

Errors: `raise RvtssError("msg", status=404, hint="...", key=value)` ->
`throw new RvtssError("msg", status: 404, hint: "...").With("key", value);`. `core.not_found(...)` -> `throw Core.NotFound(...)`.
Keep message texts character for character.

`Core` (Core/Core.cs) is the port of `core.py`: `Core.RunTransaction(doc, name, () => ..., dryRun)` returns
`(result, failures)`; `Core.Batch`, `Core.CommitResult`, `Core.ConfirmGate`, `Core.PreviewStatus`, `Core.GetElement(s)`,
`Core.ResolveCategory`, `Core.FindLevel/FindView/FindType`, `Core.ElementBrief/ElementLevel/ElementLocation/ElementPoint/ElementBbox`,
`Core.XyzList`, `Core.ToIdList`, `Core.RequireProject/RequireFamily/RequireWritable/CheckModifiable`, `Core.ReadOnlyResponse`,
`Core.FilePolicyResponse`, `Core.RvtssHome/RvtssSubdir/LoadConfig/LoadQcRules`, `Core.Ok/Respond/ErrorResponse`,
`Core.AuditCode`, `Core.ConfirmThreshold`, `Core.MaxLimit`. Read the file for exact signatures.

## Must compile on .NET Framework 4.8 (Revit 2024) and .NET 8 / 10

C# language features are fine (latest C#, PolySharp provides the compiler polyfills). These library members do
**not** exist on .NET Framework 4.8, so do not use them:

`Math.Clamp` (use `Py.Clamp`), `dict.TryAdd`, `dict.GetValueOrDefault`, `dict.Remove(key, out v)`,
`string.Split(string)` / `Split(char, options)` (use `Split(new[] { ',' })`, `Split(new[] { "ab" }, StringSplitOptions.None)`),
`string.Contains(char)`, `string.Contains(s, StringComparison)`, `StartsWith(char)` / `EndsWith(char)`,
`string.Join(char, ...)`, `string.Replace(a, b, StringComparison)`, `MinBy` / `MaxBy` / `DistinctBy` / `Chunk` / `TakeLast` / `SkipLast`,
`Path.GetRelativePath`, `File.*Async`, `Convert.ToHexString`, `HashCode`, `Random.Shared`,
`ArgumentNullException.ThrowIfNull`, `Enum.GetValues<T>()` / `Enum.GetNames<T>()` (use the `typeof` forms),
`StringBuilder.AppendJoin`, `KeyValuePair.Create`, ranges on arrays (`arr[1..]`), `Span` / `Memory` APIs,
`Environment.ProcessPath`, `Stopwatch.GetElapsedTime`, `Task.WaitAsync`, `Dictionary.EnsureCapacity`.
`string` ranges (`s[1..]`) are also best written as `Substring`.

## Build check

```
dotnet build host/RvtssHost.Impl -c Release -p:RevitYear=2026 -p:Lane=<your lane> [-p:Group=<your Modules folder>] -nologo -v q
dotnet build host/RvtssHost.Impl -c Release -p:RevitYear=2024 -p:Lane=<your lane> [-p:Group=<your Modules folder>] -nologo -v q
```
`Lane` gives your build its own obj/out folders: several people build at once. `Group` compiles only
`Modules/<Group>` plus Core and Pure. Your files must build with 0 errors for both years. Errors in files that are
not yours (someone is still writing them): report them, do not fix them.

Do not start or close Revit, do not touch `%APPDATA%\Autodesk`, do not run git commands that change anything.

## URL parameters

A route path with a pyRevit `<name>` segment (`/get_view/<view_name>`) is registered with the same path text;
the value is in `request.UrlParams["view_name"]` (already URL-decoded).

## Comparing with the reference

pyRevit serves the reference implementation on `http://127.0.0.1:48884/revit_mcp` whenever Revit runs. For every
route you port, add read-only / dry-run cases to `host/tests/compare/cases/<Group>.json` (format: see
`host/tests/compare/compare_routes.py`). `uv run --project . python host/tests/compare/compare_routes.py <Group> --ref-only`
prints what pyRevit answers, which is the exact shape (keys, value types, error texts) your port must produce.
Only send requests that do not change the model: reads, `dry_run: true`, and requests that are expected to fail
validation. Never send a request that modifies, saves, closes or opens anything.
