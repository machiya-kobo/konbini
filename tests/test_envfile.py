"""--env-file / KANBAN_ENV_FILE (native installs): settings from KEY=VALUE lines, loaded before any setting is read;
the real environment wins; a missing or bad file stops start-up naming the file and line (never the line's text)."""
import json, os, socket, subprocess, sys, tempfile, textwrap

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\n"
        "project: kura\nstatus: wip\n---\n# Kura\n")
HARNESS = textwrap.dedent('''
    import json, sys, threading, time, urllib.request, urllib.error
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    threading.Thread(target=app.serve, args=(app.TAILNET_PORT, "tailnet"), daemon=True).start()
    time.sleep(0.5)
    try:
        code = urllib.request.urlopen("http://%s:%d/api/status" % (app.BIND, app.TAILNET_PORT), timeout=10).status
    except urllib.error.HTTPError as e:
        code = e.code
    print(json.dumps({"bind": app.BIND, "port": app.TAILNET_PORT, "auth": app.AUTH, "env_file": app.ENV_FILE,
                      "banner": app.auth_banner(), "status": code, "tz": __import__("os").environ.get("TZ")}))
''')


def setup(lines):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env_file = os.path.join(d, "konbini.env")
    open(env_file, "w").write("\n".join(l.format(d=d, port=port) for l in lines) + "\n")
    h = os.path.join(d, "harness.py"); open(h, "w").write(HARNESS)
    return d, port, env_file, h


def run(h, args, extra_env=None):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra_env or {})
    return subprocess.run([sys.executable, h, APP] + args, env=env, capture_output=True, text=True, timeout=120)


GOOD = ["# Konbini's settings", "KANBAN_BIND=127.0.0.1", "export KANBAN_TAILNET_PORT={port}", "KANBAN_AUTH=open",
        "KANBAN_REPO='{d}'", 'KANBAN_DB="{d}/db/k.db"', "TZ=Asia/Tokyo  # the board's days", ""]

# --env-file: everything comes from the file (a clean environment otherwise)
d, port, f, h = setup(GOOD)
r = run(h, ["--env-file", f]); out = json.loads(r.stdout.strip().splitlines()[-1])
assert (out["bind"], out["port"], out["auth"], out["status"], out["tz"]) == ("127.0.0.1", port, "open", 200, "Asia/Tokyo"), out
assert out["env_file"] == f and out["banner"][0] == "startup: settings from " + f, out

# KANBAN_ENV_FILE does the same; the real environment wins over the file
r = run(h, [], {"KANBAN_ENV_FILE": f, "KANBAN_AUTH": "tailscale", "KANBAN_TAILNET_USERS": "me@example"})
out = json.loads(r.stdout.strip().splitlines()[-1])
assert out["auth"] == "tailscale" and out["status"] == 403 and out["env_file"] == f, out

# a missing file stops start-up, naming it
r = run(h, ["--env-file", "/nonexistent/konbini.env"])
assert r.returncode != 0 and "konbini: env file:" in r.stderr and "/nonexistent/konbini.env" in r.stderr, r.stderr[-300:]

# a bad line stops start-up with the file and line number, never the line's text (it may hold a secret)
d, port, f, h = setup(["KANBAN_BIND=127.0.0.1", "KANBAN_AUTH=open", "this is not a setting s3cr3t-token"])
r = run(h, ["--env-file", f])
assert r.returncode != 0 and f in r.stderr and "line 3" in r.stderr and "s3cr3t" not in r.stderr, r.stderr[-300:]
print("envfile tests: all passed")
