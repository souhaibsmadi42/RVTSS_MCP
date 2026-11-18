# -*- coding: utf-8 -*-
"""Vectors for revit_mcp/pure/security.py -> security.json."""
from _lane_b import Recorder
from revit_mcp.pure import security as S

r = Recorder(S)
r.extra["constants"] = {"TOKEN_BODY_KEY": S.TOKEN_BODY_KEY, "TOKEN_QUERY_KEY": S.TOKEN_QUERY_KEY,
                        "TOKEN_HEADER": S.TOKEN_HEADER, "UNPROTECTED_PATHS": list(S.UNPROTECTED_PATHS),
                        "REDACTED": S.REDACTED}

FLAGS = [None, "", "1", "0", "true", "TRUE", " Yes ", "on", "allow", "Allowed", "false", "No", "OFF", "deny", "denied",
         "disabled", "maybe", "2", True, False, 1, 0, 2, 1.0, 0.0, "enabled", " ", "y", "n", "t", "f", "On\n"]
for v in FLAGS:
    r.call("parse_flag", v)
    r.call("parse_flag", v, True)
    r.call("parse_flag", v, False)
    r.call("parse_flag", v, default=None)

for a, b in [("abc", "abc"), ("abc", "abd"), (None, "abc"), ("abc", None), (None, None), ("", ""), ("a", ""), ("abc", "abcd"),
             (123, "123"), (123, 123), (1.5, "1.5"), (True, "True"), (u"\u00e9", u"\u00e9"), (u"\u00e9", "e"), ("A", "a"),
             ("x" * 64, "x" * 64), ("x" * 64, "x" * 63 + "y"), (u"\u0100", u"\u0000")]:
    r.call("constant_time_equal", a, b)

TOKENS = [
    ([], {}), ([{"_rvtss_token": "a"}], {}), ([None, {"rvtss_token": ["b"]}], {}), ([None, None, {"x-rvtss-token": "c"}], {}),
    ([{"_rvtss_token": ""}, {"rvtss_token": "q"}, {"X-RVTSS-Token": "h"}], {}),
    ([{"_rvtss_token": None}, {"rvtss_token": ""}, {"X-RVTSS-TOKEN": "h"}], {}),
    ([{"_rvtss_token": "body"}, {"rvtss_token": "q"}, {"X-RVTSS-Token": "h"}], {}),
    ([{}, {"rvtss_token": "q"}, {"X-RVTSS-Token": "h"}], {}), ([{}, {}, {}], {}), ([{"other": 1}, {"other": "x"}, {"Other": "y"}], {}),
    ([None, {"rvtss_token": ["first", "second"]}], {}), ([None, {"rvtss_token": []}, {"x-rvtss-token": "h"}], {}),
    ([{"_rvtss_token": 12345}], {}), ([None, {"rvtss_token": 77}], {}), ([None, {"rvtss_token": [5]}], {}),
    ([], {"headers": {"Content-Type": "json", "x-RvTsS-token": "mixed"}}), ([], {"query_params": {"rvtss_token": "kw"}}),
    ([], {"data": {"_rvtss_token": "kw-body", "x": 1}}), ([None, None, {"x-rvtss-token": ""}], {}),
    ([{"_rvtss_token": "0"}], {}), ([{"_rvtss_token": 0}, {"rvtss_token": "q"}], {}),
]
for args, kw in TOKENS:
    r.call("extract_token", *args, **kw)

for h in [None, "", "127.0.0.1", "localhost", "LOCALHOST", " localhost ", "::1", "[::1]", "127.1.2.3", "127.", "1270.0.0.1",
          "10.0.0.5", "0.0.0.0", "::", "*", "example.com", "[127.0.0.1]", "[[::1]]", "localhost.evil.com", "::ffff:127.0.0.1",
          " [::1] ", "[ ::1 ]", "192.168.1.1", " 0.0.0.0 ", " * ", "  "]:
    r.call("is_loopback", h)
    r.call("binds_all_interfaces", h)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123_-xyz"
TEXTS = [
    None, "", "nothing secret here", "wall " * 200, "z" * 600, "z" * 39, "z" * 40, "a" * 40 + " " + "b" * 39,
    "password=hunter2", "password: hunter2, user=bob", 'Password = "hunter2"', "{'api_key': 'abc123', 'name': 'x'}",
    '{"apiKey":"abc123","token" : "t0k3n"}', "api-key=K1;access_key=K2 secret:S3", "Authorization: Bearer abc.def",
    "authorization=Basic dXNlcjpwYXNz", "token=", "token = ,x", "my_token_value=5", "secrets=1", "PASSWD=x}y",
    "key sk-abcdefghijklmnop1234 end", "sk-short", "ghp_" + "A1b2" * 6, "gho_" + "x" * 19, "xoxb-12345-abcde-XYZ",
    "AKIAABCDEFGHIJKLMNOP", "AKIAabcdefghijklmnop", JWT, "jwt " + JWT + " tail", "eyJabc.def.ghi",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN PUBLIC KEY-----", "id 123e4567-e89b-12d3-a456-426614174000 ok",
    "123e4567-e89b-12d3-a456-426614174000-123e4567-e89b-12d3-a456-426614174000",
    "guid 123e4567e89b12d3a456426614174000aaaaaaaa", "f" * 36, "-" * 50, "=" * 45, "a" * 20 + "/" + "b" * 25,
    "path C:\\Users\\x\\" + "d" * 45 + "\\file.rvt", "url https://h/x?token=abc123&y=2", "a=b password=p1 token=t2 secret=s3",
    "connection_string=Server=x;Password=pw", "private_key: abc", "bearer abc", "SECRET : 'quoted value' rest",
    u"mot de passe: \u00e9t\u00e9 password=\u00e9t\u00e9", "password=a,b", "password='a b'", 'token="abc" token2="def"',
    "tokens", "apikey:1 api_key:2 api-key:3 apiKey:4 APIKEY:5", "x" * 45 + "." + "y" * 45, "line1\npassword=p\nline3",
    "Password\t=\tp", "passwordx=1", "xpassword=1", "password==x", "password=:x", "access-key = 'AK'",
]
for t in TEXTS:
    r.call("redact", t)
    for n in (None, 0, 5, 20, 100, 1000, -3):
        r.call("redact", t, n)
r.call("redact", "wall " * 200, max_len=100)
r.call("redact", 12345)
r.call("redact", 1.5, 2)
r.call("redact", True)
r.call("redact", ["password=x"])

MAPPINGS = [
    {"name": "Mark", "password": "p", "nested": [{"apiKey": "k", "v": "ok"}]}, None, "password=p", 5, 2.5, True, [], {},
    ["a", "token=abc", ["z" * 50, {"Secret": 1}], None, 3],
    {"Authorization": "Bearer x", "bearer_token": None, "my_api-key": [1, 2], "API_KEY_ID": {"a": 1}, "keys": "k",
     "connectionString": "cs", "connection_string": "cs", "private-key": "pk", "accesskey": "ak", "access_key": "ak",
     "note": "password=inline", "long": "q" * 44, "uuid": "123e4567-e89b-12d3-a456-426614174000", "n": 1, "f": 1.5,
     "b": False, "none": None, "deep": {"deeper": {"passwd": "x", "ok": ["token: t"]}}},
    {"tokens": ["a", "b"], "Token": "t", "TOKEN": 5, "untouched": {"k": "v"}},
    [[[["secret=1"]]]], {"a": {"b": {"c": {"PASSWORD": {"x": 1}}}}},
]
for m in MAPPINGS:
    r.call("redact_mapping", m)
r.write("security")
