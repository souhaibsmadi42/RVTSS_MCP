using System.Reflection;
#if NET
using System.Runtime.Loader;
#endif

namespace RvtssHost;

/// <summary>
/// Loads RvtssHost.Impl.dll (and its private dependencies) from bytes, so the files are never
/// locked and a new build can be loaded while Revit runs.
/// Contract: static class RvtssHost.Entry with
///   Func&lt;HttpRequest, Task&lt;HttpResponse&gt;&gt; Start(RevitDispatcher, string revitVersion, int port)
///   void Stop()
/// </summary>
public sealed class ImplLoader(RevitDispatcher dispatcher, string revitVersion, int port)
{
    private const string ImplName = "RvtssHost.Impl";
    private static readonly string Dir = Path.GetDirectoryName(typeof(ImplLoader).Assembly.Location) ?? ".";

    private Action? _stop;
    private Type? _entry;
#if NET
    private AssemblyLoadContext? _context;
#else
    private static bool _resolverInstalled;
#endif

    public Func<HttpRequest, Task<HttpResponse>>? Handler { get; private set; }
    public string? LastError { get; private set; }

    /// <summary>Loads (or reloads) the implementation. Returns null on success, else the error text.</summary>
    public string? Load()
    {
        try
        {
            Unload();
            var assembly = LoadAssembly();
            var entry = assembly.GetType("RvtssHost.Entry", true)!;
            _entry = entry;
            var start = entry.GetMethod("Start", BindingFlags.Public | BindingFlags.Static)
                        ?? throw new MissingMethodException("RvtssHost.Entry.Start");
            var stop = entry.GetMethod("Stop", BindingFlags.Public | BindingFlags.Static);
            Handler = (Func<HttpRequest, Task<HttpResponse>>)start.Invoke(null, new object[] { dispatcher, revitVersion, port })!;
            _stop = stop == null ? null : () => stop.Invoke(null, null);
            LastError = null;
            return null;
        }
        catch (Exception e)
        {
            var inner = e is TargetInvocationException && e.InnerException != null ? e.InnerException : e;
            Handler = null;
            LastError = inner.GetType().Name + ": " + inner.Message;
            Log.Write("Impl load failed: " + inner);
            return LastError;
        }
    }

    /// <summary>Calls a public static method of RvtssHost.Entry in the loaded implementation (ribbon commands).</summary>
    public object? InvokeEntry(string method, params object?[] args)
    {
        var entry = _entry ?? throw new InvalidOperationException("RVTSS routes are not loaded: " + (LastError ?? "unknown"));
        var m = entry.GetMethod(method, BindingFlags.Public | BindingFlags.Static)
                ?? throw new MissingMethodException("RvtssHost.Entry." + method);
        try { return m.Invoke(null, args); }
        catch (TargetInvocationException e) when (e.InnerException != null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(e.InnerException).Throw();
            throw;
        }
    }

    public void Unload()
    {
        Handler = null;
        _entry = null;
        try { _stop?.Invoke(); } catch (Exception e) { Log.Write("Impl stop failed: " + e.Message); }
        _stop = null;
#if NET
        try { _context?.Unload(); } catch { /* best effort */ }
        _context = null;
#endif
    }

    private static byte[]? ReadIfExists(string file) => File.Exists(file) ? File.ReadAllBytes(file) : null;

#if NET
    private Assembly LoadAssembly()
    {
        var context = new ImplContext();
        _context = context;
        return context.LoadFromBytes(ImplName) ?? throw new FileNotFoundException(Path.Combine(Dir, ImplName + ".dll"));
    }

    /// <summary>Private dependencies come from the add-in folder; everything else from the shell's context.</summary>
    private sealed class ImplContext() : AssemblyLoadContext("RvtssHost.Impl", isCollectible: true)
    {
        private static readonly Assembly Shell = typeof(ImplLoader).Assembly;
        private static readonly AssemblyLoadContext ShellContext = GetLoadContext(Shell) ?? Default;

        public Assembly? LoadFromBytes(string name)
        {
            var dll = ReadIfExists(Path.Combine(Dir, name + ".dll"));
            if (dll == null)
                return null;
            var pdb = ReadIfExists(Path.Combine(Dir, name + ".pdb"));
            using var a = new MemoryStream(dll);
            if (pdb == null)
                return LoadFromStream(a);
            using var b = new MemoryStream(pdb);
            return LoadFromStream(a, b);
        }

        protected override Assembly? Load(AssemblyName name)
        {
            if (name.Name == null)
                return null;
            if (name.Name == Shell.GetName().Name)
                return Shell;
            // A dependency shipped next to the add-in is always the private copy, even when another add-in
            // (pyRevit ships the same IronPython) has already loaded an assembly with that name.
            var mine = LoadFromBytes(name.Name);
            if (mine != null)
                return mine;
            // Everything else (Revit API, framework) comes from the shell's context.
            try { return ShellContext.LoadFromAssemblyName(name); }
            catch { return null; }
        }
    }
#else
    private Assembly LoadAssembly()
    {
        if (!_resolverInstalled)
        {
            _resolverInstalled = true;
            AppDomain.CurrentDomain.AssemblyResolve += (_, args) =>
            {
                var wanted = new AssemblyName(args.Name);
                var name = wanted.Name;
                var all = AppDomain.CurrentDomain.GetAssemblies().Where(a => a.GetName().Name == name).ToList();
                // Exact version already loaded, else our own copy next to the add-in, else whatever has the name.
                var exact = all.FirstOrDefault(a => wanted.Version == null || a.GetName().Version == wanted.Version);
                if (exact != null)
                    return exact;
                var file = Path.Combine(Dir, name + ".dll");
                if (File.Exists(file))
                    return Assembly.LoadFrom(file);
                return all.FirstOrDefault();
            };
        }
        var dll = ReadIfExists(Path.Combine(Dir, ImplName + ".dll")) ?? throw new FileNotFoundException(Path.Combine(Dir, ImplName + ".dll"));
        var pdb = ReadIfExists(Path.Combine(Dir, ImplName + ".pdb"));
        return pdb == null ? Assembly.Load(dll) : Assembly.Load(dll, pdb);
    }
#endif
}
