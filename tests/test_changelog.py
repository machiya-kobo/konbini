"""GET /api/changelog: the app's own CHANGELOG.md as text/markdown (vaultkit.changelog), behind the same gate as
/api/health: 200 with an ETag, 304 on a matching If-None-Match, HEAD without a body, 404 when there is no file (never a
500). /api/health also names the vendored vaultkit. A board runs in its own process on 127.0.0.1 over a throwaway vault."""
import http.client, json, os, socket, subprocess, sys, tempfile, textwrap, time

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
ROOT = os.path.join(APP, "..")
NOTE = "---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\nproject: kura\nstatus: wip\n---\n# Kura\n"
SERVER = textwrap.dedent('''
    import os, sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.CHANGELOG = os.environ["TEST_CHANGELOG"]
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
procs = []


def start(changelog, **extra):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1", TEST_CHANGELOG=changelog)
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            time.sleep(0.05)
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


def get(port, path, method="GET", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read())
    c.close()
    return out


try:
    real = os.path.join(APP, "CHANGELOG.md")
    port = start(real)
    status, h, body = get(port, "/api/changelog")
    assert status == 200 and h["content-type"].startswith("text/markdown"), (status, h)
    assert body.decode().startswith("# Changelog") and "\n## " in body.decode(), body[:80]
    assert h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-cache"
    tag = h["etag"]
    status, h2, body2 = get(port, "/api/changelog", headers={"If-None-Match": tag})
    assert status == 304 and body2 == b"", (status, body2)                 # a poller asks again cheaply
    assert get(port, "/api/changelog", headers={"If-None-Match": '"nope"'})[0] == 200
    status, h3, body3 = get(port, "/api/changelog", "HEAD")
    assert status == 200 and body3 == b"" and int(h3["content-length"]) == len(body), (status, h3)
    health = json.loads(get(port, "/api/health")[2])
    assert health["vaultkit"].startswith("v0."), health                    # the vendored vaultkit, for the status page

    port = start(os.path.join(tempfile.mkdtemp(), "missing.md"))           # no file: a 404, not a 500
    status, h, body = get(port, "/api/changelog")
    assert status == 404 and h["content-type"].startswith("text/plain"), (status, h)

    # behind the gate: with the tailnet check on, a request without the proxy's identity is refused like /api/health
    port = start(real, KANBAN_AUTH="tailscale", KANBAN_TAILNET_USERS="owner@example.com")
    assert get(port, "/api/changelog")[0] == get(port, "/api/health")[0] != 200
    assert get(port, "/api/changelog", headers={"Tailscale-User-Login": "owner@example.com"})[0] == 200
finally:
    for p in procs:
        p.kill()
print("changelog tests: all passed")
