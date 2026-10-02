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
    out["actors"] = sorted({e.get("actor") for e in app.store.events(card="kura")})
    print(json.dumps(out))
''')


def run(auth, bind="127.0.0.1"):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_USERS="owner@example",
               KANBAN_TAILNET_PORT=str(port), KANBAN_BIND=bind, PYTHONDONTWRITEBYTECODE="1")
    env.pop("KANBAN_AUTH", None)
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

# open: everyone gets in; the header is ignored and every event names 'local'; same-origin still guards form posts
r = run("open"); out = json.loads(r.stdout.strip().splitlines()[-1])
assert out["auth"] == "open" and "WARNING" in out["banner"][0], out
assert (out["get_none"], out["get_owner"], out["get_other"]) == (200, 200, 200), out
assert out["patch_owner"] == 200 and out["form_crosssite"] == 403 and out["form_sameorigin"] == 302, out
assert out["actors"] == ["local"] and out["patch_none"] == 200 and out["health_auth"] == "open", out
assert out["status_auth"] == "open", out
assert out["healthz"] == [200, "ok\n"] and out["healthz_head"] == 200 and out["status_none"] == 200, out
assert out["banner"][0].startswith("startup: WARNING: KANBAN_AUTH=open: no identity check. Anyone who can reach 127.0.0.1:"), out

# an unknown mode refuses to start
r = run("opne")
assert r.returncode != 0 and "konbini: KANBAN_AUTH must be tailscale or open, not 'opne'" in r.stderr, (r.returncode, r.stderr[-300:])
print("auth tests: all passed")
