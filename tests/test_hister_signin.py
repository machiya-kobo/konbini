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
ROOM_SID = "mhr_" + "R" * 43              # a room session of this board (vaultkit 0.22: the room's own host-only cookie)
OTHER_ROOM_SID = "mhr_" + "S" * 43        # one of another room's: refused here
RTOKEN = "mht_" + "T" * 43                # a room token (headless callers: pm, the MCP)
CODE = "mhc_" + "C" * 43                  # the one-time code on the way back from the helper
STATE = "n" * 43
checks, redeems = [], []                  # what the board asked the helper
ACCOUNT = {"theme": "night", "palette": "nord", "text_size": "large"}      # the account's Shared settings (the helper's)
prefs_calls = []


class Helper(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, obj, extra=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.send(200, {"ok": True})
        sid, tok = self.headers.get("X-Machiya-Session"), self.headers.get("X-Access-Token")
        if self.path == "/v1/prefs":
            prefs_calls.append(("GET", sid, tok, self.headers.get("If-None-Match"), None))
            if self.headers.get("If-None-Match") == '"3"':
                self.send_response(304); self.send_header("ETag", '"3"'); self.send_header("Content-Length", "0"); self.end_headers()
                return
            return self.send(200, {"v": 1, "rev": 3, "prefs": dict(ACCOUNT, **{"konbini.group": "family"}), "updated": {}}, {"ETag": '"3"'})
        if self.path == "/v1/check":
            checks.append((sid, tok, self.headers.get("X-Machiya-Room")))
        if sid in (ROOM_SID, RTOKEN):
            return self.send(200, {"username": "owner", "user_id": 1, "prefs": ACCOUNT, "room": BOARD})
        if sid == OTHER_ROOM_SID:
            return self.send(200, {"username": "owner", "user_id": 1, "prefs": ACCOUNT, "room": "https://kura.example.test"})
        if sid == OWNER_SID or tok == TOKEN:
            return self.send(200, {"username": "owner", "user_id": 1, "prefs": ACCOUNT})
        if sid == STRANGER_SID:
            return self.send(200, {"username": "stranger", "user_id": 2})
        self.send(401, {"error": "signed out"})

    def do_POST(self):
        if self.path == "/v1/redeem":
            redeems.append((self.headers.get("X-Machiya-Code"), self.headers.get("X-Machiya-Room"), self.headers.get("X-Machiya-State")))
            if self.headers.get("X-Machiya-Code") != CODE or self.headers.get("X-Machiya-State") != STATE:
                return self.send(401, {"error": "bad code"})
            return self.send(200, {"session": ROOM_SID, "username": "owner", "user_id": 1, "max_age": 3600, "return": BOARD + "/now"})
        signouts.append(self.headers.get("X-Machiya-Session"))
        self.send(200, {"ok": True})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        prefs_calls.append(("PUT", self.headers.get("X-Machiya-Session"), self.headers.get("X-Access-Token"), None, body))
        self.send(200, {"v": 1, "rev": 4, "prefs": dict(ACCOUNT, **body.get("prefs", {})), "updated": {}}, {"ETag": '"4"'})


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
                            stdout=subprocess.DEVNULL, stderr=open(d + "/server.log", "w"))      # a file: an unread pipe fills up and stalls the board
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            time.sleep(0.05)
    raise SystemExit("board did not start: " + open(d + "/server.log").read()[-500:])


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
    guard = [c for c in cookies(r) if c.startswith("__Host-machiya_sso_konbini_try=1")]
    assert guard, cookies(r)
    status, r, body = get(port, "/now", dict(HTML, Cookie="__Host-machiya_sso_konbini_try=1"))
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
    assert r.status == 201 and out["actor"] == "owner@example.com", (r.status, out)     # continuity: the tailnet login, not "owner"
    # sign-out: same-origin only; the helper ends the session, the cookie is cleared, the cache is cleared, and it goes to /
    before = len(signouts)
    status, r, _ = get(port, "/signout", dict(SID, Origin="https://evil.example"), "POST")
    assert status == 403 and len(signouts) == before, status
    status, r, _ = get(port, "/signout", dict(SID, Origin=BOARD), "POST")
    assert status == 303 and r.getheader("Location") == "/" and r.getheader("Clear-Site-Data") == '"cache"', status
    assert any(c.startswith("machiya_sso=;") and "Max-Age=0" in c for c in cookies(r)) and signouts[-1] == OWNER_SID, (cookies(r), signouts)
    assert get(port, "/api/cards", SID)[0] == 401                                                  # that session is over, here too
    assert get(port, "/signout", {"X-Access-Token": TOKEN})[0] == 404                              # a GET: nothing to see

    # preferences that follow the person (vaultkit 0.21): /api/prefs forwards to the helper with the caller's own credential;
    # a PUT carried by the cookie must be same-origin; the first render of a browser with no cookies uses the account's settings
    port = start()
    status, r, body = get(port, "/api/prefs", SID)
    data = json.loads(body)
    assert status == 200 and data["rev"] == 3 and data["prefs"]["konbini.group"] == "family" and r.getheader("ETag") == '"3"', (status, data)
    assert prefs_calls[-1][:3] == ("GET", OWNER_SID, None), prefs_calls[-1]                   # the cookie's id, never a user id
    assert get(port, "/api/prefs", dict(SID, **{"If-None-Match": '"3"'}))[0] == 304
    status, r, body = get(port, "/api/prefs", {"X-Access-Token": TOKEN})
    assert status == 200 and prefs_calls[-1][:3] == ("GET", None, TOKEN), prefs_calls[-1]   # a Hister token goes as the token
    assert get(port, "/api/prefs")[0] == 401                                                  # signed out
    put = json.dumps({"prefs": {"konbini.done_cards": "10"}})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("PUT", "/api/prefs", body=put, headers=dict(SID, **{"Content-Type": "application/json", "Origin": "https://evil.example"}))
    assert c.getresponse().status == 403 and prefs_calls[-1][0] != "PUT"                       # another site's page: refused
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("PUT", "/api/prefs", body=put, headers=dict(SID, **{"Content-Type": "application/json", "Origin": BOARD}))
    r = c.getresponse(); out = json.loads(r.read())
    assert r.status == 200 and out["rev"] == 4 and prefs_calls[-1][0] == "PUT" and prefs_calls[-1][4] == {"prefs": {"konbini.done_cards": "10"}}, (r.status, out)
    # first render: no theme cookie at all, yet the page is drawn in the account's theme, palette and size
    status, r, body = get(port, "/now", dict(HTML, **SID))
    page_html = body.decode()
    assert 'class="theme-night palette-nord' in page_html and 'data-text="large"' in page_html, page_html[page_html.index("<body"):][:200]
    # the own settings that follow the person are declared for machiya.js (account keys konbini.group, konbini.done_cards)
    assert 'name="machiya-app-prefs"' in page_html and "konbini.done_cards" in page_html and "konbini.group" in page_html and "konbini.card_style" in page_html
    # /settings (vaultkit 0.23's order): Appearance (kept in the account), the board's own (with Offline Copies, this
    # device's only row), Account, About; no This Device section
    status, r, body = get(port, "/settings", dict(HTML, **SID))
    html = body.decode()
    order = [html.index(h) for h in ('id="appearance"', 'id="board"', "data-clear-offline", 'id="account"', 'id="about"')]
    assert status == 200 and order == sorted(order), order
    assert 'data-prefs-state="account"' in html and "Saved to your account." in html and ">owner<" in html
    assert "follow you to your other devices when signed in" in html and "Offline Copies stay on this device" in html
    assert "Use This Device" in html and 'id="this-device"' not in html and 'id="shared"' not in html and 'id="apps"' not in html

    # vaultkit 0.22: each room has its own host-only cookie holding a room session; a trip to the helper comes back with a one-time
    # code that /machiya/callback trades (once, for this room, with this browser's nonce) for it
    port = start(KANBAN_AUTH_ACCEPT_ORIGINS="https://shiori.example.test")
    ROOM = {"Cookie": "__Host-machiya_sso_konbini=" + ROOM_SID}
    status, r, body = get(port, "/now", dict(HTML, **ROOM))
    assert status == 200 and checks[-1][0] == ROOM_SID, status
    assert checks[-1][2] == BOARD + ", https://shiori.example.test", checks[-1]       # every check names the room (and the origins it accepts)
    assert get(port, "/api/cards", {"Cookie": "__Host-machiya_sso_konbini=" + OTHER_ROOM_SID})[0] == 401   # another room's session: refused
    assert get(port, "/api/cards", {"Authorization": "Bearer " + RTOKEN})[0] == 200                       # a room token: a headless caller
    assert checks[-1][0] == RTOKEN
    # a page without any cookie goes to the helper with a state (the nonce's hash), the nonce staying in this room's own cookie
    status, r, _ = get(port, "/now", HTML)
    loc = r.getheader("Location")
    assert status == 302 and "state=" in loc and any(c.startswith("__Host-machiya_sso_konbini_state=") for c in cookies(r)), (loc, cookies(r))
    assert all("Domain=" not in c for c in cookies(r)), cookies(r)                   # host-only
    # the way back: the code is traded once, here, with the nonce from the state cookie; the room cookie is set; back to the page
    status, r, _ = get(port, "/machiya/callback?code=" + CODE, dict(HTML, Cookie="__Host-machiya_sso_konbini_state=" + STATE))
    assert status == 302 and r.getheader("Location") == BOARD + "/now", (status, r.getheader("Location"))
    assert redeems[-1] == (CODE, BOARD, STATE), redeems
    room_cookie = [c for c in cookies(r) if c.startswith("__Host-machiya_sso_konbini=mhr_")]
    assert room_cookie and "Secure" in room_cookie[0] and "Domain=" not in room_cookie[0] and "HttpOnly" in room_cookie[0], cookies(r)
    # a wrong code (or one without this browser's nonce) shows the sign-in page, never a loop and never a session
    status, r, body = get(port, "/machiya/callback?code=" + "mhc_" + "X" * 43, dict(HTML, Cookie="__Host-machiya_sso_konbini_state=" + STATE))
    assert status == 401 and not any(c.startswith("__Host-machiya_sso_konbini=mhr_") for c in cookies(r)), status
    status, r, body = get(port, "/machiya/callback?code=" + CODE, HTML)               # no nonce cookie
    assert status == 401, status
    # sign-out marks the deliberate sign-out and clears the room's cookies
    status, r, _ = get(port, "/signout", dict(ROOM, Origin=BOARD), "POST")
    assert status == 303 and any(c.startswith("__Host-machiya_sso_konbini=;") and "Max-Age=0" in c for c in cookies(r)), cookies(r)

    # the helper is unreachable: the owner's tailnet login is admitted with the banner; nobody else is
    port = start(KANBAN_AUTH_URL=DOWN)
    status, r, body = get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "owner@example.com"}))
    assert status == 200 and b"machiya-banner" in body and b"sign-in is unavailable" in body, status
    assert get(port, "/api/cards", {"Tailscale-User-Login": "owner@example.com"})[0] == 200
    assert get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "intruder@example.com"}))[0] == 403
    assert get(port, "/api/prefs", {"Tailscale-User-Login": "owner@example.com"})[0] == 503   # no account while sign-in is down
    status, r, body = get(port, "/settings", dict(HTML, **{"Tailscale-User-Login": "owner@example.com"}))
    assert status == 200 and b'data-prefs-state="unavailable"' in body
    assert get(port, "/now", HTML)[0] == 503                                                    # no login at all
    assert get(port, "/api/health")[0] == 200 and get(port, "/api/changelog")[0] == 200         # the probes still answer
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)                                # a write through the fallback
    c.request("POST", "/api/cards/kura/events", body=json.dumps({"body": "hi"}), headers={
        "Content-Type": "application/json", "X-Agent": "test", "Tailscale-User-Login": "owner@example.com"})
    r = c.getresponse(); out = json.loads(r.read())
    assert r.status == 201 and out["actor"] == "owner@example.com", (r.status, out)
    # with no fallback (Kura's setting) an unreachable helper is 503 for everyone
    port = start(KANBAN_AUTH_URL=DOWN, KANBAN_AUTH_FALLBACK="none")
    assert get(port, "/now", dict(HTML, **{"Tailscale-User-Login": "owner@example.com"}))[0] == 503

    # with two tailnet logins there is no single owner to keep: the Hister username is the actor
    port = start(KANBAN_TAILNET_USERS="owner@example.com,other@example.com")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/api/cards/kura/events", body=json.dumps({"body": "hi"}), headers={
        "Content-Type": "application/json", "X-Agent": "test", "X-Access-Token": TOKEN})
    r = c.getresponse(); out = json.loads(r.read())
    assert r.status == 201 and out["actor"] == "owner", (r.status, out)

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
