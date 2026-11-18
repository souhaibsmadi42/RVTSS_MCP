using System.Diagnostics;
using System.Reflection;
using RvtssHost.Modules;

namespace RvtssHost.Tests;

/// <summary>The checks. Runs inside the context the launcher built, against the real PyEngine.cs.</summary>
public static class Checks
{
    private static int _failed;
    private static object? _doc, _uidoc, _app;
    private static string _layout = "";

    private static void Check(string name, bool ok, string? detail = null)
    {
        if (!ok)
            _failed++;
        Console.WriteLine((ok ? "  ok    " : "  FAIL  ") + name + (ok || detail == null ? "" : "\n          " + detail.Replace("\n", "\n          ")));
    }

    /// <summary>One execution the way the route does it: (output, failure).</summary>
    private static (string output, PyFailure? failure) Exec(string code, bool readOnly = false)
    {
        using var session = PyEngine.Begin(_doc, _uidoc, "uiapp", _app, readOnly);
        var failure = session.Run(code);
        return (session.Output(), failure);
    }

    private static void Ok(string name, string code, string expectedOutput, bool readOnly = false)
    {
        var (output, failure) = Exec(code, readOnly);
        Check(name, failure == null && output == expectedOutput,
            failure != null ? failure.ErrorType + ": " + failure.Message + "\n" + failure.Traceback : "output: " + Show(output) + "\nwanted: " + Show(expectedOutput));
    }

    private static PyFailure Fails(string name, string code, string errorType, string? messageContains = null, bool readOnly = false)
    {
        var (_, failure) = Exec(code, readOnly);
        var ok = failure != null && failure.ErrorType == errorType
                 && (messageContains == null || failure.Message.IndexOf(messageContains, StringComparison.Ordinal) >= 0);
        Check(name, ok, failure == null ? "no error" : failure.ErrorType + ": " + failure.Message);
        return failure ?? new PyFailure();
    }

    private static string Show(string s) => "\"" + s.Replace("\n", "\\n") + "\"";

    /// <summary>Development aid: EXEC_LEAK_PROBE=load|create|bare|run|import|class|clr|error|netclass|&lt;python code&gt; runs just that, so the
    /// launcher (--bytes-only) tells whether it keeps the load context alive.</summary>
    private static int LeakProbe(string what)
    {
        Console.WriteLine("  leak probe: " + what);
        if (what == "load")
        {
            Console.WriteLine("  " + typeof(IronPython.Hosting.Python).Assembly.FullName);
            return 0;
        }
        if (what == "create")
        {
            var e = IronPython.Hosting.Python.CreateEngine();
            e.Runtime.Shutdown();
            return 0;
        }
        if (what == "bare")
        {
            var e = IronPython.Hosting.Python.CreateEngine();
            e.Execute("x = 1 + 1");
            e.Runtime.Shutdown();
            return 0;
        }
        // anything else is Python code, run through PyEngine like a request
        var code = what == "run" ? "x = 1" : what == "import" ? "import json, re, os, collections" : what == "class" ? "class A(object):\n    pass\nA()"
            : what == "clr" ? "from System.Collections.Generic import List\nl = List[int]()\nf = System.Func[int, int](lambda x: x + 1)\nf(1)\nprint(doc.Title, DB.Wall)"
            : what == "error" ? "1/0" : what == "netclass" ? "class W(DB.Element):\n    pass\nW()" : what;
        using (var s = PyEngine.Begin(_doc, _uidoc, "uiapp", _app, false))
        {
            var f = s.Run(code);
            Console.WriteLine("  -> " + (f == null ? "ok" : f.ErrorType + ": " + f.Message) + "  output: " + Show(s.Output()));
        }
        PyEngine.Shutdown();
        return 0;
    }

    /// <summary>The scripts of the "reload" pass: what a session of normal use looks like, then Shutdown.</summary>
    private static int Typical()
    {
        Ok("typical: prints, json, re, os, math, collections, itertools, traceback, datetime, csv",
            "import json, math, re, os, sys, traceback, collections, itertools, datetime, csv, io, time, random, functools, operator, string, copy\n"
            + "rows = [collections.OrderedDict([('id', i), ('name', 'w%d' % i)]) for i in range(3)]\nprint(json.dumps(rows))\n"
            + "P = collections.namedtuple('P', 'x y')\nprint(P(1, 2), re.findall('[0-9]', 'a1b2'), math.sqrt(16), datetime.date(2026, 1, 2).isoformat())",
            "[{\"id\": 0, \"name\": \"w0\"}, {\"id\": 1, \"name\": \"w1\"}, {\"id\": 2, \"name\": \"w2\"}]\nP(x=1, y=2) ['1', '2'] 4.0 2026-01-02\n");
        Ok("typical: Revit-style API use, classes, .NET generics, delegates, LINQ",
            "from System.Collections.Generic import List\nimport System.Linq\nclr.ImportExtensions(System.Linq)\nfrom Fake.DB import *\n"
            + "class Info(object):\n    def __init__(self, e):\n        self.name = e.Describe()\n"
            + "class W(DB.Element):\n    def Describe(self):\n        return 'python wall'\n"
            + "ids = List[int]([3, 1, 2])\nprint(Info(Wall()).name, DB.Thrower.CallDescribe(W()), ids.Where(lambda x: x > 1).Count(), revit.doc.Title,\n"
            + "      sorted(ids, key=lambda x: -x), System.Func[int, int](lambda x: x * 2)(21), unicode(long(5)), list(xrange(2)))",
            "element python wall 2 Fake Project [3, 2, 1] 42 5 [0, 1]\n");
        Fails("typical: Python error", "def f():\n    return {}['k']\nf()", "KeyError");
        Fails("typical: .NET error", "DB.Thrower.RevitInvalidOperation()", "Exception");
        Fails("typical: syntax error", "print \"x\"", "SyntaxError");
        Fails("typical: read_only block", "DB.Transaction(doc, 'x')", "RuntimeError", readOnly: true);
        Fails("typical: sys.exit", "import sys\nsys.exit(0)", "SystemExit");
        for (var i = 0; i < 30; i++)
            Exec("total = sum(i * i for i in range(2000))\nprint(total)");
        Check("typical: 30 more executions", true);
        PyEngine.Shutdown();
        Ok("typical: engine restarted after Shutdown", "import json\nprint(json.dumps({'a': 1}))", "{\"a\": 1}\n");
        PyEngine.Shutdown();
        return _failed;
    }

    public static int Run(string layout, Assembly fakeApi, string mode)
    {
        _failed = 0;
        _layout = layout;
        _doc = Activator.CreateInstance(fakeApi.GetType("Fake.DB.Document", true)!);
        _uidoc = Activator.CreateInstance(fakeApi.GetType("Fake.UI.UIDocument", true)!);
        _app = _doc!.GetType().GetProperty("Application")!.GetValue(_doc);
        PyEngine.Configure(layout, new[] { fakeApi }, "Fake.DB", "Fake.UI");

        var probe = Environment.GetEnvironmentVariable("EXEC_LEAK_PROBE");
        if (probe != null)
            return LeakProbe(probe);
        if (mode == "typical")
            return Typical();

        var watch = Stopwatch.StartNew();
        Ok("engine starts, print is captured", "print('hello', 1)\nprint('a', 'b', sep='-', end='!')\nimport sys\nsys.stdout.write('w')", "hello 1\na-b!w");
        Console.WriteLine($"        (engine created and first script run in {watch.ElapsedMilliseconds} ms)");
        Check("engine assemblies come from " + (typeof(IronPython.Hosting.Python).Assembly.Location.Length == 0 ? "bytes" : "file"), true);
        Check("search path is the packed standard library of the layout",
            PyEngine.SearchPaths.Count == 1 && PyEngine.SearchPaths[0] == Path.Combine(layout, PyEngine.StdLibZip), string.Join(";", PyEngine.SearchPaths));
        var (version, _) = Exec("import sys\nprint(sys.version)\nprint(sys.implementation.name)");
        Console.WriteLine("        " + version.Trim().Replace("\n", " | "));

        // ---- standard library from IronPython.StdLib.zip
        Ok("import json, math, re, os, sys, traceback, collections, itertools",
            "import json, math, re, os, sys, traceback, collections, itertools\n"
            + "d = collections.OrderedDict([('b', 1), ('a', [1, 2.5, None, True])])\n"
            + "print(json.dumps(d))\n"
            + "print(json.loads('{\"x\": [1, 2]}')['x'][1], math.floor(2.7), re.sub(r'\\d+', '#', 'a12b3'))\n"
            + "print(os.path.join('a', 'b').replace(os.sep, '/'), list(itertools.chain([1], [2])), collections.Counter('aab').most_common(1))\n"
            + "P = collections.namedtuple('P', 'x y')\nprint(P(1, 2).y, collections.defaultdict(int)['k'])\n"
            + "print(json.__file__.replace(os.sep, '/').split('/')[-3:])",
            "{\"b\": 1, \"a\": [1, 2.5, null, true]}\n2 2 a#b#\na/b [1, 2] [('a', 2)]\n2 0\n['IronPython.StdLib.zip', 'json', '__init__.py']\n");
        var more = new[] { "datetime", "time", "random", "functools", "operator", "string", "io", "csv", "copy", "decimal", "fractions",
            "uuid", "hashlib", "base64", "struct", "textwrap", "difflib", "logging", "glob", "fnmatch", "shutil", "tempfile", "zipfile",
            "xml.etree.ElementTree", "codecs", "locale", "inspect", "types", "enum", "statistics", "bisect", "heapq", "pprint", "threading",
            "subprocess", "urllib.request", "sqlite3", "ctypes", "unittest", "argparse", "configparser", "pathlib", "typing", "abc", "contextlib" };
        var (imports, importFailure) = Exec("import importlib\nfor m in " + "['" + string.Join("','", more) + "']" + ":\n"
            + "    try:\n        importlib.import_module(m)\n    except Exception as e:\n        print(m + ' -> ' + type(e).__name__ + ': ' + str(e))");
        Check($"{more.Length} more standard modules import (datetime, csv, logging, sqlite3, xml, ...)", importFailure == null && imports == "",
            importFailure?.Traceback ?? imports);
        Ok("standard modules work (datetime, csv, logging to captured stdout, uuid, hashlib)",
            "import datetime, csv, io, logging, sys, hashlib\n"
            + "print(datetime.date(2026, 1, 31).isoformat(), (datetime.datetime(2026, 1, 1) + datetime.timedelta(days=1)).strftime('%Y-%m-%d'))\n"
            + "b = io.StringIO()\ncsv.writer(b).writerow(['a', 'b,c'])\nprint(b.getvalue().strip())\n"
            + "h = logging.StreamHandler(sys.stdout)\nlog = logging.getLogger('t')\nlog.addHandler(h)\nlog.warning('warned')\nlog.removeHandler(h)\n"
            + "print(hashlib.md5(b'x').hexdigest())",
            "2026-01-31 2026-01-02\na,\"b,c\"\nwarned\n9dd4e461268c8034f5c8564e155c67a6\n");

        // ---- names the old tool's scripts expect
        Ok("doc, uidoc, uiapp, app, __revit__, revit.doc / uidoc / app",
            "print(doc.Title, uidoc.Document.Title, uiapp, app.VersionNumber, __revit__)\n"
            + "print(revit.doc.Title, revit.uidoc is uidoc, revit.app is app, revit.uiapp, revit.version)",
            "Fake Project Fake Project uiapp 2026 uiapp\nFake Project True True uiapp 2026\n");
        Ok("DB and UI are the namespaces of the already loaded assemblies",
            "print(DB.Wall.__name__, DB.BuiltInCategory.OST_Walls, int(DB.BuiltInCategory.OST_Doors), UI.TaskDialog.__name__)\n"
            + "print(isinstance(doc, DB.Document), DB.Transaction(doc, 'x') is not None)",
            "Wall OST_Walls -2000023 TaskDialog\nTrue True\n");
        Ok("import clr; clr.AddReference(<loaded assembly>); from <namespace> import *",
            "import clr\nclr.AddReference('" + fakeApi.GetName().Name + "')\nfrom Fake.DB import *\nfrom Fake.UI import UIDocument\n"
            + "import Fake\nprint(Wall is DB.Wall, Document is type(doc), UIDocument is type(uidoc), Fake.DB.Wall is Wall)",
            "True True True True\n");
        Ok("clr, System and .NET interop (generics, delegates, LINQ extension methods)",
            "from System.Collections.Generic import List, Dictionary\nl = List[int]([3, 1, 2])\nl.Sort()\nprint(list(l), System.String.Join(',', ['a', 'b']))\n"
            + "f = System.Func[int, int](lambda x: x + 1)\nprint(f(41), System.Math.Abs(-2))\n"
            + "import System.Linq\nclr.ImportExtensions(System.Linq)\nprint(l.Where(lambda x: x > 1).Count(), System.Environment.NewLine == '\\r\\n')",
            "[1, 2, 3] a,b\n42 2\n2 True\n");
        Ok("Python 2 names: unicode, basestring, long, xrange, reduce",
            "print(unicode(5) + 'x', isinstance('a', basestring), isinstance(u'a', unicode), long(7) * 2, list(xrange(3)), reduce(lambda a, b: a + b, [1, 2, 3]))\n"
            + "print(isinstance(2 ** 70, long), type(long('12')).__name__)",
            "5x True True 14 [0, 1, 2] 6\nTrue int\n");
        Ok("from pyrevit import revit, DB, UI, HOST_APP (stand-in)",
            "from pyrevit import revit as r, DB as D, UI as U, HOST_APP\nprint(r.doc.Title, D.Wall is DB.Wall, U is UI, HOST_APP.version)",
            "Fake Project True True 2026\n");
        Ok("classes: Python class, Exception subclass, subclass of a .NET class, .NET interface",
            "class A(object):\n    def __init__(self):\n        self.v = 1\n"
            + "class E(Exception):\n    pass\n"
            + "class W(DB.Element):\n    def Describe(self):\n        return 'python wall'\n"
            + "class C(System.IComparable):\n    def CompareTo(self, other):\n        return 0\n"
            + "class S(object):\n    __slots__ = ('a',)\n"
            + "try:\n    raise E('boom')\nexcept E as e:\n    print(A().v, str(e), DB.Thrower.CallDescribe(W()), System.Collections.Generic.Comparer[object].Default.Compare(C(), 1))",
            "1 boom python wall 0\n");
        Ok("__name__ is __main__", "if __name__ == '__main__':\n    print('main')", "main\n");

        // ---- read_only proxy
        Ok("read_only: DB proxy passes everything else through", "print(DB.Wall.__name__, DB.BuiltInCategory.OST_Walls, 'Wall' in dir(DB))", "Wall OST_Walls True\n", readOnly: true);
        foreach (var blocked in new[] { "Transaction", "SubTransaction", "TransactionGroup" })
        {
            var f = Fails("read_only: DB." + blocked + " is blocked", "t = DB." + blocked + "(doc, 'x')", "RuntimeError", readOnly: true);
            Check("  message as in the Python route", f.Message == "read_only mode: DB." + blocked + " is not allowed. Use transaction_mode='auto' or "
                + "'dry_run' for code that modifies the model.", f.Message);
        }

        // ---- errors: what the route reports as error_type / error / traceback
        var zero = Fails("exception: ZeroDivisionError", "x = 1\ndef f(n):\n    return n / 0\nprint('before')\nf(x)", "ZeroDivisionError");
        Check("  traceback names the lines of the submitted code",
            zero.Traceback.StartsWith("Traceback (most recent call last):") && zero.Traceback.Contains("File \"<string>\", line 5, in <module>")
            && zero.Traceback.Contains("File \"<string>\", line 3, in f") && zero.Traceback.Contains("return n / 0")
            && zero.Traceback.TrimEnd().EndsWith("ZeroDivisionError: " + zero.Message) && !zero.Traceback.Contains("_run"), zero.Traceback);
        var (partial, _) = Exec("print('before')\nraise ValueError('bad')");
        Check("  partial output is kept", partial == "before\n", Show(partial));
        Fails("exception: raise ValueError('bad value')", "raise ValueError('bad value')", "ValueError", "bad value");
        Fails("exception: KeyError", "{}['missing']", "KeyError", "missing");
        Fails("exception: NameError", "print(undefined_name)", "NameError", "undefined_name");
        Fails("exception: None attribute -> AttributeError mentioning NoneType", "e = None\ne.Name", "AttributeError", "NoneType");
        Fails("exception: missing attribute on a .NET object", "doc.Nope", "AttributeError", "Nope");
        Fails("exception: custom class", "class MyError(Exception):\n    pass\nraise MyError('mine')", "MyError", "mine");
        // pyRevit (IronPython 2.7) reports a Revit exception as error_type "Exception": same here; the .NET name is extra.
        var revitInvalid = Fails(".NET exception: Revit-style InvalidOperationException is 'Exception', as under pyRevit", "DB.Thrower.RevitInvalidOperation()", "Exception", "outside of a transaction");
        Check("  and its .NET class name is known (for the transaction hint)", revitInvalid.ClrType == "InvalidOperationException", revitInvalid.ClrType);
        Check("  traceback ends like Python's", revitInvalid.Traceback.TrimEnd().EndsWith("Exception: Cannot modify the document outside of a transaction."), revitInvalid.Traceback);
        foreach (var call in new[] { "Argument", "SystemInvalidOperation", "NullReference" })
        {
            var f = Exec("DB.Thrower." + call + "()").failure;
            Console.WriteLine("        Thrower." + call + " is reported as: " + f?.ErrorType + ": " + f?.Message + "  [.NET: " + f?.ClrType + "]");
        }
        Check("a Python error has no .NET class name", zero.ClrType == "", zero.ClrType);
        Ok(".NET exceptions can be caught in the script", "try:\n    DB.Thrower.RevitInvalidOperation()\nexcept Exception as e:\n    print(type(e).__name__, str(e)[:6])", "Exception Cannot\n");
        var exit = Fails("sys.exit() does not escape", "import sys\nsys.exit(3)", "SystemExit");

        // ---- syntax errors
        var syntax = Fails("syntax error is reported, not thrown", "x = 1\ny = (1,\nprint(x)", "SyntaxError");
        Console.WriteLine("        " + syntax.Message + " | " + syntax.Traceback.Trim().Replace("\n", " | "));
        var p2 = Fails("Python 2 print statement -> SyntaxError", "x = 5\nprint \"value\", x", "SyntaxError");
        Console.WriteLine("        " + p2.Message);
        var hints = PyEngine.Python3Hints(p2.ErrorType, p2.Message, "x = 5\nprint \"value\", x");
        Check("  with the print hint", hints.Count == 1 && hints[0].Contains("Python 2 print statement"), string.Join("|", hints));
        Check("  print >>f, x and 'if x: print y' are recognised", PyEngine.Python3Hints("SyntaxError", "", "print >>sys.stderr, 1").Count == 1
            && PyEngine.Python3Hints("SyntaxError", "", "if x: print y").Count == 1);
        Check("  no print hint for print(...), print (x), pprint x", PyEngine.Python3Hints("SyntaxError", "", "print('a')\nprint ('b')\nprint()\nprint\nfoo.print x\npprint x\ny = (").Count == 0);
        var p2e = Fails("Python 2 'except E, e' -> SyntaxError", "try:\n    pass\nexcept Exception, e:\n    pass", "SyntaxError");
        Check("  with the except hint", PyEngine.Python3Hints(p2e.ErrorType, p2e.Message, "try:\n    pass\nexcept Exception, e:\n    pass").Count == 1);
        var iter = Fails("dict.iteritems -> AttributeError", "for k, v in {'a': 1}.iteritems():\n    pass", "AttributeError", "iteritems");
        Check("  with the Python 3 hint", PyEngine.Python3Hints(iter.ErrorType, iter.Message, "").Count == 1);
        var noPyrevit = Fails("from pyrevit import forms -> ImportError", "from pyrevit import forms", "ImportError");
        Check("  with the pyRevit hint", PyEngine.Python3Hints(noPyrevit.ErrorType, noPyrevit.Message, "from pyrevit import forms").Count == 1, noPyrevit.Message);

        // ---- isolation between executions
        Ok("each execution has its own namespace (1)", "leak = 42\nprint(leak)", "42\n");
        Fails("each execution has its own namespace (2)", "print(leak)", "NameError");
        var (stdoutState, _) = Exec("import sys\nprint(type(sys.stdout).__name__)");
        var restored = Exec("import sys, io\nprint(isinstance(sys.__stdout__, io.StringIO))").output;
        Check("sys.stdout is the capture during a run and restored after it", stdoutState == "StringIO\n" && restored == "False\n", stdoutState + restored);
        Ok("unicode output", "print(u'\\u0645\\u0631\\u062d\\u0628\\u0627 \\u00e9')", "\u0645\u0631\u062d\u0628\u0627 \u00e9\n");

        // ---- life cycle
        PyEngine.Shutdown();
        Check("Shutdown stops the engine", !PyEngine.IsCreated);
        watch.Restart();
        Ok("a new engine is created after Shutdown", "import json\nprint(json.dumps([1]))", "[1]\n");
        Console.WriteLine($"        (second engine created in {watch.ElapsedMilliseconds} ms)");
        PyEngine.Shutdown();
        return _failed;
    }
}
