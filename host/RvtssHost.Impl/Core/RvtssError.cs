namespace RvtssHost;

/// <summary>An expected, user-facing failure with an HTTP status and recovery hint (core.RvtssError).</summary>
public sealed class RvtssError : Exception
{
    public int Status { get; }
    public string? Hint { get; }
    public Dict Extra { get; } = new();

    public RvtssError(string message, int status = 400, string? hint = null, Dict? extra = null) : base(message)
    {
        Status = status;
        Hint = hint;
        if (extra != null)
            foreach (var kv in extra)
                Extra[kv.Key] = kv.Value;
    }

    /// <summary>Extra response field (the **extra keyword arguments of the Python class).</summary>
    public RvtssError With(string key, object? value)
    {
        Extra[key] = value;
        return this;
    }
}
