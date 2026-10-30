# "Change your code" on the ship (board/lvcode.py, POST /api/code {old, new}, answered from
# board/main.py's ota_route): refused without a signed-in session (401), refused for a bad
# new code (not 4 digits, the same as the old one: 400, no try counted), refused for a wrong
# current code (403, counted with the sign-in's tries: the fifth is the sign-in's own 429
# lockout, which then blocks signing in as well); on success the new code signs in and the
# old one doesn't, this phone's session stays, and crew.json is the same file with only that
# crew member's digest swapped (everyone else's entry, the salt, the layout byte-for-byte).
# The write is crew.json.new, read back, then a rename; a failure at any step (simulated)
# leaves crew.json and the codes in memory as they were and no stray files. Codes never
# appear in anything the ship prints. On CPython also: tools/bench.py's settings write
# (--code) reads the changed file and keeps the changed code for names it isn't given.
# Runs on CPython and MicroPython (stock and the game firmware's unix build):
#   python3 tests/test_code.py && micropython tests/test_code.py        (from game/)
import sys
import os
import json

try:
    import asyncio
except ImportError:  # pragma: no cover
    import uasyncio as asyncio

HERE = os.getcwd()
sys.path.insert(0, HERE)
sys.path.insert(0, HERE + "/board")
import lvweb  # noqa: E402
import lvcode  # noqa: E402
from lv import codes as K  # noqa: E402

ok = [0]


def check(name, cond, extra=""):
    if not cond:
        print("FAIL", name, extra)
        sys.exit(1)
    ok[0] += 1


ROOT = HERE + "/build/code-test"
DATA = ROOT + "/data"
PATH = DATA + "/crew.json"
SALT = b"code-test-salt16"
CODES = ["0000", "1111", "2222", "3333", "4444", None, "6666", "7777"]   # crew i: i four times


def mkdirs(p):
    cur = ""
    for part in p.split("/"):
        if not part:
            cur = "/"
            continue
        cur = cur + part if cur.endswith("/") else cur + "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


def read(p=PATH):
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def gone(p):
    return read(p) is None


mkdirs(DATA)
for x in (".new", ".old"):
    try:
        os.remove(PATH + x)
    except OSError:
        pass
# As tools/bench.py writes it (json.dump of the updater's format, one line).
ORIG = json.dumps(K.make_config(CODES, SALT)).encode()


def fresh():
    with open(PATH, "wb") as f:
        f.write(ORIG)


class Phone:
    def __init__(self):
        self.data = DATA
        self.book = K.load(PATH)
        self.tokens = {"tok2": 2, "tok3": 3, "tok5": 5, "tok0": 0}

    def who(self, req):
        return self.tokens.get(req.header("x-crew-token") or "")


class FakeShip:
    drops = []

    @staticmethod
    def drop(name):
        FakeShip.drops.append(name)
        sys.modules.pop(name, None)


class FakeLvweb:
    MAX_BODY = 512
    send_json = staticmethod(lvweb.send_json)
    dns_answer = staticmethod(lambda q, ip: None)


class Server:
    routed = []

    def __init__(self):
        self.phone = Phone()

    def get_phone(self):
        return self.phone

    async def route(self, req, w):
        Server.routed.append(req.path)


class Req:
    def __init__(self, method, path, body=b"", tok=None):
        self.method, self.path, self.q, self.body = method, path, {}, body
        self.hdr = {"x-crew-token": tok} if tok else {}

    def header(self, k):
        return self.hdr.get(k)


class Wr:
    def __init__(self):
        self.out = b""

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


src = open(HERE + "/board/main.py").read()
src = src[src.index("def http_admission"):src.index("\nasync def ota_ok")]
g = {"lvship": FakeShip, "asyncio": asyncio}
exec(src, g)
fresh()
srv = Server()
g["ota_hooks"](FakeLvweb, srv)
book = srv.phone.book


def http(method="POST", body=None, tok="tok2"):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    w = Wr()
    asyncio.run(srv.route(Req(method, "/api/code", body or b"", tok), w))
    head, _, b = w.out.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(b)


def signs_in(crew, code):
    return book.check(crew, code, 0)[0] == K.OK


# ---- refusals: nothing changes, no try counted (except a wrong current code)
check("route: GET is 404", http("GET")[0] == 404)
c, j = http(body={"old": "2222", "new": "9090"}, tok=None)
check("no session: 401", c == 401 and j.get("err") == "signed out", (c, j))
c, j = http(body={"old": "2222", "new": "9090"}, tok="someone-elses")
check("a session nobody has: 401", c == 401, (c, j))
for name, body in (("no body", b""), ("not JSON", b"old=2222"), ("no new", {"old": "2222"}),
                   ("no old", {"new": "9090"}), ("a list", b"[1, 2]"),
                   ("new 3 digits", {"old": "2222", "new": "909"}),
                   ("new 5 digits", {"old": "2222", "new": "90909"}),
                   ("new 8 digits", {"old": "2222", "new": "90909090"}),
                   ("new with a letter", {"old": "2222", "new": "90a0"}),
                   ("new with a space", {"old": "2222", "new": "90 0"}),
                   ("new a number, not a string", {"old": "2222", "new": 9090}),
                   ("new empty", {"old": "2222", "new": ""}),
                   ("new unicode digits", {"old": "2222", "new": "\u0661\u0662\u0663\u0664"}),
                   ("old 3 digits", {"old": "222", "new": "9090"}),
                   ("new is the old one", {"old": "2222", "new": "2222"})):
    c, j = http(body=body)
    check("refused, %s: 400" % name, c == 400 and j.get("err"), (c, j))
    check("refused, %s: crew.json as it was" % name, read() == ORIG)
    check("refused, %s: no try counted" % name, book.fails[2] == 0, book.fails)
check("refused: the old code still signs in", signs_in(2, "2222"))
c, j = http(body={"old": "2222", "new": "2222"})
check("same code: says so", "same" in j["err"], j)
c, j = http(body={"old": "2222", "new": "12345"})
check("bad format: says 4 digits", "4 digits" in j["err"], j)

# ---- a wrong current code: counted with the sign-in, then the sign-in's lockout
for i in range(K.MAX_TRIES - 1):
    c, j = http(body={"old": "0009", "new": "9090"}, tok="tok3")
    check("wrong current code %d: 403" % (i + 1), c == 403 and j.get("left") == K.MAX_TRIES - 1 - i, (c, j))
c, j = http(body={"old": "0009", "new": "9090"}, tok="tok3")
check("wrong current code %d: locked, 429" % K.MAX_TRIES, c == 429 and j.get("wait") == K.LOCK_MS // 1000, (c, j))
c, j = http(body={"old": "3333", "new": "9090"}, tok="tok3")
check("locked: even the right code is 429", c == 429, (c, j))
check("locked: signing in is locked too (one counter)", book.check(3, "3333", 0)[0] == K.LOCKED)
check("locked: the others aren't", book.fails[2] == 0 and book.until[2] is None)
check("wrong codes: crew.json as it was", read() == ORIG)
check("wrong codes: the session stays", srv.phone.who(Req("GET", "/", tok="tok3")) == 3)
# The lockout ends (as CodeBook.check does after LOCK_MS): the right code works again.
book.until[3] = None
book.fails[3] = 0
# a sign-in's wrong tries count toward the change too
book.check(3, "0009", 0)
c, j = http(body={"old": "0001", "new": "9090"}, tok="tok3")
check("sign-in tries and change tries share one count", c == 403 and j["left"] == K.MAX_TRIES - 2, (c, j))
book.fails[3] = 0
c, j = http(body={"old": "5555", "new": "9090"}, tok="tok5")
check("no code set up: 409", c == 409, (c, j))

# ---- success
c, j = http(body={"old": "2222", "new": "9090"})
check("change: 200", c == 200 and j == {"ok": True}, (c, j))
check("change: the new code signs in", signs_in(2, "9090"))
check("change: the old code doesn't", book.check(2, "2222", 0)[0] == K.WRONG)
book.fails[2] = 0
check("change: still signed in", srv.phone.who(Req("GET", "/", tok="tok2")) == 2)
new = read()
cfg = json.loads(new)
o = json.loads(ORIG)
check("change: crew 2's digest is the new code's", cfg["codes"][2] == K.digest(SALT, 2, "9090"))
check("change: everyone else's entry identical", all(cfg["codes"][i] == o["codes"][i] for i in range(8) if i != 2))
check("change: salt and schema identical", cfg["salt"] == o["salt"] and cfg["schema"] == o["schema"])
check("change: the file is the old one with one digest swapped, byte for byte",
      new == ORIG.replace(o["codes"][2].encode(), cfg["codes"][2].encode()) and len(new) == len(ORIG))
check("change: no crew.json.new / .old left", gone(PATH + ".new") and gone(PATH + ".old"))
check("change: a restart reads the new code", K.load(PATH).codes == book.codes)
check("change: K.load accepts it", K.load(PATH).is_set(2) and K.load(PATH).is_set(0))
check("change: lvcode dropped after each request", FakeShip.drops and all(x == "lvcode" for x in FakeShip.drops))
c, j = http(body={"old": "2222", "new": "1212"})
check("change again with the old code: 403", c == 403, (c, j))
book.fails[2] = 0
c, j = http(body={"old": "9090", "new": "2222"})
check("change back: 200, the file as it first was", c == 200 and read() == ORIG, (c, j))
# Two crew members may share a code: they sign in by name first (nothing to refuse).
c, j = http(body={"old": "0000", "new": "6666"}, tok="tok0")
check("a code someone else has: allowed", c == 200 and signs_in(0, "6666") and signs_in(6, "6666"), (c, j))
check("the other one's entry untouched", json.loads(read())["codes"][6] == o["codes"][6])
fresh()
srv.phone = Phone()
book = srv.phone.book

# ---- the write fails part-way (lvcode.save; this module's own copy)
p = Phone()


class Boom(OSError):
    pass


def fail_at(*where):
    def f(w):
        if w in where:
            raise Boom(w)
    return f


# (0.2.7: a refused rename is a failure too; there's no second route through crew.json.old)
for where in ("write", "read", "rename"):
    fresh()
    p = Phone()
    lvcode.fail = fail_at(where)
    s, j = lvcode.change(p, type("R", (), {"body": b'{"old": "3333", "new": "6060"}', "header": lambda self, k: "tok3"})())
    lvcode.fail = None
    name = "fail at " + where
    check(name + ": 500, says the current code still works", s == 500 and "still works" in j["err"], (s, j))
    check(name + ": crew.json byte-identical", read() == ORIG)
    check(name + ": the book in memory unchanged", p.book.codes[3] == json.loads(ORIG)["codes"][3])
    check(name + ": the current code still signs in", p.book.check(3, "3333", 0)[0] == K.OK)
    check(name + ": no crew.json.new / .old left", gone(PATH + ".new") and gone(PATH + ".old"))
# Review #3 m5: crew.json.bak (lvsafe's restore source) follows a change at once, so a
# crew.json lost before the next boot can't bring the old code back.
fresh()
p = Phone()
with open(PATH + ".bak", "wb") as f:
    f.write(ORIG)
s, j = lvcode.change(p, type("R", (), {"body": b'{"old": "3333", "new": "6060"}', "header": lambda self, k: "tok3"})())
with open(PATH + ".bak", "rb") as f:
    bk = f.read()
check("m5: the change also lands in crew.json.bak", s == 200 and bk == read() and bk != ORIG, s)
check("m5: no crew.json.bak.new left", gone(PATH + ".bak.new"))
fresh()
p = Phone()
with open(PATH + ".bak", "wb") as f:
    f.write(ORIG)
lvcode.fail = fail_at("bak")
s, j = lvcode.change(p, type("R", (), {"body": b'{"old": "3333", "new": "6060"}', "header": lambda self, k: "tok3"})())
lvcode.fail = None
check("m5: the .bak can't be written: still 200 (crew.json is)", s == 200 and p.book.check(3, "6060", 0)[0] == K.OK, s)
check("m5: ... and the stale .bak (the old code) is removed", gone(PATH + ".bak") and gone(PATH + ".bak.new"))
# A file someone edited so the digest isn't there once: refused, untouched.
with open(PATH, "wb") as f:
    f.write(ORIG.replace(b'"codes"', b'"was": "%s", "codes"' % json.loads(ORIG)["codes"][3].encode()))
weird = read()
p = Phone()
s, j = lvcode.change(p, type("R", (), {"body": b'{"old": "3333", "new": "6060"}', "header": lambda self, k: "tok3"})())
check("digest twice in the file: 500, untouched", s == 500 and read() == weird, (s, j))

# ---- never logged: nothing in lvcode prints
lsrc = open(HERE + "/board/lvcode.py").read()
check("lvcode prints nothing", "print(" not in lsrc and "say(" not in lsrc)

# ---- tools/bench.py --code still works on a changed file (CPython only: bench is a PC tool)
if sys.implementation.name == "cpython":
    fresh()
    p = Phone()
    s, j = lvcode.change(p, type("R", (), {"body": b'{"old": "3333", "new": "6060"}', "header": lambda self, k: "tok3"})())
    check("bench: changed first", s == 200)
    sys.path.insert(0, HERE + "/tools")
    import bench
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(bench.snippet(bench.SETTINGS, SET={}, DROP=[], CODES={0: "4321"}), {"__name__": "bench"})
    finally:
        os.chdir(cwd)
    after = K.load(PATH)
    check("bench --code: the named one set", after.check(0, "4321", 0)[0] == K.OK)
    check("bench --code: the changed code kept", after.check(3, "6060", 0)[0] == K.OK)
    check("bench --code: the others kept", after.codes[1] == json.loads(ORIG)["codes"][1] and after.codes[5] is None)
    with open(PATH + ".bak", "rb") as f:
        check("m5: bench --code writes crew.json.bak the same", json.loads(f.read()) == json.loads(read()))
    check("bench --code: the codes aren't printed", "4321" not in buf.getvalue() and "6060" not in buf.getvalue())
fresh()
check("other paths go to the game", Server.routed == [])
asyncio.run(srv.route(Req("POST", "/api/codes", b"{}", "tok2"), Wr()))
check("other paths go to the game", Server.routed == ["/api/codes"])
print("code: %d checks ok" % ok[0])
