// Launcher of the Exec.Tests harness: plays the shell add-in (RvtssHost) outside Revit.
//   * The loader below is a copy of RvtssHost/ImplLoader.cs: the payload and its private dependencies (IronPython)
//     are loaded FROM BYTES from the layout folder into a collectible AssemblyLoadContext (.NET 8/10), or with
//     Assembly.Load(bytes) + AssemblyResolve (.NET Framework 4.8).
//   * Fake.DB / Fake.UI in this assembly stand in for RevitAPI / RevitAPIUI: assemblies that are already loaded in
//     the shell's context, which the engine must see without loading a second copy.
using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
#if NET
using System.Runtime.Loader;
#endif

namespace Fake.DB
{
    public class Application
    {
        public string VersionNumber => "2026";
    }

    public class Document
    {
        public string Title => "Fake Project";
        public Application Application { get; } = new Application();
        public bool IsModifiable => false;
    }

    public class Element
    {
        public virtual string Describe() => "element";
    }

    public class Wall : Element { }

    public enum BuiltInCategory { OST_Walls = -2000011, OST_Doors = -2000023 }

    public class Transaction
    {
        public Transaction(Document doc, string name) { }
    }

    public class SubTransaction { }

    public class TransactionGroup { }

    public static class Thrower
    {
        public static void RevitInvalidOperation() => throw new Fake.Exceptions.InvalidOperationException("Cannot modify the document outside of a transaction.");
        public static void SystemInvalidOperation() => throw new System.InvalidOperationException("system invalid operation");
        public static void NullReference() => throw new NullReferenceException("Object reference not set to an instance of an object.");
        public static void Argument() => throw new Fake.Exceptions.ArgumentException("bad argument");
        public static string CallDescribe(Element e) => e.Describe();
    }
}

namespace Fake.Exceptions
{
    public class InvalidOperationException : Exception { public InvalidOperationException(string m) : base(m) { } }
    public class ArgumentException : Exception { public ArgumentException(string m) : base(m) { } }
}

namespace Fake.UI
{
    public class UIDocument
    {
        public Fake.DB.Document Document { get; } = new Fake.DB.Document();
    }

    public class TaskDialog { }
}

namespace RvtssHost.Tests
{
    public static class Program
    {
        private const string PayloadName = "Exec.Payload";

        public static int Main(string[] args)
        {
            var here = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            // out\<lane>\R<year>\exec-tests  ->  the Impl build output out\<lane>\R<year> is the deployed layout
            var layout = args.Length > 0 && !args[0].StartsWith("--") ? Path.GetFullPath(args[0]) : Path.GetDirectoryName(here)!;
            var payloadDir = Path.Combine(here, "payload");
            Console.WriteLine("runtime : " + System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription);
            Console.WriteLine("layout  : " + layout);
            if (!File.Exists(Path.Combine(layout, "IronPython.dll")) || !File.Exists(Path.Combine(layout, "IronPython.StdLib.zip")))
            {
                Console.WriteLine("FAIL: the layout has no IronPython.dll / IronPython.StdLib.zip. Build host/RvtssHost.Impl first (same RevitYear and Lane).");
                return 2;
            }
            if (File.Exists(Path.Combine(here, "IronPython.dll")))
            {
                Console.WriteLine("FAIL: IronPython.dll lies next to the launcher: the test would not prove loading from bytes.");
                return 2;
            }

            var failures = 0;
#if NET
            // 1. exactly like ImplLoader: collectible context, everything private from bytes
            failures += RunInContext("bytes, collectible AssemblyLoadContext (ImplLoader)", layout, payloadDir, fromBytes: true, mode: "full");
            // 1b. a reload: after typical scripts and PyEngine.Shutdown the context must be collectable
            failures += RunInContext("reload: typical scripts, Shutdown, unload the context", layout, payloadDir, fromBytes: true, mode: "typical");
            // 2. the other way the shell can end up resolving the engine: from files, by the shell's own context
            if (!args.Contains("--bytes-only"))
                failures += RunInContext("files, non-collectible context (engine resolved by the shell's context)", layout, payloadDir, fromBytes: false, mode: "full");
#else
            failures += RunFramework(layout, payloadDir);
#endif
            Console.WriteLine();
            Console.WriteLine(failures == 0 ? "ALL PASSED" : failures + " FAILED");
            return failures == 0 ? 0 : 1;
        }

        private static int Invoke(Assembly payload, string layout, string mode)
        {
            var run = payload.GetType("RvtssHost.Tests.Checks", true)!.GetMethod("Run", BindingFlags.Public | BindingFlags.Static)!;
            try
            {
                return (int)run.Invoke(null, new object[] { layout, typeof(Program).Assembly, mode })!;
            }
            catch (TargetInvocationException e)
            {
                Console.WriteLine("FAIL: harness crashed: " + e.InnerException);
                return 1;
            }
        }

        private static byte[]? ReadIfExists(string file) => File.Exists(file) ? File.ReadAllBytes(file) : null;

#if NET
        private static int RunInContext(string title, string layout, string payloadDir, bool fromBytes, string mode)
        {
            Console.WriteLine();
            Console.WriteLine("=== " + title + " ===");
            var failures = RunAndRelease(layout, payloadDir, fromBytes, mode, out var weak, out var loaded);
            Console.WriteLine("  assemblies in the context: " + loaded);
            if (!fromBytes)
                return failures;
            for (var i = 0; i < 100 && weak.IsAlive; i++)
            {
                GC.Collect();
                GC.WaitForPendingFinalizers();
                System.Threading.Thread.Sleep(50);
            }
            if (weak.IsAlive && mode == "full")
            {
                Console.WriteLine("  FAIL  context unloaded after the full pass and PyEngine.Shutdown (it is still alive)");
                failures++;
            }
            else if (weak.IsAlive)
            {
                Console.WriteLine("  FAIL  context unloaded after PyEngine.Shutdown (it is still alive: something of the engine leaks)");
                failures++;
            }
            else
            {
                Console.WriteLine("  ok    context unloaded after PyEngine.Shutdown (collected by the GC: no leak across reloads)");
            }
            return failures;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static int RunAndRelease(string layout, string payloadDir, bool fromBytes, string mode, out WeakReference weak, out string loaded)
        {
            var context = new ImplContext(layout, payloadDir, fromBytes);
            weak = new WeakReference(context);
            var payload = context.LoadPrivate(PayloadName) ?? throw new FileNotFoundException(PayloadName);
            var failures = Invoke(payload, layout, mode);
            loaded = string.Join(", ", context.Assemblies.Select(a => a.GetName().Name + (a.IsDynamic ? "(dynamic)" : a.Location.Length == 0 ? "(bytes)" : "(file)")));
            if (fromBytes)
            {
                foreach (var a in context.Assemblies)
                    if (!a.IsDynamic && a.Location.Length != 0)
                    {
                        Console.WriteLine("  FAIL  " + a.GetName().Name + " was loaded from a file, not from bytes");
                        failures++;
                    }
                foreach (var a in AssemblyLoadContext.Default.Assemblies)
                    if ((a.GetName().Name ?? "").StartsWith("IronPython") || (a.GetName().Name ?? "").StartsWith("Microsoft.Scripting") || a.GetName().Name == "Microsoft.Dynamic")
                    {
                        Console.WriteLine("  FAIL  " + a.GetName().Name + " ended up in the default context");
                        failures++;
                    }
                context.Unload();
            }
            return failures;
        }

        /// <summary>Copy of ImplLoader.ImplContext (fromBytes: true). Private dependencies come from the layout folder.</summary>
        private sealed class ImplContext : AssemblyLoadContext
        {
            private static readonly Assembly Shell = typeof(Program).Assembly;
            private static readonly AssemblyLoadContext ShellContext = GetLoadContext(Shell) ?? Default;
            private readonly string _layout, _payloadDir;
            private readonly bool _fromBytes;

            public ImplContext(string layout, string payloadDir, bool fromBytes) : base("RvtssHost.Impl", isCollectible: fromBytes)
            {
                _layout = layout;
                _payloadDir = payloadDir;
                _fromBytes = fromBytes;
            }

            public Assembly? LoadPrivate(string name)
            {
                var file = Path.Combine(name == PayloadName ? _payloadDir : _layout, name + ".dll");
                if (!_fromBytes && name != PayloadName)
                    return File.Exists(file) ? LoadFromAssemblyPath(file) : null;
                var dll = ReadIfExists(file);
                if (dll == null)
                    return null;
                using var a = new MemoryStream(dll);
                return LoadFromStream(a);
            }

            protected override Assembly? Load(AssemblyName name)
            {
                if (name.Name == Shell.GetName().Name)
                    return Shell;
                try { return ShellContext.LoadFromAssemblyName(name); }
                catch { /* not there: a private dependency of the implementation */ }
                return name.Name == null ? null : LoadPrivate(name.Name);
            }
        }
#else
        /// <summary>Copy of the .NET Framework branch of ImplLoader.LoadAssembly.</summary>
        private static int RunFramework(string layout, string payloadDir)
        {
            Console.WriteLine();
            Console.WriteLine("=== Assembly.Load(bytes) + AssemblyResolve (ImplLoader on .NET Framework) ===");
            AppDomain.CurrentDomain.AssemblyResolve += (_, a) =>
            {
                var name = new AssemblyName(a.Name).Name;
                var loaded = AppDomain.CurrentDomain.GetAssemblies().FirstOrDefault(x => x.GetName().Name == name);
                if (loaded != null)
                    return loaded;
                var file = Path.Combine(layout, name + ".dll");
                return File.Exists(file) ? Assembly.LoadFrom(file) : null;
            };
            var payload = Assembly.Load(File.ReadAllBytes(Path.Combine(payloadDir, PayloadName + ".dll")));
            var failures = Invoke(payload, layout, "full");
            Console.WriteLine("  engine assemblies: " + string.Join(", ", AppDomain.CurrentDomain.GetAssemblies()
                .Where(x => !x.IsDynamic && (x.GetName().Name.StartsWith("IronPython") || x.GetName().Name.StartsWith("Microsoft.")))
                .Select(x => x.GetName().Name + " " + x.GetName().Version)));
            return failures;
        }
#endif
    }
}
