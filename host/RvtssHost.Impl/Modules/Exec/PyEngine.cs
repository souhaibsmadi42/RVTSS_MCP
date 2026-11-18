using System.Reflection;
using System.Text.RegularExpressions;
using IronPython.Hosting;
using Microsoft.Scripting.Hosting;

namespace RvtssHost.Modules;

/// <summary>What user code raised: the three values the Python route took from the exception.</summary>
internal sealed class PyFailure
{
    /// <summary>type(exec_error).__name__</summary>
    public string ErrorType = "";
    /// <summary>str(exec_error)</summary>
    public string Message = "";
    /// <summary>traceback.format_exc()</summary>
    public string Traceback = "";
    /// <summary>Class name of the .NET exception when the error came from .NET (Revit), else "".
    /// IronPython reports every .NET exception it has no Python class for as plain "Exception".</summary>
    public string ClrType = "";
}

/// <summary>
/// The embedded IronPython 3 engine behind /execute_code/ (pyRevit ran the code in its own IronPython 2.7).
///
/// This file has no Revit and no RvtssHost dependency on purpose: host/tests/Exec.Tests compiles the same file
/// and runs it outside Revit, loaded from bytes the way ImplLoader loads the implementation.
///
/// One engine per load of the implementation assembly: created on first use, shut down by <see cref="Shutdown"/>
/// (registered with Entry.OnStop), so a reload does not leave an engine behind.
/// </summary>
internal static class PyEngine
{
    /// <summary>The standard library, packed by the build (RvtssHost.Impl.csproj, target PackPythonStdLib).</summary>
    public const string StdLibZip = "IronPython.StdLib.zip";

    /// <summary>File name of the bootstrap code in tracebacks (its frames are removed from what the caller sees).</summary>
    private const string HostFile = "rvtss_host.py";   // no "<...>": .NET Framework rejects it as a path

    private static readonly object Gate = new();
    private static ScriptEngine? _engine;
    private static ScriptScope? _host;
    private static object? _begin, _run, _end;

    // Set by Configure before the first use.
    private static string _homeDir = "";
    private static Assembly[] _assemblies = new Assembly[0];
    private static string _dbNamespace = "Autodesk.Revit.DB";
    private static string _uiNamespace = "Autodesk.Revit.UI";

    /// <summary>Search path entries that exist (shown in diagnostics and by the tests).</summary>
    public static List<string> SearchPaths { get; private set; } = new();

    public static bool IsCreated => _engine != null;

    /// <summary>False when neither IronPython.StdLib.zip nor a Lib folder lies in the add-in folder.</summary>
    public static bool HasStandardLibrary =>
        File.Exists(Path.Combine(_homeDir, StdLibZip)) || Directory.Exists(Path.Combine(_homeDir, "Lib"));

    /// <summary>
    /// homeDir: the add-in folder (IronPython.StdLib.zip, optional Lib and site-packages folders).
    /// assemblies: already loaded assemblies scripts may import from without clr.AddReference (RevitAPI, RevitAPIUI).
    /// </summary>
    public static void Configure(string homeDir, IEnumerable<Assembly> assemblies,
        string dbNamespace = "Autodesk.Revit.DB", string uiNamespace = "Autodesk.Revit.UI")
    {
        _homeDir = homeDir;
        _assemblies = assemblies.ToArray();
        _dbNamespace = dbNamespace;
        _uiNamespace = uiNamespace;
    }

    private static ScriptEngine Engine()
    {
        lock (Gate)
        {
            if (_engine != null)
                return _engine;
            var options = new Dictionary<string, object>
            {
                // sys._getframe for the standard library (logging, collections.namedtuple, inspect)
                ["Frames"] = true,
            };
            var engine = Python.CreateEngine(options);
            try
            {
                var paths = new List<string>();
                // A loose Lib folder (development) wins over the packed library; site-packages is for the user's own modules.
                foreach (var name in new[] { "Lib", StdLibZip, Path.Combine("Lib", "site-packages"), "site-packages" })
                {
                    var p = Path.Combine(_homeDir, name);
                    if (Directory.Exists(p) || File.Exists(p))
                        paths.Add(p);
                }
                engine.SetSearchPaths(paths);
                SearchPaths = paths;

                // The assemblies are already loaded in this process (by Revit): hand the very same ones to the engine,
                // so "from Autodesk.Revit.DB import *" works without clr.AddReference and never loads a second copy.
                foreach (var a in _assemblies)
                    engine.Runtime.LoadAssembly(a);
                engine.Runtime.LoadAssembly(typeof(Enumerable).Assembly);   // System.Core / System.Linq

                var host = engine.CreateScope();
                host.SetVariable("_assemblies", _assemblies);
                engine.CreateScriptSourceFromString(
                    Bootstrap.Replace("@DB@", _dbNamespace).Replace("@UI@", _uiNamespace).Replace("@HOST@", HostFile),
                    HostFile, Microsoft.Scripting.SourceCodeKind.File).Execute(host);
                _begin = host.GetVariable<object>("_begin");
                _run = host.GetVariable<object>("_run");
                _end = host.GetVariable<object>("_end");
                _host = host;
                _engine = engine;
                return engine;
            }
            catch
            {
                try { engine.Runtime.Shutdown(); } catch { /* best effort */ }
                throw;
            }
        }
    }

    /// <summary>Stops the engine. The next request creates a new one.</summary>
    public static void Shutdown()
    {
        lock (Gate)
        {
            var engine = _engine;
            _engine = null;
            _host = null;
            _begin = _run = _end = null;
            if (engine == null)
                return;
            try { engine.Runtime.Shutdown(); } catch { /* best effort */ }
            try { FlushExpressionCaches(); } catch { /* best effort */ }
        }
    }

    /// <summary>
    /// System.Linq.Expressions keeps two small static caches keyed by delegate type (Expression.Lambda). The DLR
    /// fills them with delegate types built from IronPython's own types, and such an entry keeps the whole
    /// collectible load context of the implementation (engine included) alive after a reload. Measured with
    /// host/tests/Exec.Tests: without this, "import decimal" or a few ordinary scripts pin the context for good.
    /// The caches are fixed-size hash tables (at most 64 slots) where a new key overwrites its slot, so a thousand
    /// lambdas over framework-only delegate types push every IronPython entry out.
    /// </summary>
    private static void FlushExpressionCaches()
    {
#if NET
        var types = new List<Type>();
        foreach (var t in new[] { typeof(int), typeof(string), typeof(object), typeof(double), typeof(long), typeof(bool), typeof(char), typeof(byte) })
            for (var rank = 0; rank < 4; rank++)
                types.Add(rank == 0 ? t : t.MakeArrayType(rank));
        foreach (var a in types)
            foreach (var b in types)
                System.Linq.Expressions.Expression.Lambda(typeof(Func<,>).MakeGenericType(a, b),
                    System.Linq.Expressions.Expression.Default(b), System.Linq.Expressions.Expression.Parameter(a));
#endif
    }

    /// <summary>
    /// Calls a Python callable. The hosting API returns C# `dynamic`; it must become `object` at once and no
    /// expression in this file may operate on a `dynamic` value: the C# runtime binder caches its call sites in
    /// statics of Microsoft.CSharp (default load context), which keeps the collectible context of the
    /// implementation alive after a reload (measured with host/tests/Exec.Tests).
    /// </summary>
    private static object? Call(ScriptEngine engine, object? callable, params object?[] args)
    {
        object? result = engine.Operations.Invoke(callable, args);
        return result;
    }

    /// <summary>
    /// Runs a whole script in its own scope with the given variables (the self-test plan). Output is not
    /// captured. Returns null when it ran to its end, else the formatted Python traceback.
    /// </summary>
    public static string? RunFile(string source, string fileName, IDictionary<string, object?> variables)
    {
        var engine = Engine();
        var scope = engine.CreateScope();
        foreach (var kv in variables)
            scope.SetVariable(kv.Key, kv.Value);
        try
        {
            engine.CreateScriptSourceFromString(source, fileName, Microsoft.Scripting.SourceCodeKind.File).Execute(scope);
            return null;
        }
        catch (Exception e)
        {
            try { return engine.GetService<ExceptionOperations>().FormatException(e); }
            catch { return e.ToString(); }
        }
    }

    /// <summary>
    /// Builds the namespace of one execution and starts capturing print output
    /// (the Python route: sys.stdout = StringIO(); namespace = {...}). Dispose restores sys.stdout.
    /// </summary>
    public static Session Begin(object? doc, object? uidoc, object? uiapp, object? app, bool readOnly)
    {
        var engine = Engine();
        var r = (IList<object?>)Call(engine, _begin, doc, uidoc, uiapp, app, readOnly)!;
        return new Session(engine, r[0], r[1], r[2]);
    }

    internal sealed class Session : IDisposable
    {
        private readonly ScriptEngine _eng;
        private readonly object? _namespace, _captured, _oldStdout;
        private bool _closed;

        internal Session(ScriptEngine engine, object? ns, object? captured, object? oldStdout)
        {
            _eng = engine;
            _namespace = ns;
            _captured = captured;
            _oldStdout = oldStdout;
        }

        /// <summary>exec(code, namespace). Null when the code ran to its end, else what it raised.</summary>
        public PyFailure? Run(string code)
        {
            object? r;
            try
            {
                r = Call(_eng, _run, code, _namespace);
            }
            catch (Exception e)
            {
                // Not an Exception for Python (SystemExit from sys.exit(), KeyboardInterrupt, GeneratorExit):
                // the runner lets those through, like "except Exception" in the Python route did.
                var name = e.GetType().Name;
                if (name.EndsWith("Exception", StringComparison.Ordinal) && name.StartsWith("System", StringComparison.Ordinal)
                    && name.Length > "SystemException".Length)
                    name = name.Substring(0, name.Length - "Exception".Length);   // SystemExitException -> SystemExit
                string trace;
                try { trace = _eng.GetService<ExceptionOperations>().FormatException(e); }
                catch { trace = e.ToString(); }
                return new PyFailure { ErrorType = name, Message = e.Message, Traceback = trace };
            }
            if (r == null)
                return null;
            var t = (IList<object?>)r;
            return new PyFailure { ErrorType = Text(t[0]), Message = Text(t[1]), Traceback = Text(t[2]), ClrType = Text(t[3]) };
        }

        /// <summary>captured_output.getvalue()</summary>
        public string Output()
        {
            if (_closed)
                return "";
            try { return Text(Call(_eng, _eng.Operations.GetMember<object>(_captured, "getvalue"))); }
            catch (Exception e) { return "<<output unavailable: " + e.Message + ">>"; }
        }

        public void Dispose()
        {
            if (_closed)
                return;
            _closed = true;
            try { Call(_eng, _end, _captured, _oldStdout); } catch { /* engine already stopped */ }
        }

        private static string Text(object? v) => v?.ToString() ?? "";
    }

    // ------------------------------------------------------------------ hints

    private static readonly Regex Py2Print = new(@"(^|[;:])[ \t]*print[ \t]*(>>|[ \t][""'\w\-\[{%])", RegexOptions.Multiline);
    private static readonly Regex Py2Except = new(@"^[ \t]*except[ \t]+[\w.]+[ \t]*,[ \t]*\w+[ \t]*:", RegexOptions.Multiline);
    private static readonly Regex Py2Raise = new(@"^[ \t]*raise[ \t]+[\w.]+[ \t]*,", RegexOptions.Multiline);
    private static readonly string[] Py2DictMethods = { "iteritems", "itervalues", "iterkeys", "has_key" };

    /// <summary>
    /// Hints for code written for the IronPython 2.7 of the pyRevit version of this tool (the engine is Python 3 now).
    /// Returned in addition to the hints of the original route.
    /// </summary>
    public static List<string> Python3Hints(string errorType, string errorMessage, string code)
    {
        var hints = new List<string>();
        if (errorType == "SyntaxError")
        {
            if (Py2Print.IsMatch(code))
                hints.Add("This looks like a Python 2 print statement. The code runs under IronPython 3: "
                          + "write print(value) with parentheses, e.g. print(\"walls:\", count).");
            if (Py2Except.IsMatch(code))
                hints.Add("Python 3 syntax: write 'except SomeError as e:' instead of 'except SomeError, e:'.");
            if (Py2Raise.IsMatch(code))
                hints.Add("Python 3 syntax: write 'raise SomeError(\"message\")' instead of 'raise SomeError, \"message\"'.");
        }
        else if (errorType == "AttributeError")
        {
            foreach (var m in Py2DictMethods)
                if (errorMessage.IndexOf(m, StringComparison.Ordinal) >= 0)
                {
                    hints.Add("Python 3: dict.iteritems()/itervalues()/iterkeys() are items()/values()/keys(), "
                              + "and d.has_key(k) is 'k in d'.");
                    break;
                }
        }
        else if (errorType == "ImportError" || errorType == "ModuleNotFoundError")
        {
            if (errorMessage.IndexOf("pyrevit", StringComparison.Ordinal) >= 0 || code.IndexOf("pyrevit", StringComparison.Ordinal) >= 0)
                hints.Add("pyRevit is not available in the RVTSS host. Only 'from pyrevit import revit, DB, UI, HOST_APP' "
                          + "is emulated; use doc, uidoc, DB, UI and the Revit API directly.");
            else if (errorMessage.IndexOf("StringIO", StringComparison.Ordinal) >= 0)
                hints.Add("Python 3: use 'from io import StringIO'.");
        }
        return hints;
    }

    // ------------------------------------------------------------- bootstrap
    // Runs once per engine. Everything a script sees that is not a Revit object is defined here, in Python,
    // so its behaviour (exception types, str(), traceback) is the interpreter's own.
    private const string Bootstrap = @"
import sys, io, re, traceback, linecache, functools, types
import clr, System

for _a in _assemblies:
    try:
        clr.AddReference(_a)
    except Exception:
        pass

import @DB@ as _DB
import @UI@ as _UI


class _State(object):
    doc = None
    uidoc = None
    uiapp = None
    app = None

_state = _State()


class _Revit(object):
    '''Stand-in for pyRevit's `revit` module: the objects of the request being executed.'''
    doc = property(lambda self: _state.doc)
    uidoc = property(lambda self: _state.uidoc)
    uiapp = property(lambda self: _state.uiapp)
    app = property(lambda self: _state.app)
    docs = property(lambda self: list(_state.app.Documents) if _state.app is not None else [])
    active_view = property(lambda self: _state.doc.ActiveView if _state.doc is not None else None)
    version = property(lambda self: _state.app.VersionNumber if _state.app is not None else None)
    DB = _DB
    UI = _UI

    def get_selection(self):
        if _state.uidoc is None:
            return []
        return [_state.doc.GetElement(i) for i in _state.uidoc.Selection.GetElementIds()]

    def __repr__(self):
        return '<RVTSS revit context (pyRevit is not loaded)>'

revit = _Revit()

# 'from pyrevit import revit, DB, UI, HOST_APP' keeps working; the rest of pyRevit does not exist here.
_pyrevit = types.ModuleType('pyrevit')
_pyrevit.__doc__ = 'RVTSS stand-in for pyRevit: only revit, DB, UI and HOST_APP.'
_pyrevit.revit = revit
_pyrevit.DB = _DB
_pyrevit.UI = _UI
_pyrevit.HOST_APP = revit
sys.modules['pyrevit'] = _pyrevit


class _ReadOnlyDB(object):
    '''DB namespace for read_only code: transaction classes are blocked.'''

    _BLOCKED = ('Transaction', 'SubTransaction', 'TransactionGroup')

    def __getattr__(self, name):
        if name in self._BLOCKED:
            raise RuntimeError(""read_only mode: DB.{} is not allowed. Use transaction_mode='auto' or ""
                               ""'dry_run' for code that modifies the model."".format(name))
        return getattr(_DB, name)

    def __dir__(self):
        return dir(_DB)


def _begin(doc, uidoc, uiapp, app, read_only):
    _state.doc = doc
    _state.uidoc = uidoc
    _state.uiapp = uiapp
    _state.app = app
    old_stdout = sys.stdout
    captured_output = io.StringIO()
    sys.stdout = captured_output
    namespace = {
        '__name__': '__main__',
        'doc': doc,
        'uidoc': uidoc,
        'uiapp': uiapp,
        'app': app,
        '__revit__': uiapp,
        'DB': _ReadOnlyDB() if read_only else _DB,
        'UI': _UI,
        'revit': revit,
        'clr': clr,
        'System': System,
        # names Python 2 code uses
        'unicode': str,
        'basestring': str,
        'long': int,
        'xrange': range,
        'reduce': functools.reduce,
    }
    return (namespace, captured_output, old_stdout)


_HOST_FRAME = re.compile(r'  File ""@HOST@"", line \d+, in \w+\n')


def _run(code, namespace):
    try:
        # so the traceback shows the source lines of the submitted code
        linecache.cache['<string>'] = (len(code), None, code.splitlines(True), '<string>')
        exec(compile(code, '<string>', 'exec'), namespace)
        return None
    except Exception as exec_error:
        tb = exec_error.__traceback__
        while tb is not None and tb.tb_frame.f_code.co_filename == '@HOST@':
            tb = tb.tb_next          # drop this function's own frame
        try:
            text = ''.join(traceback.format_exception(type(exec_error), exec_error, tb))
        except Exception:
            text = traceback.format_exc()
        text = _HOST_FRAME.sub('', text)
        # IronPython has no Python class for most .NET exceptions (all of Revit's): they are plain 'Exception'.
        clr_type = ''
        try:
            cls = exec_error.clsException if type(exec_error) in (Exception, SystemError) else None
            if cls is not None and not (cls.GetType().Namespace or '').startswith(('IronPython', 'Microsoft.Scripting')):
                clr_type = cls.GetType().Name
        except Exception:
            pass
        return (type(exec_error).__name__, str(exec_error), text, clr_type)


def _end(captured_output, old_stdout):
    sys.stdout = old_stdout
    _state.doc = _state.uidoc = _state.uiapp = _state.app = None
    try:
        captured_output.close()
    except Exception:
        pass
";
}
