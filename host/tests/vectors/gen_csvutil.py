# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/csvutil.py -> csvutil.json."""
import binascii
import csv
import io
import os
import tempfile

from _lane_b import Recorder
from revit_mcp.pure import csvutil as C

r = Recorder(C)

for v in [None, True, False, "", "a", "a,b", 'say "hi"', "line\nbreak", "cr\rhere", 0, 1, -5, 2.5, 1.0, " pad ", ";", "'",
          u"été", '"', ",", "\n"]:
    r.call("_cell", v)

TABLES = [
    (["ElementId", "Comments"], [[1, 'He said "hi", ok'], [2, u"été\nline"], [3, None]]),
    (["a"], [[True]]), (["a", "b"], []), ([], []), ([], [[], [1]]), (["a,b", 'c"d'], [["x\r\ny", False, None, 2.5]]),
    (["h"], [["1"], [""], [None], ["  "]]), ([1, None, True], [[0, 0.5, -1]]), (["a"], ["xy", "z"]),
]
for header, rows in TABLES:
    r.call("to_csv", header, rows)

TEXTS = [
    "", None, u"﻿", "a,b\r\n1,2\r\n", u"﻿a,b\r\n1,2\r\n", "a,b\n1,2\n", "a,b\n1,2", "a,b", "a,b\n",
    " a , b \n 1 , 2 \n", "a,b\n\n1,2\n\n\n3,4\n", "a,b\n , \n1,2\n", "a,b,c\n1\n1,2\n1,2,3\n1,2,3,4\n",
    "a,a,b\n1,2,3\n", "a,,b\n1,2,3\n", ",\n1,2\n", "\n\na,b\n1,2\n",
    'a,b\n"x,y","he said ""hi"""\n', 'a,b\n"multi\nline",2\n', 'a,b\n"multi\r\nline",2\r\n3,4\r\n',
    'a,b\n"unterminated,2\n3,4\n', 'a,b\n1,"', 'a,b\n1,"x', 'a,b\n"x"y,2\n', 'a,b\nx"y,2\n', 'a,b\n"x" ,2\n', 'a,b\n "x",2\n',
    'a,b\n"",""\n', 'a,b\n"",x\n', 'a,b\n""\n', 'a,b\n"""",""""""\n', "a,b\r1,2\r", "a,b\n1,2\r\n\r\n", "a,b\r\r\n1,2\n",
    "a\n1\n2\n3", "a,b\n1,2,\n", "a,b\n,\n", "a,b\n,x\n", u"näme,v\né,1\n", "a;b\n1;2\n", "a\tb\n1\t2\n",
    '"a","b"\n"1","2"\n', '"a,b"\n"1,2"\n', "a,b\n1,2\n\n", "   \n\t\n", "a , b,c \nx", 'a,b\n"x"\n', 'a\n"line1\nline2\nline3"\n',
    'a,b\n"q"",",z\n', "a,b\n'x,y',2\n", 'a,b\n1,2\n"3', 'a,b\n1,"2\n', "x\r\n", "\r\n", "a,b\n\r\n1,2", "a,b\n1,2\n \n",
]
for text in TEXTS:
    r.call("parse_csv", text)
    if text is not None:
        # the raw records of csv.reader, to check the reader itself
        r.call_as("reader", lambda t: list(csv.reader(io.StringIO(t))), (text,), {})

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "f.csv")
FILES = ["", "a,b\r\n1,2\r\n", u"été,中\r\nx\ny\rz\r\n", u"﻿already", "no newline", "\n\n", "a\r\rb\r\n\nc"]
for text in FILES:
    C.write_file(path, text)
    with open(path, "rb") as fh:
        raw = fh.read()
    # write_file: the bytes on disk; read_file: what comes back from those bytes
    r.cases.append({"fn": "write_file", "args": [text], "kwargs": {}, "out": binascii.hexlify(raw).decode("ascii")})
    r.cases.append({"fn": "read_file", "args": [binascii.hexlify(raw).decode("ascii")], "kwargs": {}, "out": C.read_file(path)})
for raw in [b"plain no bom\r\nx", b"\xef\xbb\xbf\xef\xbb\xbftwice", b"\xef\xbb", b"a\rb\r\nc\n", b"\xc3\xa9"]:
    with open(path, "wb") as fh:
        fh.write(raw)
    r.call_as("read_file", C.read_file, (path,), {}, shown_args=[binascii.hexlify(raw).decode("ascii")])
os.remove(path)
os.rmdir(tmp)
r.write("csvutil")
