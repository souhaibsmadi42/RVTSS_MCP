namespace RvtssHost.Tests;

public static class TracingTests
{
    /// <summary>Stands in for the Routes response object (Python attribute `data`).</summary>
    private sealed class Resp
    {
        public object? Data { get; set; }
    }

    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "tracing", c =>
        {
            switch (c.Fn)
            {
                case "clean_request_id": return Tracing.CleanRequestId(c.Arg(0));
                case "pop_request_id":
                {
                    var data = c.Arg(0) as Dict;
                    var rid = Tracing.PopRequestId(data, c.Arg(1) as Dict);
                    return new Lst { rid, data };
                }
                case "attach_request_id":
                {
                    var body = c.Arg(1);
                    var rid = c.Str(2);
                    bool same;
                    if (c.Str(0) == "object")
                    {
                        var response = new Resp { Data = body };
                        same = ReferenceEquals(Tracing.AttachRequestId(response, rid), response);
                    }
                    else
                    {
                        same = body == null
                            ? Tracing.AttachRequestId(body, rid) == null
                            : body is Dict || body is Lst || body is string
                                ? ReferenceEquals(Tracing.AttachRequestId(body, rid), body)
                                : Equals(Tracing.AttachRequestId(body, rid), body);
                    }
                    return new Dict { ["same"] = same, ["body"] = body };
                }
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        });
        var constants = (Dict)doc["constants"]!;
        t.Eq("REQUEST_ID_BODY_KEY", constants["REQUEST_ID_BODY_KEY"], Tracing.RequestIdBodyKey);
        t.Eq("REQUEST_ID_QUERY_KEY", constants["REQUEST_ID_QUERY_KEY"], Tracing.RequestIdQueryKey);

        // the static type of the response is kept
        Dict payload = Tracing.AttachRequestId(new Dict { ["status"] = "success" }, "r1");
        t.Eq("typed attach", "r1", payload["request_id"]);
    }
}
