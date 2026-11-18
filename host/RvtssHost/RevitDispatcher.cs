using System.Collections.Concurrent;
using Autodesk.Revit.UI;

namespace RvtssHost;

/// <summary>Thrown when Revit's main thread did not pick the job up in time.</summary>
public sealed class RevitBusyException(double seconds)
    : Exception($"Revit did not give its main thread within {seconds:0} seconds") { }

/// <summary>
/// Runs work on Revit's main thread (API context) through one ExternalEvent.
/// A job that timed out while waiting is cancelled, so it can never run later
/// behind the caller's back.
/// </summary>
public sealed class RevitDispatcher : IExternalEventHandler
{
    private sealed class Job(Func<UIApplication, object?> work)
    {
        public readonly Func<UIApplication, object?> Work = work;
        public readonly TaskCompletionSource<object?> Done = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public int State; // 0 queued, 1 running/finished, 2 cancelled
    }

    private readonly ConcurrentQueue<Job> _queue = new();
    private readonly ExternalEvent _event;

    /// <summary>Must be created in API context (OnStartup).</summary>
    public RevitDispatcher() => _event = ExternalEvent.Create(this);

    public string GetName() => "RVTSS Host request";

    public void Execute(UIApplication app)
    {
        while (_queue.TryDequeue(out var job))
        {
            if (Interlocked.CompareExchange(ref job.State, 1, 0) != 0)
                continue; // cancelled while waiting
            try { job.Done.SetResult(job.Work(app)); }
            catch (Exception e) { job.Done.SetException(e); }
        }
    }

    public async Task<object?> Run(Func<UIApplication, object?> work, TimeSpan timeout)
    {
        var job = new Job(work);
        _queue.Enqueue(job);
        _event.Raise();
        var finished = await Task.WhenAny(job.Done.Task, Task.Delay(timeout)).ConfigureAwait(false);
        if (finished != job.Done.Task && Interlocked.CompareExchange(ref job.State, 2, 0) == 0)
            throw new RevitBusyException(timeout.TotalSeconds);
        // Either finished, or already running: wait for the real result.
        return await job.Done.Task.ConfigureAwait(false);
    }
}
