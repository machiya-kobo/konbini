"""KANBAN_AUTH / KANBAN_BIND: each mode runs in its own process (the settings are read at import), serving a
throwaway vault on 127.0.0.1."""
import json, os, socket, subprocess, sys, tempfile, textwrap

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\n"
        "project: kura\nstatus: wip\n---\n# Kura\n")
HARNESS = textwrap.dedent('''
    import json, sys, threading, time, urllib.request, urllib.error
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    port = int(sys.argv[2])
    threading.Thread(target=app.serve, args=(port, "tailnet"), daemon=True).start()
    time.sleep(0.5)
    out = {"bind": app.BIND, "auth": app.AUTH, "banner": app.auth_banner()}
    def call(name, method, path, headers=None, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method, headers=headers or {})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        try:
            out[name] = urllib.request.build_opener(NoRedirect).open(req, timeout=10).status
        except urllib.error.HTTPError as e:
            out[name] = e.code
    owner = {"Tailscale-User-Login": "owner@example"}
    call("patch_none", "PATCH", "/api/cards/kura", {"Content-Type": "application/json", "X-Agent": "t"},
         json.dumps({"next": "no header"}).encode())
    call("get_none", "GET", "/")
    # /healthz: open in every mode, no header, no data
    out["healthz"] = [urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=10).status,
                      urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=10).read().decode()]
    call("healthz_head", "HEAD", "/healthz")
    call("status_none", "GET", "/api/status")
    try:
        out["health_auth"] = json.load(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:%d/api/health" % port, headers=owner), timeout=10)).get("auth")
    except Exception as e:
        out["health_auth"] = repr(e)
    out["legacy_names"] = json.load(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:%d/api/status" % port, headers=owner), timeout=10)).get("legacy_names")
    out["version"] = json.load(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:%d/api/status" % port, headers=owner), timeout=10)).get("version")
    out["status_auth"] = json.load(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:%d/api/status" % port, headers=owner), timeout=10)).get("auth")
    call("get_owner", "GET", "/", owner)
    call("get_other", "GET", "/", {"Tailscale-User-Login": "someone@else"})
    call("patch_owner", "PATCH", "/api/cards/kura", dict(owner, **{"Content-Type": "application/json", "X-Agent": "t"}),
         json.dumps({"next": "check auth"}).encode())
    call("form_crosssite", "POST", "/p/kura", dict(owner, **{"Content-Type": "application/x-www-form-urlencoded"}), b"next=x")
    call("form_sameorigin", "POST", "/p/kura", dict(owner, **{"Content-Type": "application/x-www-form-urlencoded",
         "Origin": "http://127.0.0.1:%d" % port, "Host": "127.0.0.1:%d" % port}), b"next=y")
    # CSRF: another site's page posting to the API with the owner's login (Tailscale adds it to every request)
    js = {"Content-Type": "application/json"}
    same = {"Origin": "http://127.0.0.1:%d" % port, "Host": "127.0.0.1:%d" % port}
    nxt = json.dumps({"next": "csrf"}).encode()
    call("api_xsite_origin", "PATCH", "/api/cards/kura", dict(owner, **js, Origin="https://evil.example", **{"X-Agent": "t"}), nxt)
    call("api_xsite_form", "POST", "/api/cards/kura/events", dict(owner, **{"Content-Type": "text/plain",
         "Origin": "https://evil.example"}), b"body=csrf")
    call("api_xsite_referer", "PATCH", "/api/cards/kura", dict(owner, **js, Referer="https://evil.example/x", **{"X-Agent": "t"}), nxt)
    call("api_null_origin", "PATCH", "/api/cards/kura", dict(owner, **js, Origin="null", **{"X-Agent": "t"}), nxt)
    call("api_no_agent", "PATCH", "/api/cards/kura", dict(owner, **js), nxt)
    call("api_blank_agent", "PATCH", "/api/cards/kura", dict(owner, **js, **{"X-Agent": " "}), nxt)
    call("api_web", "PATCH", "/api/cards/kura", dict(owner, **js, **same), json.dumps({"next": "board ui"}).encode())
    # KANBAN_AUTH=open and DNS rebinding: another site's name pointed at 127.0.0.1 arrives in Host (and Origin)
    evil = "evil.example:%d" % port
    call("rebind_get", "GET", "/", {"Host": evil})
    call("rebind_patch", "PATCH", "/api/cards/kura", {"Host": evil, "Origin": "http://" + evil,
         "Content-Type": "application/json", "X-Agent": "t"}, json.dumps({"next": "rebound"}).encode())
    call("rebind_form", "POST", "/p/kura", {"Host": evil, "Origin": "http://" + evil,
         "Content-Type": "application/x-www-form-urlencoded"}, b"next=rebound")
    call("rebind_owner", "GET", "/", dict(owner, Host=evil))
    call("rebind_healthz", "GET", "/healthz", {"Host": evil})
    call("host_localhost", "GET", "/", {"Host": "LocalHost.:%d" % port})
    call("host_v6", "GET", "/", {"Host": "[::1]:%d" % port})
    call("host_listed", "GET", "/", {"Host": "other.example"})
    call("host_empty", "GET", "/", {"Host": ""})
    hosts = ["127.0.0.1", "127.0.0.1:8081", "10.0.0.5:80", "[::1]", "[::1]:8081", "[FE80::1]:9", "localhost",
             "LOCALHOST:8081", "localhost.", "localhost.:8081", "kanban.example.net", "Kanban.Example.Net.:443",
             "board.example", "BOARD.example.:8443", "other.example", "", None, "evil.example", "evil.example:8081",
             "localhost.evil.example", "::1", "[::1", "[::1]x", "localhost:abc", "127.0.0.1.evil.example",
             "evil@127.0.0.1", "0x7f.1"]
    out["hosts"] = {str(h): app.host_allowed(h, app.ALLOWED_HOSTS) for h in hosts}
    out["allowed_hosts"] = sorted(app.ALLOWED_HOSTS)
    out["actors"] = sorted({e.get("actor") for e in app.store.events(card="kura")})
    print(json.dumps(out))
''')


def run(auth, bind="127.0.0.1", **extra):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_USERS="owner@example",
               KANBAN_TAILNET_PORT=str(port), KANBAN_BIND=bind, PYTHONDONTWRITEBYTECODE="1")
    env.pop("KANBAN_AUTH", None)
    env.update(extra)
    if auth is not None:
        env["KANBAN_AUTH"] = auth
    h = os.path.join(d, "harness.py"); open(h, "w").write(HARNESS)
    r = subprocess.run([sys.executable, h, APP, str(port)], env=env, capture_output=True, text=True, timeout=120)
    return r


# default (unset) = tailscale: the allow-list, nothing else changes
r = run(None); out = json.loads(r.stdout.strip().splitlines()[-1])
assert "/healthz" not in r.stderr and "GET /api/status" in r.stderr, r.stderr[-400:]     # health polls are not logged
assert out["auth"] == "tailscale" and out["bind"] == "127.0.0.1", out
assert (out["get_none"], out["get_owner"], out["get_other"]) == (403, 200, 403), out
assert out["patch_owner"] == 200 and out["form_crosssite"] == 403 and out["form_sameorigin"] == 302, out
assert out["actors"] == ["owner@example"] and out["patch_none"] == 403 and out["health_auth"] == "tailscale", out
assert out["status_auth"] == "tailscale", out
assert out["healthz"] == [200, "ok\n"] and out["healthz_head"] == 200 and out["status_none"] == 403, out    # /api/status stays gated
import re as _re
assert out["version"] == _re.search(r'VERSION = "([^"]+)"', open(os.path.join(APP, "version.py")).read()).group(1), out   # /api/status reports the release
assert out["legacy_names"] == [], out                      # the field is always there, empty when the vault is clean
assert [out[k] for k in ("api_xsite_origin", "api_xsite_form", "api_xsite_referer", "api_null_origin", "api_no_agent",
                         "api_blank_agent")] == [403] * 6, out     # CSRF: another site's page, or a caller that names nobody
assert out["api_web"] == 200, out                          # the board's own page: same origin, no X-Agent needed

# open: everyone gets in; the header is ignored and every event names 'local'; same-origin still guards form posts
r = run("open"); out = json.loads(r.stdout.strip().splitlines()[-1])
assert out["auth"] == "open" and "WARNING" in out["banner"][0], out
assert (out["get_none"], out["get_owner"], out["get_other"]) == (200, 200, 200), out
assert out["patch_owner"] == 200 and out["form_crosssite"] == 403 and out["form_sameorigin"] == 302, out
assert out["actors"] == ["local"] and out["patch_none"] == 200 and out["health_auth"] == "open", out
assert out["status_auth"] == "open", out
assert out["healthz"] == [200, "ok\n"] and out["healthz_head"] == 200 and out["status_none"] == 200, out
assert out["banner"][0].startswith("startup: WARNING: KANBAN_AUTH=open: no identity check. Anyone who can reach 127.0.0.1:"), out
# DNS rebinding: in open mode only IP literals, localhost, KANBAN_BOARD_URL's host and KANBAN_ALLOWED_HOSTS are served
assert (out["rebind_get"], out["rebind_patch"], out["rebind_form"], out["rebind_owner"]) == (403, 403, 403, 403), out
assert out["rebind_healthz"] == 200, out                     # liveness answers whatever the Host
assert out["host_localhost"] == 200 and out["host_v6"] == 200 and out["host_empty"] == 403, out
assert out["host_listed"] == 403, out                        # nothing listed in this run
assert out["allowed_hosts"] == ["localhost"], out
assert "rebound" not in json.dumps(out), out

r = run("open", KANBAN_BOARD_URL="https://Kanban.Example.Net.:443/", KANBAN_ALLOWED_HOSTS=" Board.Example.:8443 ,other.example,,")
out = json.loads(r.stdout.strip().splitlines()[-1])
assert out["allowed_hosts"] == ["board.example", "kanban.example.net", "localhost", "other.example"], out
assert out["host_listed"] == 200 and out["rebind_get"] == 403 and out["rebind_patch"] == 403, out
assert "other.example" in out["banner"][1], out
refused = {"", "None", "evil.example", "evil.example:8081", "localhost.evil.example", "::1", "[::1", "[::1]x",
           "localhost:abc", "127.0.0.1.evil.example", "evil@127.0.0.1", "0x7f.1"}
assert {h for h, ok in out["hosts"].items() if not ok} == refused, out["hosts"]

# tailscale mode never looks at Host (the proxy's identity header decides)
r = run(None); out = json.loads(r.stdout.strip().splitlines()[-1])
assert out["rebind_owner"] == 200 and out["rebind_get"] == 403, out

# an unknown mode refuses to start
r = run("opne")
assert r.returncode != 0 and "konbini: KANBAN_AUTH must be tailscale or open, not 'opne'" in r.stderr, (r.returncode, r.stderr[-300:])
print("auth tests: all passed")
