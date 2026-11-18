# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/catalog.py -> catalog.json."""
from _lane_b import Recorder
from revit_mcp.pure import catalog as C

r = Recorder(C)
r.extra["catalog_units"] = dict(C.CATALOG_UNITS)
r.extra["rvtss_to_catalog"] = dict(C.RVTSS_TO_CATALOG)
r.extra["spec_to_catalog"] = dict(C.SPEC_TO_CATALOG)

for cell in ["Width##LENGTH##MILLIMETERS", "Fire Rating##OTHER##", "Name", "", "A##length##feet", " A ## angle ## degrees ",
             "A##AREA##SQUARE_METERS", "A##VOLUME##CUBIC_FEET", "A##LENGTH##FURLONGS", "A##LENGTH", "A####", "##", "A##B##C##D",
             "A#B", "A##ANGLE##DECIMAL_DEGREES", "A##ANGLE##RADIANS", u"Höhe##LENGTH##METERS", "A## ##  ", "A#####INCHES"]:
    r.call("parse_header_cell", cell)

TEXTS = [
    ",Width##LENGTH##MILLIMETERS,Height##LENGTH##MILLIMETERS,Fire Rating##OTHER##\nD1 900x2100,900,2100,60 min\n",
    "Name,Width##LENGTH##MILLIMETERS\nA,1\n", "", "\n\n", " , \n", ",W##LENGTH##FEET\n", ",W##LENGTH##FEET\nA,1,2\n",
    ",W##LENGTH##FEET\n,1\n", ",W##LENGTH##FEET\n  ,1\n", ",W##LENGTH##FEET,H##LENGTH##FEET\nA,1\nB\nC,,3\nD, ,\n",
    ",W##LENGTH##FEET\r\nA,1\r\n\r\nB,2\r\n", ',W##LENGTH##FEET,"Note, long##OTHER##"\n"D 900, std",3,"say ""hi"""\n',
    " ,W##LENGTH##FEET\n A , 1 \n", ",W##LENGTH##FEET,W##LENGTH##METERS\nA,1,2\n", ",\nA\n", ",\nA,1\n",
    ",W##LENGTH##FEET\nA,1\nA,2\n", u",Höhe##LENGTH##METERS\nTür,2.1\n", ",A##ANGLE##DEGREES,V##VOLUME##CUBIC_METERS\nT,45,1.5\n",
    "\n,W##LENGTH##FEET\n\nA,1\n", ",W##LENGTH##FEET\nA,1\n,2\n", ",W##LENGTH##FEET\nA,1\nB,2,3,4\n", "x", ",W\nA,1",
    ',W##LENGTH##FEET\n"A\nB",1\n', ",W##OTHER##\nA,  spaced value  \n",
]
for text in TEXTS:
    r.call("parse", text)

COLS = [{"name": "Width", "spec": "length", "unit": "mm"}, {"name": "Fire Rating", "spec": "text"},
        {"name": "Area", "spec": "area", "unit": "m2"}, {"name": "Angle", "spec": "angle", "unit": "deg"},
        {"name": "Vol", "spec": "volume", "unit": "ft3"}, {"name": "Count", "spec": "integer", "unit": "mm"},
        {"name": "Odd", "spec": "length", "unit": "furlong"}, {"name": "NoSpec"}, {"name": "NoneSpec", "spec": None, "unit": None},
        {"name": "Unknown", "spec": "currency", "unit": "m"}, {"name": "Rad", "spec": "angle", "unit": "rad"},
        {"name": "Internal", "spec": "length", "unit": "internal"}, {"name": "Yes", "spec": "yesno"}]
TYPES = [
    {"name": "D 900, std", "values": {"Width": 900, "Fire Rating": "60"}},
    {"name": "Plain", "values": {"Width": 900.5, "Fire Rating": 'say "hi"', "Area": 1, "Angle": 45.0, "Vol": None,
                                 "Count": 3, "Yes": True, "NotAColumn": "ignored"}},
    {"name": "", "values": {}}, {"name": "Multi\nline", "values": {"Fire Rating": "a\nb", "Yes": False, "Width": 0}},
    {"name": 5, "values": {"Width": "", "Fire Rating": " padded "}}, {"name": u"Tür", "values": {"Fire Rating": u"é"}},
]
r.call("write", COLS, TYPES)
r.call("write", COLS[:2], TYPES[:1])
r.call("write", [], TYPES)
r.call("write", [], [])
r.call("write", [], [{"name": "", "values": {}}, {"name": "x", "values": {}}])
r.call("write", COLS, [])
r.call("write", [{"name": "Only"}], [{"name": "", "values": {"Only": ""}}, {"name": "", "values": {"Only": None}}])
r.call("write", [{"spec": "length"}], [])
r.call("write", COLS[:1], [{"name": "x"}])
r.call("write", COLS[:1], [{"values": {}}])
r.call("write", ["notadict"], [])
r.call("write", [{"name": "a,b", "spec": "length", "unit": "m"}, {"name": 'q"q', "spec": "number"}], [{"name": "n", "values": {"a,b": "1,5"}}])

# round trip: what write produces must parse back
text = C.write(COLS, TYPES[:2])
r.call("parse", text)
r.write("catalog")
