"""The built-in sign-in, Shiori's device pairing and per-user preferences (vaultkit.signin, Machiya's identity plan
phase 6), wired into the board. GET/POST /signin, POST /signout and POST /api/pair answer before the gate (they are
how a caller gets past it); GET/PUT /api/prefs after it (konbini `read`). Each setup runs in its own process on
127.0.0.1, serving a throwaway vault; the identity file is written with vaultkit's own helpers. Without the file every
one of these routes is 404, as before (tests/test_identity.py and tests/test_auth.py keep covering the gates)."""
import json, os, re, socket, stat, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request
from urllib.parse import quote, urlencode

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from vaultkit import identity  # noqa: E402

NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - topic/search\n"
        "project: kura\nstatus: wip\n---\n# Kura\n")
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
OWNER_PW, READER_PW = "owner pass 1", "reader pass 1"


def write_identity(folder):
    """The owner and a reader (people with passwords), an agent with a token, a person granted nothing, and a pairing
    code for the owner's phone. -> (path, {name: token}, pairing code)."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "session.key"), "w") as f:
        f.write("k" * 43)
    data = {"version": 1, "session_key_file": "session.key", "principals": {
        "owner": {"id": "ownerid000000001", "kind": "person", "owner": True,
                  "password": identity.hash_password(OWNER_PW)},
        "reader": {"id": "readerid00000001", "kind": "person", "tailscale": ["reader@example"],
                   "password": identity.hash_password(READER_PW), "grants": {"konbini": ["read"]}},
        "nobody": {"id": "nobodyid00000001", "kind": "person", "tailscale": ["nobody@example"]},
        "mcp": {"kind": "agent", "grants": {"konbini": ["read", "write"]}}}}
    tokens = {"mcp": identity.new_token(data, "mcp", "test")}
    code, _ = identity.new_pairing(data, "owner", "iPhone")
    path = os.path.join(folder, "identity.toml")
    identity.write_file(path, data)
    return path, tokens, code


def start(identity_file=True, board_url=False, **extra):
    """A board on a free port. board_url=True sets KANBAN_BOARD_URL to its plain-http address."""
    d = tempfile.mkdtemp()
    os.makedirs(d + "/vault/Projects")
    open(d + "/vault/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    path, tokens, code = write_identity(d + "/identity")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_USERS="", PYTHONDONTWRITEBYTECODE="1")
    for k in ("KANBAN_AUTH", "KANBAN_AUTH_HEADER", "KANBAN_SIGNIN", "KANBAN_BIND_BEHIND_PROXY", "KANBAN_BOARD_URL",
              "MACHIYA_IDENTITY_FILE", "MACHIYA_COOKIE_DOMAIN"):
        env.pop(k, None)
    if identity_file:
        env["MACHIYA_IDENTITY_FILE"] = path
    if board_url:
        env["KANBAN_BOARD_URL"] = "http://127.0.0.1:%d" % port
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, port, d, tokens, code
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(port, method, path, headers=None, body=None):
    """-> (status, headers, body text). A dict body goes as JSON."""
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        headers = dict({"Content-Type": "application/json"}, **(headers or {}))
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def sign_in(port, origin, name="owner", password=OWNER_PW, next="/"):
    return call(port, "POST", "/signin", dict(FORM, Origin=origin),
                urlencode({"name": name, "password": password, "next": next}).encode())


def session(set_cookie):
    m = re.match(r"machiya_session=([^;]+)", set_cookie or "")
    assert m, set_cookie
    return {"Cookie": "machiya_session=" + m.group(1)}


# -- sign-in on, no KANBAN_BOARD_URL: the cookie is Secure and only an https page naming the board's own Host counts
# (tailscale serve or another https proxy in front; the test speaks plain http behind it, as the proxy would)
proc, port, d, tokens, code = start(KANBAN_SIGNIN="1")
try:
    HTTPS = "https://127.0.0.1:%d" % port
    MCP = {"Authorization": "Bearer " + tokens["mcp"]}

    # the way in, before the gate
    st, h, body = call(port, "GET", "/signin?next=/p/kura")
    assert st == 200 and 'name="password"' in body and 'value="/p/kura"' in body, (st, body[:300])
    assert h["Cache-Control"] == "no-store" and h["X-Frame-Options"] == "DENY", dict(h)
    assert "Kura" not in body                                           # no board data on the way in
    # the sign-in page's look answers before the gate; the board's own files and data don't
    assert call(port, "GET", "/static/machiya.css")[0] == 200
    assert call(port, "GET", "/static/icons/konbini.svg")[0] == 200
    assert call(port, "GET", "/static/board.js")[0] == 401
    # a browser without a session: 401 with a link to /signin?next=<where it was going>
    st, h, body = call(port, "GET", "/p/kura?x=1")
    assert st == 401 and 'href="/signin?next=%s"' % quote("/p/kura?x=1", safe="") in body, (st, body[-600:])
    assert h["Cache-Control"] == "no-store" and "Kura" not in body.replace("Konbini", ""), dict(h)
    st, _, body = call(port, "GET", "/api/cards")
    assert (st, json.loads(body)) == (401, {"error": "sign in first"}), (st, body)     # the API stays JSON

    # cross-site sign-in is refused: another site, no Origin at all, a plain-http page (the cookie is Secure here)
    assert sign_in(port, "https://evil.example")[0] == 403
    assert call(port, "POST", "/signin", FORM, urlencode({"name": "owner", "password": OWNER_PW}).encode())[0] == 403
    assert sign_in(port, "http://127.0.0.1:%d" % port)[0] == 403
    # a wrong password: the page again, one message; a body over the limit: 413
    st, _, body = sign_in(port, HTTPS, password="wrong")
    assert st == 401 and "Wrong name or password." in body and OWNER_PW not in body, st
    st, h, _ = call(port, "POST", "/signin", dict(FORM, Origin=HTTPS), b"x" * 5000)
    assert st == 413, st

    # the full flow: sign in, read the board with the cookie, see Account in Settings, sign out
    st, h, _ = sign_in(port, HTTPS, next="/p/kura")
    assert st == 303 and h["Location"] == "/p/kura", (st, dict(h))
    assert "Secure" in h["Set-Cookie"] and "HttpOnly" in h["Set-Cookie"], h["Set-Cookie"]
    OWNER = session(h["Set-Cookie"])
    assert call(port, "GET", "/p/kura", OWNER)[0] == 200
    st, _, body = call(port, "GET", "/api/cards", OWNER)
    assert st == 200 and json.loads(body)["cards"][0]["slug"] == "kura", st
    st, _, body = call(port, "GET", "/settings", OWNER)
    assert st == 200 and 'action="/signout"' in body and "Signed In As" in body and ">owner<" in body, st
    assert 'action="/signout"' not in call(port, "GET", "/settings", MCP)[2]      # a token: nothing to sign out of
    # a session principal writes like any other: the board's same-origin rule for its own pages still holds
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(OWNER, Origin=HTTPS), {"next": "signed in"})
    assert st == 200, (st, body)
    assert call(port, "PATCH", "/api/cards/kura", dict(OWNER, Origin="https://evil.example", **{"X-Agent": "x"}),
                {"next": "csrf"})[0] == 403

    # prefs: per principal, same-origin for a cookie, a token exempt
    st, h, body = call(port, "GET", "/api/prefs", OWNER)
    assert (st, json.loads(body)) == (200, {"prefs": {}}) and h["Cache-Control"] == "no-store", (st, body)
    put = {"prefs": {"board.group": "family", "theme": "night"}}
    assert call(port, "PUT", "/api/prefs", OWNER, put)[0] == 403                      # a cookie and no Origin
    assert call(port, "PUT", "/api/prefs", dict(OWNER, **{"X-Agent": "x"}), put)[0] == 403   # X-Agent doesn't excuse it
    assert call(port, "PUT", "/api/prefs", dict(OWNER, Origin="https://evil.example"), put)[0] == 403
    assert call(port, "PUT", "/api/prefs", dict(OWNER, Referer="https://evil.example/x"), put)[0] == 403
    st, _, body = call(port, "PUT", "/api/prefs", dict(OWNER, Origin=HTTPS), put)
    assert (st, json.loads(body)) == (200, {"prefs": {"board.group": "family", "theme": "night"}}), (st, body)
    st, _, body = call(port, "PUT", "/api/prefs", dict(OWNER, Origin=HTTPS), {"prefs": {"theme": None}})
    assert json.loads(body) == {"prefs": {"board.group": "family"}}, body                # null removes
    assert call(port, "PUT", "/api/prefs", dict(OWNER, Origin=HTTPS), {"prefs": {"Bad Key": "x"}})[0] == 400
    # a token needs neither Origin nor X-Agent (a browser never adds Authorization on its own) and has its own prefs
    st, _, body = call(port, "PUT", "/api/prefs", MCP, {"prefs": {"agent.note": "mine"}})
    assert (st, json.loads(body)) == (200, {"prefs": {"agent.note": "mine"}}), (st, body)
    assert json.loads(call(port, "GET", "/api/prefs", OWNER)[2]) == {"prefs": {"board.group": "family"}}
    # a reader (konbini read only) keeps preferences too; a Tailscale login rides along with a browser: same-origin
    st, h, _ = sign_in(port, HTTPS, name="reader", password=READER_PW)
    READER = session(h["Set-Cookie"])
    assert json.loads(call(port, "GET", "/api/prefs", READER)[2]) == {"prefs": {}}
    TS_READER = {"Tailscale-User-Login": "reader@example"}
    assert call(port, "PUT", "/api/prefs", TS_READER, {"prefs": {"x": "1"}})[0] == 403
    assert call(port, "PUT", "/api/prefs", dict(TS_READER, Origin=HTTPS), {"prefs": {"x": "1"}})[0] == 200
    assert json.loads(call(port, "GET", "/api/prefs", READER)[2]) == {"prefs": {"x": "1"}}   # one principal, any proof
    assert json.loads(call(port, "GET", "/api/prefs", OWNER)[2]) == {"prefs": {"board.group": "family"}}
    # after the gate: no proof 401, nobody's grant 403
    assert call(port, "GET", "/api/prefs")[0] == 401
    assert call(port, "PUT", "/api/prefs", {"Origin": HTTPS}, {"prefs": {"x": "1"}})[0] == 401
    assert call(port, "GET", "/api/prefs", {"Tailscale-User-Login": "nobody@example"})[0] == 403
    assert call(port, "POST", "/api/prefs", dict(OWNER, Origin=HTTPS), {"prefs": {}})[0] == 405
    # the file: next to KANBAN_DB, readable by the board's user only
    assert stat.S_IMODE(os.stat(d + "/db/prefs.sqlite3").st_mode) == 0o600

    # pairing: no cookie, so no same-origin rule and no X-Agent; the code gives a working device token
    assert call(port, "POST", "/api/pair", None, {"code": "WRONG-CODE", "device": "iPhone"})[0] == 401
    assert call(port, "POST", "/api/pair", FORM, b"code=x")[0] == 415
    st, h, body = call(port, "POST", "/api/pair", None, {"code": code.lower(), "device": "iPhone"})
    out = json.loads(body)
    assert st == 200 and out["principal"] == "owner" and out["token"].startswith("mcd_"), (st, body)
    assert h["Cache-Control"] == "no-store" and "Set-Cookie" not in h, dict(h)
    DEVICE = {"Authorization": "Bearer " + out["token"]}
    assert call(port, "GET", "/api/cards", DEVICE)[0] == 200
    assert json.loads(call(port, "GET", "/api/prefs", DEVICE)[2]) == {"prefs": {"board.group": "family"}}   # the owner's
    assert call(port, "PUT", "/api/prefs", DEVICE, {"prefs": {"shiori.sync": "on"}})[0] == 200          # token: exempt
    assert call(port, "GET", "/api/pair")[0] == 405 and call(port, "GET", "/signout")[0] == 405

    # sign-out: same-origin only, then the cookie is cleared
    assert call(port, "POST", "/signout", dict(OWNER, Origin="https://evil.example"), b"")[0] == 403
    st, h, _ = call(port, "POST", "/signout", dict(OWNER, Origin=HTTPS), b"")
    assert st == 303 and h["Location"] == "/" and "Max-Age=0" in h["Set-Cookie"], (st, dict(h))
finally:
    proc.kill()
    proc.wait()

# -- plain http (a LAN or localhost install): KANBAN_BOARD_URL=http://... makes the cookie plain and names the one
# origin the sign-in and prefs checks accept; without it (above) a plain-http page is refused
proc, port, d, tokens, code = start(board_url=True, KANBAN_SIGNIN="1")
try:
    ORIGIN = "http://127.0.0.1:%d" % port
    assert sign_in(port, "http://localhost:%d" % port)[0] == 403        # not the board's address
    assert sign_in(port, "https://127.0.0.1:%d" % port)[0] == 403       # nor another scheme
    st, h, _ = sign_in(port, ORIGIN)
    assert st == 303 and "Secure" not in h["Set-Cookie"], dict(h)
    OWNER = session(h["Set-Cookie"])
    assert call(port, "PUT", "/api/prefs", dict(OWNER, Origin=ORIGIN), {"prefs": {"a": "1"}})[0] == 200
    assert call(port, "PUT", "/api/prefs", dict(OWNER, Origin="http://localhost:%d" % port), {"prefs": {"a": "2"}})[0] == 403
    assert call(port, "POST", "/signout", dict(OWNER, Origin=ORIGIN), b"")[0] == 303
finally:
    proc.kill()
    proc.wait()

# -- open mode with the file and sign-in: the Host rule (DNS rebinding) comes first, before the sign-in routes too
proc, port, d, tokens, code = start(KANBAN_AUTH="open", KANBAN_SIGNIN="1")
try:
    EVIL = {"Host": "evil.example:%d" % port}
    assert call(port, "GET", "/signin", EVIL)[0] == 403
    assert call(port, "POST", "/signin", dict(EVIL, Origin="https://evil.example:%d" % port, **FORM),
                urlencode({"name": "owner", "password": OWNER_PW}).encode())[0] == 403
    assert call(port, "POST", "/api/pair", EVIL, {"code": code, "device": "x"})[0] == 403
    assert call(port, "GET", "/static/machiya.css", EVIL)[0] == 403
    assert call(port, "GET", "/signin")[0] == 200
    # open mode's owner rides along with any page: a prefs PUT still needs the same origin
    assert call(port, "PUT", "/api/prefs", None, {"prefs": {"a": "1"}})[0] == 403
    assert call(port, "PUT", "/api/prefs", {"Origin": "https://127.0.0.1:%d" % port}, {"prefs": {"a": "1"}})[0] == 200
finally:
    proc.kill()
    proc.wait()

# -- the file without KANBAN_SIGNIN: no sign-in page (the 401 stays plain text), but pairing and prefs work
proc, port, d, tokens, code = start()
try:
    assert call(port, "GET", "/signin")[0] == 404
    assert call(port, "POST", "/signin", dict(FORM, Origin="https://127.0.0.1:%d" % port),
                urlencode({"name": "owner", "password": OWNER_PW}).encode())[0] == 404
    assert call(port, "GET", "/")[2] == "no identity\n"
    assert call(port, "GET", "/static/machiya.css")[0] == 401           # nothing to style before the gate
    st, _, body = call(port, "POST", "/api/pair", None, {"code": code, "device": "iPhone"})
    assert st == 200, (st, body)
    assert call(port, "GET", "/api/prefs", {"Authorization": "Bearer " + tokens["mcp"]})[0] == 200
finally:
    proc.kill()
    proc.wait()

# -- no identity file: every new route is 404 behind the old gate, as before
proc, port, d, tokens, code = start(identity_file=False, KANBAN_AUTH="open")
try:
    for method, path, body in (("GET", "/signin", None), ("POST", "/signin", b"name=owner"), ("POST", "/signout", b""),
                               ("POST", "/api/pair", {"code": code, "device": "x"}), ("GET", "/api/prefs", None),
                               ("PUT", "/api/prefs", {"prefs": {"a": "1"}})):
        st = call(port, method, path, {"Origin": "http://127.0.0.1:%d" % port, "X-Agent": "t"}, body)[0]
        assert st == 404, (method, path, st)
    assert not os.path.exists(d + "/db/prefs.sqlite3")
finally:
    proc.kill()
    proc.wait()
proc, port, d, tokens, code = start(identity_file=False, KANBAN_TAILNET_USERS="owner@example")
try:
    assert call(port, "POST", "/api/pair", None, {"code": code, "device": "x"})[0] == 403      # the gate first
    assert call(port, "GET", "/signin")[0] == 403
    assert call(port, "GET", "/signin", {"Tailscale-User-Login": "owner@example"})[0] == 404
    assert call(port, "GET", "/api/prefs", {"Tailscale-User-Login": "owner@example"})[0] == 404
finally:
    proc.kill()
    proc.wait()
print("signin tests: all passed")
