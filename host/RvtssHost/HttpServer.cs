using System.Net;
using System.Net.Sockets;
using System.Text;

namespace RvtssHost;

public sealed record HttpRequest(string Method, string Path, string Query, Dictionary<string, string> Headers, byte[] Body);

public sealed record HttpResponse(int Status, byte[] Body, string ContentType = "application/json; charset=utf-8");

/// <summary>
/// Minimal HTTP/1.1 server on a loopback TcpListener (keep-alive, Content-Length bodies).
/// A raw listener needs no admin rights and no URL reservation, unlike HttpListener.
/// </summary>
public sealed class HttpServer(int port, Func<HttpRequest, Task<HttpResponse>> handler)
{
    private const int MaxHeaderBytes = 64 * 1024;
    private const int MaxBodyBytes = 64 * 1024 * 1024;

    private readonly TcpListener _listener = new(IPAddress.Loopback, port);
    private volatile bool _stopped;

    public void Start()
    {
        _listener.Start();
        _ = Task.Run(AcceptLoop);
    }

    public void Stop()
    {
        _stopped = true;
        _listener.Stop();
    }

    private async Task AcceptLoop()
    {
        while (!_stopped)
        {
            TcpClient client;
            try { client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false); }
            catch { break; }
            _ = Task.Run(() => Serve(client));
        }
    }

    private async Task Serve(TcpClient client)
    {
        using (client)
        {
            try
            {
                client.NoDelay = true;
                var stream = client.GetStream();
                var buffer = new byte[8192];
                var pending = new MemoryStream();
                while (!_stopped)
                {
                    var request = await ReadRequest(stream, buffer, pending).ConfigureAwait(false);
                    if (request is null)
                        return;
                    HttpResponse response;
                    try { response = await handler(request).ConfigureAwait(false); }
                    catch (Exception e)
                    {
                        Log.Write("Unhandled: " + e);
                        response = new HttpResponse(500, Encoding.UTF8.GetBytes("{\"status\":\"error\",\"error\":\"internal error\"}"));
                    }
                    var close = request.Headers.TryGetValue("connection", out var c) && c.Equals("close", StringComparison.OrdinalIgnoreCase);
                    var head = Encoding.ASCII.GetBytes(
                        $"HTTP/1.1 {response.Status} {Reason(response.Status)}\r\nContent-Type: {response.ContentType}\r\n" +
                        $"Content-Length: {response.Body.Length}\r\nConnection: {(close ? "close" : "keep-alive")}\r\n\r\n");
                    await stream.WriteAsync(head, 0, head.Length).ConfigureAwait(false);
                    await stream.WriteAsync(response.Body, 0, response.Body.Length).ConfigureAwait(false);
                    if (close)
                        return;
                }
            }
            catch (IOException) { /* client went away */ }
            catch (SocketException) { }
            catch (ObjectDisposedException) { }
            catch (Exception e) { Log.Write("Connection error: " + e.Message); }
        }
    }

    /// <summary>Reads one request; null when the client closed or sent something we refuse.</summary>
    private static async Task<HttpRequest?> ReadRequest(NetworkStream stream, byte[] buffer, MemoryStream pending)
    {
        int headerEnd;
        while ((headerEnd = FindHeaderEnd(pending)) < 0)
        {
            if (pending.Length > MaxHeaderBytes)
                return null;
            var n = await stream.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false);
            if (n == 0)
                return null;
            pending.Write(buffer, 0, n);
        }

        var all = pending.GetBuffer();
        var lines = Encoding.ASCII.GetString(all, 0, headerEnd).Split(new[] { "\r\n" }, StringSplitOptions.None);
        var first = lines[0].Split(' ');
        if (first.Length < 2)
            return null;
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in lines.Skip(1))
        {
            var i = line.IndexOf(':');
            if (i > 0)
                headers[line.Substring(0, i).Trim()] = line.Substring(i + 1).Trim();
        }
        if (headers.ContainsKey("transfer-encoding"))
            return null; // chunked bodies are not supported

        var length = 0;
        if (headers.TryGetValue("content-length", out var cl) && (!int.TryParse(cl, out length) || length < 0 || length > MaxBodyBytes))
            return null;

        var bodyStart = headerEnd + 4;
        while (pending.Length - bodyStart < length)
        {
            var n = await stream.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false);
            if (n == 0)
                return null;
            pending.Write(buffer, 0, n);
        }
        all = pending.GetBuffer();
        var body = new byte[length];
        Buffer.BlockCopy(all, bodyStart, body, 0, length);

        // Keep whatever follows (a pipelined request) for the next read.
        var rest = (int)pending.Length - bodyStart - length;
        var tail = new byte[rest];
        Buffer.BlockCopy(all, bodyStart + length, tail, 0, rest);
        pending.SetLength(0);
        pending.Write(tail, 0, rest);

        var target = first[1];
        var q = target.IndexOf('?');
        var path = Uri.UnescapeDataString(q < 0 ? target : target.Substring(0, q));
        return new HttpRequest(first[0].ToUpperInvariant(), path, q < 0 ? "" : target.Substring(q + 1), headers, body);
    }

    private static int FindHeaderEnd(MemoryStream ms)
    {
        var b = ms.GetBuffer();
        var len = (int)ms.Length;
        for (var i = 0; i + 3 < len; i++)
            if (b[i] == 13 && b[i + 1] == 10 && b[i + 2] == 13 && b[i + 3] == 10)
                return i;
        return -1;
    }

    private static string Reason(int status) => status switch
    {
        200 => "OK", 400 => "Bad Request", 401 => "Unauthorized", 403 => "Forbidden", 404 => "Not Found",
        405 => "Method Not Allowed", 409 => "Conflict", 503 => "Service Unavailable", 504 => "Gateway Timeout",
        _ => status < 400 ? "OK" : "Error",
    };
}
