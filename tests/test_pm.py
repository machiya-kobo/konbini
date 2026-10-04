"""tools/pm against a fake board: each command sends the right request, and the failure messages are plain."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "pm")
CARD = {"slug": "one", "title": "One", "board": "wip", "priority": 1, "effort": "s", "area": "tools", "next": "do it",
        "summary": "s", "blocked_by": "", "topics": [], "machines": [], "dependsOn": ["Two"], "path": "Projects/One.md",
        "checks_total": 2, "checks_done": 1}
TWO = dict(CARD, slug="two", title="Two", board="ready", priority=None, path="Projects/Two.md", dependsOn=[])
seen, auths, mode = [], [], {"status": 200}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def handle_any(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else None
        seen.append((self.command, self.path, body, self.headers.get("X-Agent")))
        auths.append(self.headers.get("Authorization"))
        if mode["status"] != 200 and self.command != "GET":
            return self.reply(mode["status"], {"error": "nope"})
        if mode["status"] == 403:
            return self.reply(403, {})
        if self.path.startswith("/api/cards?") or self.path == "/api/cards":
            return self.reply(200, {"cards": [CARD, TWO]})
        if self.path == "/api/cards/one":
            return self.reply(200, dict(CARD, **(body or {})))
        if self.path.startswith("/api/cards/one/kit"):
            return self.reply(200, {"markdown": "# kit\n"})
        self.reply(200, dict(CARD, **(body or {})))
    do_GET = do_POST = do_PATCH = handle_any


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % srv.server_port


def pm(*args, env=None, status=200):
    mode["status"] = status
    del seen[:], auths[:]
    e = {"PATH": os.environ["PATH"], "KANBAN_URL": URL, "KANBAN_AGENT": "pm@test"}
    e.update(env or {})
    r = subprocess.run([sys.executable, PM] + list(args), env=e, capture_output=True, text=True, timeout=30)
    return r


r = pm("ls", "--area", "tools"); assert r.returncode == 0 and "one" in r.stdout and "ready" in r.stdout, r
assert seen[0][:2] == ("GET", "/api/cards?area=tools") and seen[0][3] == "pm@test", seen
r = pm("show", "one"); assert "wip" in r.stdout and "1/2" in r.stdout and URL + "/p/one" in r.stdout, r.stdout
r = pm("move", "one", "done"); assert seen[-1][:3] == ("PATCH", "/api/cards/one", {"board": "done"}), seen
r = pm("next", "one", "write it up"); assert seen[-1][2] == {"next": "write it up"}, seen
r = pm("block", "one", "a part"); assert seen[-1][2] == {"status": "blocked", "waiting": "a part"}, seen
r = pm("log", "one", "shipped"); assert seen[-1][:3] == ("POST", "/api/cards/one/events", {"type": "comment", "body": "shipped"}), seen
r = pm("tag", "one", "+topic/a", "-topic/b"); assert r.returncode == 0 and seen[-1][2] == {"tags_add": ["topic/a"], "tags_remove": ["topic/b"]}, (r, seen)
r = pm("dep", "one", "-two"); assert r.returncode == 0 and seen[-1][2] == {"dependsOn": []}, (r, seen)
r = pm("dep", "one", "+Three"); assert seen[-1][2] == {"dependsOn": ["Two", "Three"]}, seen
r = pm("stream", "one", "Release 1.0"); assert seen[-1][2] == {"stream": "Release 1.0"}, seen
r = pm("goal", "one", "-"); assert seen[-1][2] == {"goal": ""}, seen
r = pm("due", "one", "2026-12-01"); assert seen[-1][2] == {"due": "2026-12-01"}, seen
r = pm("new", "A card", "--area", "tools", "--summary", "s"); assert seen[-1][:3] == ("POST", "/api/cards", {"title": "A card", "area": "tools", "board": "backlog", "summary": "s"}), seen
r = pm("claim", "one"); assert seen[-1][:2] == ("POST", "/api/cards/one/claim"), seen
r = pm("kit", "one"); assert r.stdout == "# kit\n", r

# failures say what to do
r = pm("suggest", "Projects/One.md"); assert r.returncode != 0 and "NIWA_URL" in r.stderr and not seen, (r, seen)
r = pm("suggest", "Projects/One.md", env={"NIWA_URL": URL}); assert r.returncode == 0 and seen[-1][:2] == ("POST", "/api/suggest"), (r, seen)
r = pm("move", "one", "done", status=405); assert r.returncode != 0 and "HTTP 405" in r.stderr and "KANBAN_URL" in r.stderr, r
r = pm("ls", status=403); assert r.returncode != 0 and "403" in r.stderr and "KANBAN_AUTH" in r.stderr, r
r = pm("ls", env={"KANBAN_URL": "http://127.0.0.1:9"}); assert r.returncode != 0 and "can't reach" in r.stderr, r
src = open(PM).read()
import re
assert not re.search(r"\.ts\.net\b|/home/|\b\d{1,3}(\.\d{1,3}){3}\b", src.replace("127.0.0.1:8081", "")), "pm names a host, an address or a home path"
r = subprocess.run([sys.executable, PM, "--help"], capture_output=True, text=True); assert "KANBAN_URL" in r.stdout and "pm move" in r.stdout, r.stdout[:300]
# KANBAN_TOKEN_FILE: the owner's Hister token as a Bearer token, to the board only; none unset; a bad file stops pm
import tempfile
tok = os.path.join(tempfile.mkdtemp(), "token"); open(tok, "w").write("hister-token-xyz\n")
r = pm("ls"); assert r.returncode == 0 and auths == [None], auths                                  # unset: nothing sent
r = pm("ls", env={"KANBAN_TOKEN_FILE": tok}); assert r.returncode == 0 and auths == ["Bearer hister-token-xyz"], (r, auths)
assert "hister-token-xyz" not in r.stdout + r.stderr
r = pm("move", "one", "done", env={"KANBAN_TOKEN_FILE": tok}); assert auths == ["Bearer hister-token-xyz"], auths
r = pm("ls", env={"KANBAN_TOKEN_FILE": tok + ".missing"}); assert r.returncode != 0 and (tok + ".missing") in r.stderr and "KANBAN_TOKEN_FILE" in r.stderr, r
open(tok, "w").write("\n"); r = pm("ls", env={"KANBAN_TOKEN_FILE": tok}); assert r.returncode != 0 and "empty" in r.stderr, r
# the sweep's KONB-10: the token never goes over plain http to a host that isn't this machine, a redirect isn't followed while
# one is sent, and an address without a scheme is https
tok2 = os.path.join(tempfile.mkdtemp(), "t"); open(tok2, "w").write("secret-token-9\n")
r = pm("ls", env={"KANBAN_TOKEN_FILE": tok2, "KANBAN_URL": "http://board.example.test:9"})
assert r.returncode != 0 and "not sending the Hister token over plain http" in r.stderr and "secret-token-9" not in r.stderr + r.stdout, r
other_hits = []
class Other(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self): other_hits.append(self.headers.get("Authorization")); self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
class Redirect(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        seen.append(("GET", self.path, None, self.headers.get("X-Agent"))); auths.append(self.headers.get("Authorization"))
        self.send_response(302); self.send_header("Location", OTHER + "/api/cards"); self.send_header("Content-Length", "0"); self.end_headers()
osrv = HTTPServer(("127.0.0.1", 0), Other); threading.Thread(target=osrv.serve_forever, daemon=True).start()
OTHER = "http://127.0.0.1:%d" % osrv.server_port
rsrv = HTTPServer(("127.0.0.1", 0), Redirect); threading.Thread(target=rsrv.serve_forever, daemon=True).start()
r = pm("ls", env={"KANBAN_TOKEN_FILE": tok2, "KANBAN_URL": "http://127.0.0.1:%d" % rsrv.server_port})
assert r.returncode != 0 and "redirect" in r.stderr and auths == ["Bearer secret-token-9"] and other_hits == [], (r, auths, other_hits)
assert "secret-token-9" not in r.stderr + r.stdout
r = pm("ls", env={"KANBAN_URL": "localhost:%d" % srv.server_port})             # no scheme: https, so a plain-http board refuses the handshake
assert r.returncode != 0 and "https://localhost:" in r.stderr, r.stderr
print("pm tests: all passed")
