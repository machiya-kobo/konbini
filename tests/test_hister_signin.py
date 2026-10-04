"""KANBAN_AUTH=hister (vaultkit.histerauth): the board asks the hister-login helper who is calling. A fake helper answers
/v1/check, /healthz and /v1/signout; each board runs in its own process (settings are read at import) on 127.0.0.1.
Mirrors the design's gate 0: a signed-out page goes to the helper once (the loop guard), an API call gets 401 JSON with
the sign-in address, a Hister token or a session id signs in, a bad one is 401 and never passed over, a Hister user
outside KANBAN_HISTER_USERS is 403, signed out never falls back to the tailnet but an unreachable helper does (with the
banner; without a listed login it is 503), the probes (/api/health, /api/changelog) answer without a sign-in, sign-out
is same-origin and ends the session, writes keep the CSRF rules, and the start-up refusals. Default modes are untouched
(test_auth)."""
import http.client, http.server, json, os, socket, subprocess, sys, tempfile, textwrap, threading, time
from urllib.parse import parse_qs, urlsplit

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
BOARD = "https://board.example.test"
SIGNIN = "https://hister.example.test/machiya/signin"
OWNER_SID = "mhs_" + "A" * 43
STRANGER_SID = "mhs_" + "B" * 43
DEAD_SID = "mhs_" + "C" * 43
TOKEN = "owner-hister-token-123"
signouts = []


class Helper(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.send(200, {"ok": True})
        sid, tok = self.headers.get("X-Machiya-Session"), self.headers.get("X-Access-Token")
        if sid == OWNER_SID or tok == TOKEN:
            return self.send(200, {"username": "owner", "user_id": 1})
        if sid == STRANGER_SID:
            return self.send(200, {"username": "stranger", "user_id": 2})
        self.send(401, {"error": "signed out"})

    def do_POST(self):
        signouts.append(self.headers.get("X-Machiya-Session"))
        self.send(200, {"ok": True})


helper = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Helper)
threading.Thread(target=helper.serve_forever, daemon=True).start()
HELPER = "http://127.0.0.1:%d" % helper.server_address[1]
DOWN = "http://127.0.0.1:%d" % socket.create_server(("127.0.0.1", 0)).getsockname()[1]      # nothing answers there (a closed port)
NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\nproject: kura\nstatus: wip\n---\n# Kura\n")
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
procs = []


def env_for(d, port, **extra):
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port), KANBAN_BIND="127.0.0.1",
               PYTHONDONTWRITEBYTECODE="1", KANBAN_AUTH="hister", KANBAN_AUTH_URL=HELPER, KANBAN_AUTH_SIGNIN_URL=SIGNIN,
               KANBAN_HISTER_USERS="owner", KANBAN_BOARD_URL=BOARD, KANBAN_TAILNET_USERS="owner@example.com")
    for k in ("MACHIYA_IDENTITY_FILE", "KANBAN_AUTH_FALLBACK", "MACHIYA_COOKIE_DOMAIN", "KANBAN_BIND_BEHIND_PROXY"):
        env.pop(k, None)
    env.update({k: v for k, v in extra.items() if v is not None})
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
    return env


def vault():
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    return d


def start(**extra):
    d = vault()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env_for(d, port, **extra),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            time.sleep(0.05)
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


def refused(**extra):
    """The start-up message when the board refuses to start with these settings."""
    d = vault()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    open(d + "/server.py", "w").write(SERVER)
    r = subprocess.run([sys.executable, d + "/server.py", APP, str(port)], env=env_for(d, port, **extra),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "the board started"
    return r.stderr


def get(port, path, headers=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    out = (r.status, r, body)
    c.close()
    return out


def cookies(resp):
    return [v for k, v in resp.getheaders() if k.lower() == "set-cookie"]


HTML = {"Accept": "text/html"}
SID = {"Cookie": "machiya_sso=" + OWNER_SID}
try:
    port = start()
    # a signed-out page goes to the helper with return= this page, once; the second try shows a page with a link (no loop)
    status, r, _ = get(port, "/now?x=1", HTML)
    loc = r.getheader("Location")
    assert status == 302 and loc.startswith(SIGNIN + "?"), (status, loc)
    assert parse_qs(urlsplit(loc).query)["return"] == [BOARD + "/now?x=1"], loc
    guard = [c for c in cookies(r) if c.startswith("machiya_sso_try=1")]
    assert guard, cookies(r)
    status, r, body = get(port, "/now", dict(HTML, Cookie="machiya_sso_try=1"))
    assert status == 401 and b"Sign In" in body and SIGNIN.encode() in body and r.getheader("Location") is None, status
    # an API call (or any fetch) is never redirected: 401 JSON with the sign-in address
    status, r, body = get(port, "/api/cards")
    data = json.loads(body)
    assert status == 401 and data["error"] == "sign in" and data["signin"].startswith(SIGNIN), (status, data)
    assert get(port, "/api/cards", {"Accept": "*/*", "X-Machiya-Live": "1"})[0] == 401      # the live search's fetch
    # a Hister sign-in (the shared cookie) opens pages and the API; the page opts in to machiya.js's sign-in handling
    status, r, body = get(port, "/now", dict(HTML, **SID))
    assert status == 200 and b'name="machiya-signin" content="/signout"' in body and b"machiya-banner" not in body, status
    status, r, body = get(port, "/api/cards", SID)
    assert status == 200 and b'"kura"' in body, (status, body[:80])
    # the owner's Hister token: X-Access-Token or Bearer; a present but invalid one is 401 and never passed over
    assert get(port, "/api/cards", {"X-Access-Token": TOKEN})[0] == 200
    assert get(port, "/api/cards", {"Authorization": "Bearer " + TOKEN})[0] == 200
    assert get(port, "/api/cards", dict(SID, **{"X-Access-Token": "wrong"}))[0] == 401           # the cookie isn't tried
    assert get(port, "/api/cards", dict(SID, **{"Authorization": "Bearer mch_not_a_hister_token_x"}))[0] == 401
    # a signed-in Hister user the board doesn't admit: 403 (never a fallback, never a redirect)
    status, r, body = get(port, "/now", dict(HTML, Cookie="machiya_sso=" + STRANGER_SID,
                                              **{"Tailscale-User-Login": "owner@example.com"}))
    assert status == 403 and r.getheader("Location") is None, status
    assert get(port, "/api/cards", {"Cookie": "machiya_sso=" + STRANGER_SID})[0] == 403
    # a dead session: 401 with the cookie cleared; signed out never falls back to the tailnet login
    status, r, _ = get(port, "/now", dict(HTML, Cookie="machiya_sso=" + DEAD_SID, **{"Tailscale-User-Login": "owner@example.com"}))
    assert status == 302 and any(c.startswith("machiya_sso=;") and "Max-Age=0" in c for c in cookies(r)), cookies(r)
    assert get(port, "/api/cards", {"Tailscale-User-Login": "owner@example.com"})[0] == 401
    # the probes answer without a sign-in: health with what a probe needs, the owner with everything; the changelog is open
    status, r, body = get(port, "/api/health")
    health = json.loads(body)
    assert status == 200 and health["ok"] and health["auth"] == "hister" and health["vaultkit"].startswith("v0.") \
        and "sync" not in health and "hister" not in health, health
    assert "sync" in json.loads(get(port, "/api/health", SID)[2])
    assert get(port, "/api/status")[0] == 200
    status, r, body = get(port, "/api/changelog")
    assert status == 200 and r.getheader("Content-Type").startswith("text/markdown"), status
    assert get(port, "/healthz")[0] == 200
    # writes keep the board's CSRF rules: a cookie with a cross-site Origin, or without X-Agent, is refused; Bearer + X-Agent works
    w = {"Content-Type": "application/json"}
    assert get(port, "/api/cards/kura/events", dict(w, **SID, **{"Origin": "https://evil.example", "X-Agent": "x"}), "POST")[0] in (403, 401)
    assert get(port, "/api/cards/kura/events", dict(w, **SID), "POST")[0] == 403                   # no X-Agent, no Origin
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/api/cards/kura/events", body=json.dumps({"body": "hello"}), headers=dict(w, **{
        "Authorization": "Bearer " + TOKEN, "X-Agent": "test"}))
    r = c.getresponse(); out = json.loads(r.read())
    assert r.status == 201 and out["actor"] == "owner", (r.status, out)                              # the Hister user is the actor
    # sign-out: same-origin only; the helper ends the session, the cookie is cleared, the cache is cleared, and it goes to /
    before = len(signouts)
    status, r, _ = get(port, "/signout", dict(SID, Origin="https://evil.example"), "POST")
    assert status == 403 and len(signouts) == before, status
    status, r, _ = get(port, "/signout", dict(SID, Origin=BOARD), "POST")
    assert status == 303 and r.getheader("Location") == "/" and r.getheader("Clear-Site-Data") == '"cache"', status
    assert any(c.startswith("machiya_sso=;") and "Max-Age=0" in c for c in cookies(r)) and signouts[-1] == OWNER_SID, (cookies(r), signouts)
    assert get(port, "/api/cards", SID)[0] == 401                                                  # that session is over, here too
    assert get(port, "/signout", {"X-Access-Token": TOKEN})[0] == 404                              # a GET: nothing to see

    # the helper is unreachable: the owner's tailnet login is admitted with the banner; nobody else is
    port = start(KANBAN_AUTH_URL=DOWN)
    status, r, body = get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "owner@example.com"}))
    assert status == 200 and b"machiya-banner" in body and b"sign-in is unavailable" in body, status
    assert get(port, "/api/cards", {"Tailscale-User-Login": "owner@example.com"})[0] == 200
    assert get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "intruder@example.com"}))[0] == 403
    assert get(port, "/now", HTML)[0] == 503                                                    # no login at all
    assert get(port, "/api/health")[0] == 200 and get(port, "/api/changelog")[0] == 200         # the probes still answer
    # with no fallback (Kura's setting) an unreachable helper is 503 for everyone
    port = start(KANBAN_AUTH_URL=DOWN, KANBAN_AUTH_FALLBACK="none")
    assert get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "owner@example.com"}))[0] == 503

    # start-up refusals: no usernames, a *, no board address, an identity file too
    assert "KANBAN_HISTER_USERS" in refused(KANBAN_HISTER_USERS=None)
    assert "'*' is refused" in refused(KANBAN_HISTER_USERS="*")
    assert "KANBAN_BOARD_URL" in refused(KANBAN_BOARD_URL=None)
    assert "KANBAN_AUTH_SIGNIN_URL" in refused(KANBAN_AUTH_SIGNIN_URL=None)
    assert "identity file" in refused(MACHIYA_IDENTITY_FILE="/nonexistent/identity.toml")
finally:
    for p in procs:
        p.kill()
print("hister signin tests: all passed")
