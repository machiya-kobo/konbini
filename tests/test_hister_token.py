"""KANBAN_HISTER_TOKEN_FILE: the owner's Hister token goes to Hister as X-Access-Token on every call, and to the hister
CLI as HISTER__APP__ACCESS_TOKEN in its environment (never its arguments); unset, nothing is sent (and a token the
process inherited is not passed on); a rotated file is read at the next call; a missing file sends nothing and the error
names the file; nothing puts the value in an error, the status or the board's logs. A fake Hister records the requests."""
import http.server, json, os, socket, stat, subprocess, sys, tempfile, textwrap, threading, time, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import hister  # noqa: E402

TOKEN = "tok-3f9a1c0d-never-log-me"
seen = []
stolen = []


class Elsewhere(http.server.BaseHTTPRequestHandler):
    """Where a redirect would send the token."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        stolen.append((self.path, self.headers.get("X-Access-Token")))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Elsewhere)
threading.Thread(target=other.serve_forever, daemon=True).start()


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        seen.append((self.command, self.path, self.headers.get("X-Access-Token"), self.headers.get("Origin")))
        if self.path.startswith("/redir"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/stolen" % other.server_address[1])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"documents": [], "total": 0}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = reply


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
API = "http://127.0.0.1:%d" % srv.server_address[1]
tmp = tempfile.mkdtemp()
tokfile = os.path.join(tmp, "token")
open(tokfile, "w").write(TOKEN + "\n")


def tokens_since(n):
    return [t for _, _, t, _ in seen[n:]]


# every request carries the token (and the Origin Hister needs), whatever the call
h = hister.Hister(API, "", token_file=tokfile)
n = len(seen)
h.call("GET", "/search?q=x")
h.search("konbini")
h.call("POST", "/api/add", {"url": "https://example.com/"})
h.delete("https://example.com/")
assert len(seen) - n >= 4 and set(tokens_since(n)) == {TOKEN}, seen[n:]
assert all(o == "hister://" for _, _, _, o in seen[n:])

# a redirect is not followed: the token goes to Hister and nowhere else
status, _ = h.call("GET", "/redir")
assert status == 302 and stolen == [], (status, stolen)

# unset: nothing is sent
n = len(seen)
hister.Hister(API, "").call("GET", "/search?q=x")
assert tokens_since(n) == [None], seen[n:]

# the file is read at each call: a rotation is picked up without a restart
open(tokfile, "w").write("rotated-token\n")
n = len(seen)
h.call("GET", "/search?q=y")
assert tokens_since(n) == ["rotated-token"]
open(tokfile, "w").write(TOKEN + "\n")

# a missing or empty file: no header, an error that names the file and no value
for path in (os.path.join(tmp, "missing"), os.path.join(tmp, "empty")):
    open(os.path.join(tmp, "empty"), "w").write("\n")
    n = len(seen)
    g = hister.Hister(API, "", token_file=path)
    g.call("GET", "/search?q=z")
    assert tokens_since(n) == [None] and path in g.error and TOKEN not in g.error, g.error

# the CLI: the token is in its environment only; unset, an inherited one is dropped
cli = os.path.join(tmp, "hister")
out = os.path.join(tmp, "cli.json")
open(cli, "w").write("#!/bin/sh\nprintf '%%s\\n%%s\\n' \"$*\" \"$HISTER__APP__ACCESS_TOKEN\" > '%s'\nexit 0\n" % out)
os.chmod(cli, os.stat(cli).st_mode | stat.S_IXUSR)
assert hister.Hister(API, "", cli=cli, token_file=tokfile).index("https://example.com/x")
argv, env_token = open(out).read().split("\n")[:2]
assert env_token == TOKEN and TOKEN not in argv and "example.com/x" in argv, (argv, env_token)
os.environ["HISTER__APP__ACCESS_TOKEN"] = "inherited-token"
assert hister.Hister(API, "", cli=cli).index("https://example.com/y")
assert open(out).read().split("\n")[1] == "", "an inherited token must not reach the CLI when no token file is set"
del os.environ["HISTER__APP__ACCESS_TOKEN"]
# a failing CLI that echoes the token: the error doesn't
open(cli, "w").write("#!/bin/sh\necho \"denied for $HISTER__APP__ACCESS_TOKEN\" >&2\nexit 1\n")
bad = hister.Hister(API, "", cli=cli, token_file=tokfile)
assert not bad.index("https://example.com/z") and TOKEN not in bad.error and "***" in bad.error, bad.error

# a running board: the header reaches Hister, and the value is in no log, page or status
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
d = tempfile.mkdtemp()
os.makedirs(d + "/Projects")
open(d + "/Projects/Kura.md", "w").write("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n"
                                          "project: kura\nstatus: wip\n---\n# Kura\n")
subprocess.run(["git", "-C", d, "init", "-q"], check=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
           KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1", KANBAN_HISTER_URL=API, KANBAN_HISTER_TOKEN_FILE=tokfile)
open(d + "/server.py", "w").write(SERVER)
proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.05)
    n = len(seen)
    pages = [urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=20).read().decode()
             for path in ("/p/kura", "/api/status", "/api/health", "/settings")]
    assert len(seen) > n and set(tokens_since(n)) == {TOKEN}, seen[n:]      # the board's own Hister calls carry it
    assert all(TOKEN not in page for page in pages), "the token appeared on a page or in the API"
finally:
    proc.terminate()
    try:
        out_b, err_b = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_b, err_b = proc.communicate()
assert TOKEN.encode() not in out_b + err_b, "the token appeared in the board's logs"
print("hister token tests: all passed")
