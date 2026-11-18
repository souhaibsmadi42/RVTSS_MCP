# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/sharedparams.py -> sharedparams.json.
Run: uv run --project . python host/tests/vectors/gen_sharedparams.py"""
import base64
import os
import tempfile

from _lane_c import Recorder
from revit_mcp.pure import sharedparams as SP

rec = Recorder("sharedparams")

SHARED_FILE = (
    "# This is a Revit shared parameter file.\n"
    "# Do not edit manually.\n"
    "*META\tVERSION\tMINVERSION\n"
    "META\t2\t1\n"
    "*GROUP\tID\tNAME\n"
    "GROUP\t1\tIdentity\n"
    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEINPROPERTIES\n"
    "PARAM\t5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01\tFire Rating\tTEXT\t\t1\t1\tFire resistance\t1\t0\n"
    "PARAM\t5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01\tFire Rating 2\tTEXT\t\t1\t1\t\t1\t0\n"
    "PARAM\tnot-a-guid\tFrame Depth\tLENGTH\t\t9\t1\t\t1\t0\n"
)
G1 = "5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a01"
G2 = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
G3 = "00000000-0000-0000-0000-000000000003"
HDR = "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\tHIDEINPROPERTIES\n"

for text in (G1, G2, G1.upper(), " " + G1 + " ", G1 + "\n", "\t" + G1 + "\r\n", G1 + "\n\n", G1 + "x", "x" + G1, "5b3e5f1c",
             "", None, "   ", G1.replace("-", ""), "{" + G1 + "}", G1[:-1], G1[:-1] + "g", G1.replace("-", "_"),
             G1 + " " + G1, "5b3e5f1c-0d6a-4f0e-9a3c-2b7f3b1e9a0١"):
    rec.call("is_guid", SP.is_guid, text)

TEXTS = [
    SHARED_FILE,
    SHARED_FILE.replace("\n", "\r\n"),
    SHARED_FILE.replace("\n", "\r"),  # one line for io.StringIO
    "",
    "\n\n   \n# only comments\n",
    "PARAM\t" + G1 + "\tEarly\tTEXT\t\t1\n" + SHARED_FILE,  # row before its header
    "GROUP\t1\tX\nMETA\t2\t1\nUNKNOWN\ta\tb\n",
    # no trailing newline, missing columns, extra columns
    "*GROUP\tID\tNAME\nGROUP\t1\tA\nGROUP\t2\nGROUP\nGROUP\t3\tC\textra\n" + HDR
    + "PARAM\t" + G1 + "\tShort\nPARAM\t" + G2 + "\tLong\tTEXT\t\t3\t0\tdesc\t0\t1\tmore\tand more",
    # header with only some columns; a header given twice (the later one wins from there on)
    "*GROUP\tNAME\nGROUP\tNoId\n*PARAM\tNAME\tGUID\nPARAM\tP1\t" + G1 + "\n*PARAM\tGUID\tNAME\tGROUP\nPARAM\t" + G2 + "\tP2\t1\n"
    "*GROUP\tID\tNAME\nGROUP\t1\tLate group\n",
    # duplicates: same GUID in two cases, same name with different GUIDs and case
    "*GROUP\tID\tNAME\nGROUP\t1\tG\n" + HDR
    + "PARAM\t" + G2 + "\tWidth\tLENGTH\t\t1\t1\t\t1\t0\n"
    + "PARAM\t" + G2.lower() + "\tWIDTH\tLENGTH\t\t1\t1\t\t1\t0\n"
    + "PARAM\t" + G3 + "\twidth\tLENGTH\t\t1\t1\t\t1\t0\n"
    + "PARAM\t" + G1 + "\tZeta\tTEXT\t\t1\t1\t\t1\t0\n"
    + "PARAM\t" + G1 + "\tAlpha\tTEXT\t\t1\t1\t\t1\t0\n"
    + "PARAM\t" + G1 + "\tZeta\tTEXT\t\t1\t1\t\t1\t0\n",
    # values of the flags; indented comment; a line of tabs; a comment that does not start the line
    "*GROUP\tID\tNAME\nGROUP\t1\tG\n" + HDR
    + "PARAM\t" + G1 + "\tA\tYESNO\tcat\t1\t0\td\t0\t1\n"
    + "PARAM\t" + G2 + "\tB\tYESNO\t\t1\t\t\t\t\n"
    + "PARAM\t" + G3 + "\tC\tYESNO\t\t1\ttrue\t\tyes\t 1\n"
    + "  # indented\n\t\t\t\nPARAM\t \tD # x\n",
    # header names are case sensitive; duplicate header columns; group 'null'; unicode
    "*group\tID\tNAME\ngroup\t1\tlower\n*GROUP\tID\tID\tNAME\nGROUP\t1\t2\tDouble id\n*GROUP\tNAME\nGROUP\tNo id\n"
    "*PARAM\tGUID\tNAME\tGROUP\nPARAM\t" + G1 + "\tÉtage – niveau\tnull\nPARAM\t" + G2 + "\t墙\t2\n",
    "*META\tVERSION\tMINVERSION\nMETA\t2\t1\nMETA\t3\n",
    "﻿# bom kept by the caller\n*GROUP\tID\tNAME\nGROUP\t1\tG\n",
    "*\ta\tb\n\tx\ty\n*PARAM\nPARAM\nPARAM\t\n",
    "*GROUP\tID\tNAME\rGROUP\t1\tA\r\n*PARAM\tGUID\tNAME\tGROUP\r\nPARAM\t" + G1 + "\tP\t1\r\r\n",
]
for text in TEXTS:
    rec.call("parse", SP.parse, text)

P = [{"guid": G1, "name": "A"}, {"guid": G1.upper(), "name": "B"}, {"guid": G2, "name": "a"}, {"guid": G3, "name": "C"},
     {"guid": G3, "name": "C"}, {"guid": "", "name": ""}, {"guid": "", "name": ""}, {"guid": G1, "name": "A"}]
rec.call("find_duplicates", SP.find_duplicates, P)
rec.call("find_duplicates", SP.find_duplicates, [])
rec.call("find_duplicates", SP.find_duplicates, P[:1])
rec.call("find_duplicates", SP.find_duplicates, list(reversed(P)))
rec.call("find_duplicates", SP.find_duplicates, [{"guid": G1}])  # KeyError
rec.call("find_duplicates", SP.find_duplicates, [{"name": "x"}])  # KeyError

# ---------------------------------------------------------------- files: bytes in, text out
FILES = [
    b"\xff\xfe" + SHARED_FILE.encode("utf-16-le"),
    b"\xfe\xff" + SHARED_FILE.encode("utf-16-be"),
    b"\xef\xbb\xbf" + SHARED_FILE.encode("utf-8"),
    SHARED_FILE.encode("utf-8"),
    u"*GROUP\tID\tNAME\nGROUP\t1\tÉtage 墙\n".encode("utf-8"),
    b"\xef\xbb\xbf" + u"*GROUP\tID\tNAME\nGROUP\t1\tÉtage 墙\n".encode("utf-8"),
    b"\xff\xfe" + u"*GROUP\tID\tNAME\r\nGROUP\t1\tÉtage 墙 \U0001F600\r\n".encode("utf-16-le"),
    u"*GROUP\tID\tNAME\nGROUP\t1\tÉtage café\n".encode("latin-1"),  # not UTF-8: latin-1 fallback
    b"*GROUP\tID\tNAME\nGROUP\t1\t\x80\x81\xfe\xff\n",
    b"",
    b"\xff\xfe",
    b"\xef\xbb\xbf",
    b"\xef\xbb",
    b"plain ascii",
]
files = []
tmp = tempfile.mkdtemp(prefix="rvtss_sp_")
for i, data in enumerate(FILES):
    path = os.path.join(tmp, "sp%d.txt" % i)
    with open(path, "wb") as fh:
        fh.write(data)
    entry = {"base64": base64.b64encode(data).decode("ascii")}
    try:
        entry["text"] = SP.read_text(path)
        entry["parsed"] = SP.parse_file(path)
    except Exception as ex:
        entry["error"] = type(ex).__name__
    files.append(entry)
    os.remove(path)
os.rmdir(tmp)
rec.extra["files"] = files
rec.call("read_text", SP.read_text, os.path.join(tmp, "missing.txt"))
rec.cases[-1]["args"] = ["<missing file>"]

rec.save()
