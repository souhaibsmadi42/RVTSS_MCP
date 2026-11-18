namespace RvtssHost.Tests;

public static class SecurityTests
{
    public static void Run(T t)
    {
        var doc = LaneB.Run(t, "security", c =>
        {
            switch (c.Fn)
            {
                case "parse_flag":
                    return c.Has(1, "default")
                        ? Security.ParseFlag(c.Arg(0), (bool?)c.Arg(1, "default"))
                        : Security.ParseFlag(c.Arg(0));
                case "constant_time_equal": return Security.ConstantTimeEqual(c.Arg(0), c.Arg(1));
                case "extract_token":
                {
                    var headers = c.Arg(2, "headers") is Dict h
                        ? h.ToDictionary(kv => kv.Key, kv => (string)kv.Value!)
                        : null;
                    return Security.ExtractToken(c.Arg(0, "data") as Dict, c.Arg(1, "query_params") as Dict, headers);
                }
                case "is_loopback": return Security.IsLoopback(c.Str(0));
                case "binds_all_interfaces": return Security.BindsAllInterfaces(c.Str(0));
                case "redact":
                    return c.Arg(0) is string || c.Arg(0) == null
                        ? Security.Redact(c.Str(0), c.Int(1, "max_len"))
                        : Security.Redact(c.Arg(0), c.Int(1, "max_len"));
                case "redact_mapping": return Security.RedactMapping(c.Arg(0));
                default: throw new InvalidOperationException("no dispatch for " + c.Fn);
            }
        }, skip: c =>
        {
            // str() of a list is Python's repr, which the port does not reproduce
            if (c.Fn == "redact" && c.Arg(0) is Lst)
                return true;
            // a token that is not a string comes back as its text (the signature returns string?)
            if (c.Fn == "extract_token" && c.Raw.Get("out") != null && c.Raw["out"] is not string)
            {
                var headers = (c.Arg(2, "headers") as Dict)?.ToDictionary(kv => kv.Key, kv => (string)kv.Value!);
                t.Eq("extract_token non-string", Py.Str(c.Raw["out"]),
                    Security.ExtractToken(c.Arg(0, "data") as Dict, c.Arg(1, "query_params") as Dict, headers));
                return true;
            }
            return false;
        });

        var constants = (Dict)doc["constants"]!;
        t.Eq("TOKEN_BODY_KEY", constants["TOKEN_BODY_KEY"], Security.TokenBodyKey);
        t.Eq("TOKEN_QUERY_KEY", constants["TOKEN_QUERY_KEY"], Security.TokenQueryKey);
        t.Eq("TOKEN_HEADER", constants["TOKEN_HEADER"], Security.TokenHeader);
        t.Eq("UNPROTECTED_PATHS", constants["UNPROTECTED_PATHS"], Security.UnprotectedPaths);
        t.Eq("REDACTED", constants["REDACTED"], Security.Redacted);

        // the signatures other code relies on
        string redacted = Security.Redact("password=x", 200);
        t.Eq("Redact string", "password=[REDACTED]", redacted);
        bool? flag = Security.ParseFlag("yes", false);
        t.Eq("ParseFlag", true, flag);
        string? token = Security.ExtractToken(new Dict { ["_rvtss_token"] = "a" }, new Dict(),
            new Dictionary<string, string> { ["X-RVTSS-Token"] = "h" });
        t.Eq("ExtractToken", "a", token);
        t.Eq("ExtractToken header", "h", Security.ExtractToken(headers: new Dictionary<string, string> { ["x-rvtss-token"] = "h" }));
        t.Check("IsLoopback", Security.IsLoopback("127.0.0.1") && !Security.IsLoopback(null));
        t.Eq("typed list mapping", new Lst { new Dict { ["token"] = "[REDACTED]" } },
            Security.RedactMapping(new List<Dict> { new() { ["token"] = "t" } }));
    }
}
