"""Machiya's identity file (MACHIYA_IDENTITY_FILE, vaultkit.identity): who may read the board (konbini `read`), change
it (`write`) and add area/* lanes and new tags (`areas`, the owner's power that `agent == "web"` stood for). No proof or
a bad one is 401 and never falls through to another proof; a missing grant is 403. Each mode runs in its own process
(the settings are read at import) on 127.0.0.1, serving a throwaway vault; the file is written with vaultkit's own
helpers. Without the file nothing changes: tests/test_auth.py keeps covering that."""
import glob, json, os, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from vaultkit import identity  # noqa: E402

NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\n"
        "  - topic/search\nproject: kura\nstatus: wip\n---\n# Kura\n")
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
START = "import sys; sys.path.insert(0, sys.argv[1]); import app; print(app.AUTH, app.IDENTITY.auth, app.IDENTITY.room)"


def write_identity(folder):
    """The owner, an agent (read + write), a person who may only read, a person granted nothing, Niwa as a service
    (read) and a proxy user for header mode. -> {name: token}."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "session.key"), "w") as f:
        f.write("k" * 43)
    data = {"version": 1, "session_key_file": "session.key", "principals": {
        "owner": {"id": "ownerid000000001", "kind": "person", "owner": True, "tailscale": ["owner@example"],
                  "proxy": ["owner"]},
        "mcp": {"kind": "agent", "grants": {"konbini": ["read", "write"]}},
        "reader": {"id": "readerid00000001", "kind": "person", "tailscale": ["reader@example"],
                   "grants": {"konbini": ["read"]}},
        "nobody": {"id": "nobodyid00000001", "kind": "person", "tailscale": ["nobody@example"]},
        "niwa": {"kind": "service", "grants": {"konbini": ["read"], "niwa": ["read"]}}}}
    tokens = {n: identity.new_token(data, n, "test") for n in ("mcp", "niwa")}
    path = os.path.join(folder, "identity.toml")
    identity.write_file(path, data)
    return path, tokens


def setup(**extra):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/vault/Projects")
    open(d + "/vault/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    path, tokens = write_identity(d + "/identity")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_TAILNET_USERS="", MACHIYA_IDENTITY_FILE=path,
               PYTHONDONTWRITEBYTECODE="1")
    for k in ("KANBAN_AUTH", "KANBAN_AUTH_HEADER", "KANBAN_SIGNIN", "KANBAN_BIND_BEHIND_PROXY", "KANBAN_BOARD_URL"):
        env.pop(k, None)
    env.update(extra)
    return d, port, env, tokens


def start(**extra):
    d, port, env, tokens = setup(**extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=open(d + "/server.log", "w"))      # a file: an unread pipe fills up and stalls the board
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, port, d, tokens
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("board did not start: " + open(d + "/server.log").read()[-500:])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(port, method, path, headers=None, body=None):
    """-> (status, headers, body text)."""
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        headers = dict(headers or {}, **{"Content-Type": "application/json"})
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def events(d):
    out = []
    for name in sorted(glob.glob(d + "/vault/.board/events/*.jsonl")):
        out += [json.loads(line) for line in open(name, encoding="utf-8") if line.strip()]
    return out


def front(d):
    return open(d + "/vault/Projects/Kura.md", encoding="utf-8").read().split("---")[1]


def allnotes(d):
    return "".join(open(os.path.join(d, "vault", "Projects", n), encoding="utf-8").read()
                   for n in sorted(os.listdir(d + "/vault/Projects")) if n.endswith(".md"))


OWNER = {"Tailscale-User-Login": "owner@example"}
READER = {"Tailscale-User-Login": "reader@example"}
API = {"X-Agent": "test"}           # the /api write rule: a caller that isn't the board's page names itself

# -- tailscale mode (the default) with the file
proc, port, d, tokens = start()
try:
    MCP = {"Authorization": "Bearer " + tokens["mcp"]}
    NIWA = {"Authorization": "Bearer " + tokens["niwa"]}
    same = {"Origin": "http://127.0.0.1:%d" % port, "Host": "127.0.0.1:%d" % port}
    form = dict(same, **{"Content-Type": "application/x-www-form-urlencoded"})

    # who gets in
    assert call(port, "GET", "/", OWNER)[0] == 200
    assert call(port, "GET", "/api/cards", MCP)[0] == 200
    assert call(port, "GET", "/", READER)[0] == 200
    st, h, body = call(port, "GET", "/")
    assert (st, body) == (401, "no identity\n"), (st, body)                          # no proof at all
    assert h["Cache-Control"] == "no-store", dict(h)
    st, h, body = call(port, "GET", "/api/cards")
    assert (st, json.loads(body)) == (401, {"error": "no identity"}), (st, body)     # JSON for the API
    st, _, body = call(port, "GET", "/", {"Tailscale-User-Login": "stranger@example"})
    assert (st, body) == (403, "this login has no access\n"), (st, body)
    st, _, body = call(port, "GET", "/api/cards", {"Tailscale-User-Login": "nobody@example"})   # in the file, no grant
    assert (st, json.loads(body)["error"]) == (403, "not allowed in konbini"), (st, body)
    assert call(port, "GET", "/", {"Authorization": "Bearer mch_zzzzzz_nope"})[0] == 401
    # a bad token never falls through to a valid login
    assert call(port, "GET", "/", dict(OWNER, Authorization="Bearer mch_zzzzzz_nope"))[0] == 401
    assert call(port, "PATCH", "/api/cards/kura", dict(OWNER, Authorization="Bearer nope", **API), {"next": "x"})[0] == 401
    assert call(port, "GET", "/", {"Authorization": "Basic b3duZXI6eA=="})[0] == 401
    # /healthz stays open; /api/status and /api/health need read
    assert call(port, "GET", "/healthz")[:3:2] == (200, "ok\n")
    assert call(port, "GET", "/api/status")[0] == 401 and call(port, "GET", "/api/health")[0] == 401
    st, _, body = call(port, "GET", "/api/status", NIWA)
    assert st == 200 and json.loads(body)["auth"] == "tailscale", (st, body)
    assert sorted(json.loads(body)) == ["auth", "cards", "error", "head", "ok", "vaultkit", "version"], body   # no hister, no sync
    assert "hister" in json.loads(call(port, "GET", "/api/status", OWNER)[2])                     # the owner: in full

    # Niwa: a service token with konbini read reads the cards and the digest, and writes nothing
    assert call(port, "GET", "/api/digest?days=7", NIWA)[0] == 200
    assert json.loads(call(port, "GET", "/api/cards", NIWA)[2])["cards"][0]["slug"] == "kura"
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(NIWA, **API), {"next": "from niwa"})
    assert st == 403 and "write grant" in json.loads(body)["error"], (st, body)

    # a person who may only read: every write is 403
    assert call(port, "PATCH", "/api/cards/kura", dict(READER, **API), {"next": "reader"})[0] == 403
    assert call(port, "POST", "/api/cards/kura/events", dict(READER, **API), {"body": "hi"})[0] == 403
    assert call(port, "POST", "/api/cards/kura/claim", dict(READER, **API), {"minutes": 5})[0] == 403
    assert call(port, "POST", "/p/kura", dict(READER, **form), b"next=reader")[0] == 403
    assert call(port, "POST", "/api/cards", dict(READER, **API), {"title": "Nope", "area": "tools"})[0] == 403
    assert "reader" not in front(d)

    # an agent with read + write: edits, comments and claims, under its own name; X-Agent is only a label
    assert call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"next": "agent edit"})[0] == 200
    assert call(port, "POST", "/api/cards/kura/events", dict(MCP, **API), {"body": "a comment"})[0] == 201
    st, _, body = call(port, "POST", "/api/cards/kura/claim", dict(MCP, **API), {"minutes": 5})
    assert st == 200 and json.loads(body)["claimed_by"] == "test", (st, body)
    assert call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/search"]})[0] == 200  # known
    # ... but no new area/* lane and no new tag, confirmed or not, whatever headers it sends
    st, _, body = call(port, "POST", "/api/cards", dict(MCP, **API), {"title": "Lane", "area": "brandnew"})
    assert st == 403 and json.loads(body)["tags"] == ["area/brandnew"], (st, body)
    for confirm in (False, True):
        st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API),
                           {"tags_add": ["topic/novel"], "confirm_new_tags": confirm})
        assert st == 403 and "areas grant" in json.loads(body)["error"], (confirm, st, body)
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **same), {"tags_add": ["area/sneaky"]})
    assert st == 403, (st, body)            # same-origin and no X-Agent ("web") used to be the owner's power
    assert "area/brandnew" not in front(d) and "topic/novel" not in front(d) and "area/sneaky" not in front(d)
    # new_topics: the one new tag an agent that can only write may create, named by the caller (the owner said yes)
    def made():
        return [(e["card"], e["tag"], e["actor"], e["agent"]) for e in events(d) if e["type"] == "topic_created"]
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/newsblur"], "new_topics": ["newsblur"]})
    assert st == 200 and "topic/newsblur" in front(d), (st, body)
    assert made() == [("kura", "topic/newsblur", "mcp", "test")], made()
    # it exists now, so naming it again changes nothing and logs nothing
    assert call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/newsblur"], "new_topics": ["newsblur"]})[0] == 200
    assert len(made()) == 1, made()
    # a topic the caller didn't name stays refused, and so does anything else in the same write
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/other"], "new_topics": ["newsblur"]})
    assert st == 403 and json.loads(body)["tags"] == ["topic/other"], (st, body)
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/one", "topic/two"], "new_topics": ["one"]})
    assert st == 403 and "topic/one" not in front(d) and len(made()) == 1, (st, body)
    # a name the card doesn't use creates nothing
    st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"next": "unused", "new_topics": ["unused"]})
    assert st == 200 and "topic/unused" not in front(d) and len(made()) == 1, (st, body)
    # a new card works the same way (topics + new_topics), one event for its card
    st, _, body = call(port, "POST", "/api/cards", dict(MCP, **API),
                       {"title": "Topic card", "area": "tools", "topics": ["freshtopic"], "new_topics": ["freshtopic"]})
    assert st == 201 and "topic/freshtopic" in allnotes(d), (st, body)
    assert made()[-1][1:] == ("topic/freshtopic", "mcp", "test") and len(made()) == 2, made()
    # an area is never made this way: no card, no topic, no lane
    st, _, body = call(port, "POST", "/api/cards", dict(MCP, **API),
                       {"title": "Lane two", "area": "brandnew2", "topics": ["freshlane"], "new_topics": ["freshlane"]})
    assert st == 403 and json.loads(body)["tags"] == ["area/brandnew2"], (st, body)
    assert "brandnew2" not in allnotes(d) and "topic/freshlane" not in allnotes(d) and len(made()) == 2
    # the names are plain topic names: a prefix is fine, a lane or odd spelling is not
    for bad in (["area/x"], ["Bad Name"], ["x" * 41], "newsblur", [1]):
        st, _, body = call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/zzz"], "new_topics": bad})
        assert st == 422, (bad, st, body)
    assert call(port, "PATCH", "/api/cards/kura", dict(MCP, **API), {"tags_add": ["topic/prefixed"], "new_topics": ["topic/prefixed"]})[0] == 200
    assert len(made()) == 3 and "topic/zzz" not in front(d)
    # a reader still can't write at all
    assert call(port, "PATCH", "/api/cards/kura", dict(READER, **API), {"tags_add": ["topic/rd"], "new_topics": ["rd"]})[0] == 403
    # an agent can still create a card in an existing lane
    st, _, body = call(port, "POST", "/api/cards", dict(MCP, **API), {"title": "Agent card", "area": "tools"})
    assert st == 201, (st, body)
    acts = {(e["type"], e["actor"], e["agent"]) for e in events(d) if e["actor"] == "mcp"}
    assert {"comment", "create"} <= {a[0] for a in acts} and all(a[2] == "test" for a in acts), acts

    # the owner: every power, from the API and from the board's own pages
    st, _, body = call(port, "POST", "/api/cards", dict(OWNER, **API), {"title": "Owner lane", "area": "garden", "confirm_new_tags": True})
    assert st == 201, (st, body)
    assert call(port, "PATCH", "/api/cards/kura", dict(OWNER, **API),
                {"tags_add": ["topic/novel"], "confirm_new_tags": True})[0] == 200
    assert call(port, "POST", "/p/kura/tags", dict(OWNER, **form), b"add=topic%2Ffresh&confirm=1")[0] == 302
    assert call(port, "POST", "/p/kura", dict(OWNER, **form), b"next=owner+form")[0] == 302
    assert "topic/novel" in front(d) and "topic/fresh" in front(d) and "owner form" in front(d)
    assert {e["actor"] for e in events(d)} == {"mcp", "owner"}, {e["actor"] for e in events(d)}

    # the CSRF rules stay: another site's page riding the owner's login, a form post from elsewhere
    assert call(port, "PATCH", "/api/cards/kura", dict(OWNER, Origin="https://evil.example", **API), {"next": "csrf"})[0] == 403
    assert call(port, "PATCH", "/api/cards/kura", OWNER, {"next": "csrf"})[0] == 403          # names no caller
    assert call(port, "POST", "/p/kura", dict(OWNER, **{"Content-Type": "application/x-www-form-urlencoded"}),
                b"next=csrf")[0] == 403
    assert "csrf" not in front(d)
finally:
    proc.kill()
    proc.wait()

# -- sessions (built-in sign-in on): a renewed or cleared session cookie is sent with the answer
proc, port, d, tokens = start(KANBAN_SIGNIN="1")
try:
    config, key = identity.read_file(d + "/identity/identity.toml")
    t = int(time.time())
    old = identity.sign(key, "session", {"p": "owner", "u": "ownerid000000001", "e": 1, "iat": t - 2 * 86400,
                                         "auth": t - 2 * 86400, "exp": t + 86400})
    st, h, _ = call(port, "GET", "/", {"Cookie": "machiya_session=" + old})
    assert st == 200 and (h["Set-Cookie"] or "").startswith("machiya_session=") and "Max-Age=0" not in h["Set-Cookie"], dict(h)
    st, h, _ = call(port, "GET", "/api/rev", {"Cookie": "machiya_session=" + old})
    assert st == 200 and h["Set-Cookie"], dict(h)
    st, h, _ = call(port, "GET", "/", {"Cookie": "machiya_session=forged.value"})
    assert st == 401 and "Max-Age=0" in h["Set-Cookie"], (st, dict(h))                # a bad session is cleared
    fresh = identity.sign(key, "session", {"p": "owner", "u": "ownerid000000001", "e": 1, "iat": t, "auth": t,
                                           "exp": t + 86400})
    st, h, _ = call(port, "GET", "/", {"Cookie": "machiya_session=" + fresh})
    assert st == 200 and h["Set-Cookie"] is None, dict(h)                             # nothing to renew yet
finally:
    proc.kill()
    proc.wait()

# -- header mode: a trusted proxy's login header names the principal
proc, port, d, tokens = start(KANBAN_AUTH="header", KANBAN_AUTH_HEADER="Remote-User")
try:
    assert call(port, "GET", "/", {"Remote-User": "owner"})[0] == 200
    assert call(port, "GET", "/", {"Remote-User": "someone"})[0] == 403
    assert call(port, "GET", "/", OWNER)[0] == 401              # Tailscale's header means nothing here
    assert call(port, "GET", "/api/cards", {"Authorization": "Bearer " + tokens["niwa"]})[0] == 200
finally:
    proc.kill()
    proc.wait()

# -- open mode with the file: no proof is the owner (the Host allow-list stays), a token is still its holder
proc, port, d, tokens = start(KANBAN_AUTH="open")
try:
    assert call(port, "GET", "/")[0] == 200
    assert call(port, "GET", "/", {"Host": "evil.example:%d" % port})[0] == 403               # DNS rebinding
    assert call(port, "POST", "/api/cards", API, {"title": "Open lane", "area": "opened", "confirm_new_tags": True})[0] == 201
    MCP = {"Authorization": "Bearer " + tokens["mcp"]}
    assert call(port, "POST", "/api/cards", dict(MCP, **API), {"title": "Agent lane", "area": "agented"})[0] == 403
    assert call(port, "GET", "/", {"Authorization": "Bearer mch_zzzzzz_nope"})[0] == 401
    assert {e["actor"] for e in events(d)} == {"local"}, events(d)
finally:
    proc.kill()
    proc.wait()


# -- start-up: header mode needs the file; a header mode on a public bind needs KANBAN_BIND_BEHIND_PROXY=1
def boot(**extra):
    d, port, env, _ = setup(**extra)
    return subprocess.run([sys.executable, "-c", START, APP], env=env, capture_output=True, text=True, timeout=60)


r = boot(KANBAN_AUTH="header", KANBAN_AUTH_HEADER="Remote-User", MACHIYA_IDENTITY_FILE="")
assert r.returncode != 0 and "KANBAN_AUTH must be tailscale or open or hister, not 'header'" in r.stderr, r.stderr[-300:]
r = boot(KANBAN_AUTH="header")
assert r.returncode != 0 and "konbini: identity: auth=header needs" in r.stderr, r.stderr[-300:]
r = boot(KANBAN_BIND="0.0.0.0")
assert r.returncode != 0 and "konbini: identity:" in r.stderr and "127.0.0.1" in r.stderr, r.stderr[-300:]
r = boot(KANBAN_BIND="0.0.0.0", KANBAN_BIND_BEHIND_PROXY="1")        # a header mode also names the peers that may send it
assert r.returncode != 0 and "KANBAN_TRUSTED_PROXIES" in r.stderr, r.stderr[-300:]
r = boot(KANBAN_BIND="0.0.0.0", KANBAN_BIND_BEHIND_PROXY="1", KANBAN_TRUSTED_PROXIES="10.210.4.2/32")
assert (r.returncode, r.stdout.strip()) == (0, "tailscale tailscale konbini"), (r.stdout, r.stderr[-300:])
r = boot(KANBAN_AUTH="open", KANBAN_BIND="0.0.0.0")                 # open trusts no header: no bind check
assert r.returncode == 0, r.stderr[-300:]
r = boot(MACHIYA_IDENTITY_FILE="/nonexistent/identity.toml")
assert r.returncode != 0 and "konbini: identity: identity file" in r.stderr, r.stderr[-300:]
print("identity tests: all passed")
