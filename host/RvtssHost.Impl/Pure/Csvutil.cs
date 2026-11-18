namespace RvtssHost.Pure;

/// <summary>Python: csv.Error, raised by the reader for input it cannot parse.</summary>
public class CsvError : Exception
{
    public CsvError(string message) : base(message) { }
}

/// <summary>Minimal RFC 4180 CSV writer/reader that behaves the same on IronPython 2/3 and CPython.</summary>
public static class Csvutil
{
    private static string Cell(object? value)
    {
        if (value == null)
            return "";
        if (value is bool b)
            return b ? "Yes" : "No";
        var s = value as string ?? Py.Str(value);
        if (s.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0)
            s = "\"" + s.Replace("\"", "\"\"") + "\"";
        return s;
    }

    public static string ToCsv(System.Collections.IEnumerable header, System.Collections.IEnumerable rows)
    {
        var lines = new List<string> { string.Join(",", PureText.Iter(header).Select(Cell)) };
        foreach (var r in rows)
            lines.Add(string.Join(",", PureText.Iter(r).Select(Cell)));
        return string.Join("\r\n", lines) + "\r\n";
    }

    /// <summary>Return (header, rows as dicts). Strips a UTF-8 BOM and blank lines.</summary>
    public static (List<string> header, List<Dict> rows) ParseCsv(string? text)
    {
        if (!string.IsNullOrEmpty(text) && text![0] == '﻿')
            text = text.Substring(1);
        var rows = Reader(text ?? "").Where(r => r.Any(c => c.Trim().Length > 0)).ToList();
        if (rows.Count == 0)
            return (new List<string>(), new List<Dict>());
        var header = rows[0].Select(h => h.Trim()).ToList();
        var result = new List<Dict>();
        foreach (var r in rows.Skip(1))
        {
            var d = new Dict();
            for (var i = 0; i < header.Count; i++)
                d[header[i]] = i < r.Count ? r[i] : "";
            result.Add(d);
        }
        return (header, result);
    }

    private enum State { StartRecord, StartField, InField, InQuotedField, QuoteInQuotedField, EatCrnl }

    /// <summary>
    /// csv.reader(io.StringIO(text)) with the default "excel" dialect: the records of the text. Follows the
    /// state machine of CPython's _csv module, so quoted line breaks, doubled quotes, text after a closing
    /// quote and an unterminated last field give the same cells.
    /// </summary>
    internal static List<List<string>> Reader(string text)
    {
        var records = new List<List<string>>();
        var fields = new List<string>();
        var field = new StringBuilder();
        var state = State.StartRecord;

        void SaveField()
        {
            fields.Add(field.ToString());
            field.Clear();
        }

        // eol: the end of an input line (the line break itself is part of the line and comes first)
        void Process(char c, bool eol)
        {
            var newline = !eol && (c == '\n' || c == '\r');
            switch (state)
            {
                case State.StartRecord:
                    if (eol)
                        return; // empty line: an empty record
                    if (newline)
                    {
                        state = State.EatCrnl;
                        return;
                    }
                    state = State.StartField;
                    goto case State.StartField;
                case State.StartField:
                    if (newline || eol)
                    {
                        SaveField();
                        state = eol ? State.StartRecord : State.EatCrnl;
                    }
                    else if (c == '"')
                    {
                        state = State.InQuotedField;
                    }
                    else if (c == ',')
                    {
                        SaveField();
                    }
                    else
                    {
                        field.Append(c);
                        state = State.InField;
                    }
                    return;
                case State.InField:
                    if (newline || eol)
                    {
                        SaveField();
                        state = eol ? State.StartRecord : State.EatCrnl;
                    }
                    else if (c == ',')
                    {
                        SaveField();
                        state = State.StartField;
                    }
                    else
                    {
                        field.Append(c);
                    }
                    return;
                case State.InQuotedField:
                    if (eol)
                        return;
                    if (c == '"')
                        state = State.QuoteInQuotedField;
                    else
                        field.Append(c);
                    return;
                case State.QuoteInQuotedField:
                    if (!eol && c == '"')
                    {
                        field.Append(c);
                        state = State.InQuotedField;
                    }
                    else if (!eol && c == ',')
                    {
                        SaveField();
                        state = State.StartField;
                    }
                    else if (newline || eol)
                    {
                        SaveField();
                        state = eol ? State.StartRecord : State.EatCrnl;
                    }
                    else
                    {
                        field.Append(c);
                        state = State.InField;
                    }
                    return;
                case State.EatCrnl:
                    if (newline)
                        return;
                    if (eol)
                        state = State.StartRecord;
                    else
                        throw new CsvError("new-line character seen in unquoted field - do you need to open the file in universal-newline mode?");
                    return;
            }
        }

        var pos = 0;
        while (pos < text.Length)
        {
            // one record: one input line, or several when a quoted field spans lines
            fields = new List<string>();
            state = State.StartRecord;
            var complete = false;
            while (pos < text.Length)
            {
                var end = text.IndexOf('\n', pos);
                end = end < 0 ? text.Length : end + 1;
                for (var i = pos; i < end; i++)
                {
                    if (text[i] == '\0')
                        throw new CsvError("line contains NULL byte");
                    Process(text[i], false);
                }
                pos = end;
                Process('\0', true);
                if (state == State.StartRecord)
                {
                    complete = true;
                    break;
                }
            }
            if (!complete)
            {
                // the input ended inside a record
                if (field.Length != 0 || state == State.InQuotedField)
                    SaveField();
                else
                    break;
            }
            records.Add(fields);
        }
        return records;
    }

    /// <summary>
    /// One row as csv.writer(lineterminator=...) writes it (QUOTE_MINIMAL): a cell is quoted when it holds the
    /// delimiter, a quote or a character of the line terminator, and a row of one empty cell is written as "".
    /// </summary>
    internal static string WriteRow(IList<string> row, string lineTerminator)
    {
        var sb = new StringBuilder();
        for (var i = 0; i < row.Count; i++)
        {
            if (i > 0)
                sb.Append(',');
            var cell = row[i];
            var quote = cell.Any(c => c == ',' || c == '"' || lineTerminator.IndexOf(c) >= 0)
                        || (row.Count == 1 && cell.Length == 0);
            if (quote)
                sb.Append('"').Append(cell.Replace("\"", "\"\"")).Append('"');
            else
                sb.Append(cell);
        }
        return sb.Append(lineTerminator).ToString();
    }

    /// <summary>UTF-8 with BOM, line breaks written as they are in the text.</summary>
    public static void WriteFile(string path, string text) => File.WriteAllText(path, text, new UTF8Encoding(true));

    /// <summary>UTF-8 (a BOM is dropped); \r\n and \r become \n, as Python's text mode reads them.</summary>
    public static string ReadFile(string path)
    {
        var bytes = File.ReadAllBytes(path);
        // a file that is only the beginning of a BOM reads as empty in Python
        if (bytes.Length < 3 && bytes.SequenceEqual(new byte[] { 0xEF, 0xBB, 0xBF }.Take(bytes.Length)))
            return "";
        var start = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF ? 3 : 0;
        var text = new UTF8Encoding(false, true).GetString(bytes, start, bytes.Length - start);
        return text.Replace("\r\n", "\n").Replace('\r', '\n');
    }
}
