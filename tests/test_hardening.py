"""Hardening: redirects stay on this site (back() after a form post, the /theme fallback). A board runs in its own
process (settings are read at import) on 127.0.0.1, serving a throwaway vault, and is talked to over raw HTTP."""
import http.client, json, os, socket, subprocess, sys, tempfile, textwrap, time

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n"
        "project: kura\nstatus: wip\n---\n# Kura\n")
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')


def start(**extra):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, port
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


def request(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.getheader("Location"), r.read())
    c.close()
    return out


proc, port = start()
try:
    host = "127.0.0.1:%d" % port
    same = {"Host": host, "Origin": "http://" + host, "Content-Type": "application/x-www-form-urlencoded"}

    def back(referer):
        h = dict(same, Referer=referer) if referer is not None else same
        status, location, _ = request(port, "POST", "/p/kura", h, b"next=check+redirects")
        assert status == 302, (referer, status)
        return location

    def theme(referer):
        status, location, _ = request(port, "GET", "/theme?set=night", {"Referer": referer} if referer is not None else {})
        assert status == 302, (referer, status)
        return location

    # on-site: the page (and for back(), its query) the form or the toggle was on
    assert back("http://%s/p/kura?tagmsg=x" % host) == "/p/kura?tagmsg=x"
    assert back("/review") == "/review"
    assert back("//evil.example/x") == "/x"                # a host-relative Referer: only its path is used
    assert theme("http://%s/review?lane=ops" % host) == "/review"
    # off-site or unusable: the fallback (the card for a card form, / for the theme toggle)
    for ref in ("http://h//evil.example", "http://h/\\evil.example", "/\\evil.example",
                "http://h/\t/evil.example", "http://h/\\\t\\evil.example", "http://h/x\x01y", "http://h/x\x7fy",
                "evil.example", "http://[::1/x", "", None, "?q=1", "http://h"):
        assert back(ref) == "/p/kura", (ref, back(ref))
        assert theme(ref) == "/", (ref, theme(ref))
    assert back("http://h/x?y=\x01") == "/p/kura"          # a control character in the query too
    assert theme("http://h/x?y=\x01") == "/x"              # (the theme toggle drops the query)
finally:
    proc.kill()
    proc.wait()

print("hardening tests: all passed")
