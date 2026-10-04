"""Fixes from the 2026-10 security sweep (KONB-*): no control character reaches a response header (a crafted
/garden/x%0D%0ASet-Cookie link used to inject one), a request the handler can't take is a 400 or a JSON 500 and never a
dropped connection, a newline in a title or summary can't write a bare ======= (which stopped the export for every
card), one bad note is held out of a commit while the rest goes, and a card's file name is never empty. Each board
runs in its own process on 127.0.0.1 over a throwaway vault, and is talked to over raw HTTP."""
import json, os, socket, subprocess, sys, tempfile, textwrap, time

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
NOTE = "---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\nproject: kura\nstatus: wip\nrepo: \"javascript:alert(1)\"\n---\n# Kura\n"
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
procs = []


def start(**extra):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/Projects")
    open(d + "/Projects/Kura.md", "w").write(NOTE)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB=d + "/db/k.db", KANBAN_AUTH="open", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", PYTHONDONTWRITEBYTECODE="1", KANBAN_NIWA_URL="https://niwa.example")
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port, d
        except OSError:
            time.sleep(0.05)
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


def raw(port, method, target, body=None, headers=()):
    """The status line's code and the whole answer, from a request line written by hand (nothing re-encodes it).
    0 and b'' when the connection is dropped with no answer."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    head = "%s %s HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nX-Agent: test\r\n%s" % (method, target, port, "".join(h + "\r\n" for h in headers))
    if data:
        head += "Content-Type: application/json\r\nContent-Length: %d\r\n" % len(data)
    s.sendall(head.encode() + b"\r\n" + data)
    out = b""
    while True:
        try:
            chunk = s.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    s.close()
    return (int(out.split(b" ", 2)[1]) if out.startswith(b"HTTP/") else 0), out


def body_of(out):
    return out.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in out else b""


try:
    port, d = start()
    # KONB-2: a control character in the address is a 400 and never reaches a header
    status, out = raw(port, "GET", "/garden/x%0D%0ASet-Cookie:%20machiya_sso=1;%20Domain=example.net")
    assert status == 400 and b"Set-Cookie" not in out and b"machiya_sso" not in out, out[:300]
    status, out = raw(port, "GET", "/garden/x%0aLocation:%20https://evil.example")
    assert status == 400 and b"evil.example" not in out, out[:200]
    assert raw(port, "POST", "/p/kura%0D%0AX-Evil:%201", {"comment": "x"})[0] == 400
    assert raw(port, "GET", "/api/cards?q=%00")[0] == 400
    assert raw(port, "GET", "http://[::1/")[0] == 400                                  # an address urlsplit refuses
    # a good redirect is unchanged, and what is in it is encoded
    status, out = raw(port, "GET", "/garden/a%20b/c?x=1")
    assert status == 302 and b"Location: https://niwa.example/a%20b/c?x=1" in out, out[:300]
    # the log keeps a control character out of its lines too (checked on stderr below)

    # KONB-5: bad input is an answer, not a dropped connection
    assert raw(port, "GET", "/api/events?limit=x")[0] == 200
    for path in ("/timeline?from=9999-12", "/calendar?month=9999-12", "/roundup?date=0001-01-01", "/roundup?period=year&date=9999-12-31"):
        assert raw(port, "GET", path)[0] == 200, path
    assert raw(port, "POST", "/api/order", {"slugs": "kura", "board": "wip"})[0] == 422
    assert raw(port, "POST", "/api/order", {"slugs": [1, 2], "board": "wip"})[0] == 422
    assert raw(port, "POST", "/api/order", {"slugs": 5})[0] == 422
    assert raw(port, "PATCH", "/api/cards/kura", {"tags_add": [1]})[0] == 422
    assert raw(port, "PATCH", "/api/cards/kura", {"tags_remove": 5})[0] == 422
    assert raw(port, "POST", "/api/cards", {"title": "t", "area": "x", "topics": [1]})[0] == 422
    assert raw(port, "POST", "/api/cards/kura/claim", b'{"minutes": 1e999}')[0] == 422
    status, out = raw(port, "POST", "/api/cards", {"title": "x" * 300, "area": "projects", "board": "backlog"})
    assert status in (201, 422), status                                                  # a long title is capped, not a crash
    assert status == 422 or max(len(n.encode()) for n in os.listdir(d + "/Projects")) < 255

    # KONB-1 / KONB-6: a newline can't write a bare ======= and a title always has a file name
    status, out = raw(port, "POST", "/api/cards", {"title": "Notes", "area": "projects", "board": "backlog",
                                                    "summary": "Notes\n=======\nmore\r\n<<<<<<< x"})
    assert status == 201, (status, out[-200:])
    text = open(d + "/Projects/Notes.md").read()
    assert not any(l.strip().startswith(("=======", "<<<<<<<", ">>>>>>>")) for l in text.splitlines()), text
    assert "Notes ======= more <<<<<<< x" in text and "\n=======" not in text, text
    status, out = raw(port, "POST", "/api/cards", {"title": "???", "area": "projects", "board": "backlog"})
    assert status == 201, (status, out[-200:], sorted(os.listdir(d + "/Projects")))
    assert os.path.exists(d + "/Projects/card.md") and not os.path.exists(d + "/Projects/.md"), os.listdir(d + "/Projects")
    assert raw(port, "POST", "/api/cards", {"title": ["x"], "area": "projects"})[0] == 422
    status, out = raw(port, "POST", "/api/cards", {"title": "Two\nlines\x07here", "area": "projects", "board": "backlog"})
    assert status == 201 and os.path.exists(d + "/Projects/Two lines here.md"), os.listdir(d + "/Projects")
    assert "# Two lines here" in open(d + "/Projects/Two lines here.md").read()
    # a form post (the share target) is as safe
    status, out = raw(port, "POST", "/share", b"url=https%3A%2F%2Fexample.org&text=a%0A%3D%3D%3D%3D%3D%3D%3D%0Ab&title=Shared",
                      ["Origin: http://127.0.0.1:%d" % port, "Content-Type: application/x-www-form-urlencoded"])
    assert status in (302, 403), status

    # KONB-3 / KONB-4: the card form saves only what you changed, refuses a field somebody else changed meanwhile, and writes
    # the comment only after the rest was accepted, and only on a card that exists
    import http.client, urllib.parse
    def api(method, path, body=None):
        status, out = raw(port, method, path, body)
        return status, (json.loads(body_of(out)) if body_of(out).strip().startswith(b"{") else None)
    def form(path, fields):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", path, body=urllib.parse.urlencode(fields), headers={
            "Content-Type": "application/x-www-form-urlencoded", "Origin": "http://127.0.0.1:%d" % port})
        r = c.getresponse(); r.read(); c.close()
        return r.status
    page_html = body_of(raw(port, "GET", "/p/kura")[1]).decode()
    assert 'name="o_next"' in page_html and 'name="o_due"' in page_html
    drawn = {"priority": "", "next": "", "blocked_by": "", "dependsOn": "", "stream": "", "goal": "", "due": "", "post": "none", "post_url": ""}
    # an agent changes next and waiting while the owner's page is open
    assert api("PATCH", "/api/cards/kura", {"next": "agent's step", "waiting": "the review"})[0] == 200
    # the owner types only a note and presses Save: the page still holds the old (empty) values
    f = dict(drawn, comment="looks good", **{"o_" + k: v for k, v in drawn.items()})
    assert form("/p/kura", f) == 302
    card = api("GET", "/api/cards/kura")[1]
    assert card["next"] == "agent's step" and card["blocked_by"] == "the review", card                    # nothing reverted
    events = api("GET", "/api/events?limit=50")[1]["events"]
    assert any(e.get("body") == "looks good" for e in events)
    # the owner changes a field somebody else changed: refused, and no note is written
    f = dict(drawn, next="mine", comment="should not appear", **{"o_" + k: v for k, v in drawn.items()})
    assert form("/p/kura", f) == 409
    assert api("GET", "/api/cards/kura")[1]["next"] == "agent's step"
    assert not any(e.get("body") == "should not appear" for e in api("GET", "/api/events?limit=50")[1]["events"])
    # a field changed from what the page drew, and nobody else touched it: saved
    f = dict(drawn, stream="Machiya", **{"o_" + k: v for k, v in drawn.items()})
    f["next"] = "agent's step"; f["o_next"] = "agent's step"; f["blocked_by"] = "the review"; f["o_blocked_by"] = "the review"
    assert form("/p/kura", f) == 302 and api("GET", "/api/cards/kura")[1]["stream"] == "Machiya"
    # a card that doesn't exist gets no orphan note; an invalid save adds no comment
    assert form("/p/no-such-card", {"comment": "orphan"}) == 404
    assert not any(e.get("card") == "no-such-card" for e in api("GET", "/api/events?limit=200")[1]["events"])
    f = dict(drawn, due="not-a-date", comment="duplicate me", **{"o_" + k: v for k, v in drawn.items()})
    f["next"] = "agent's step"; f["o_next"] = "agent's step"; f["blocked_by"] = "the review"; f["o_blocked_by"] = "the review"
    assert form("/p/kura", f) == 422
    assert not any(e.get("body") == "duplicate me" for e in api("GET", "/api/events?limit=200")[1]["events"])
    # drag and drop: a card somebody moved meanwhile is left alone
    assert api("POST", "/api/cards", {"title": "Finished", "area": "projects", "board": "done"})[0] == 201
    status, out = api("POST", "/api/order", {"board": "wip", "slugs": ["finished"], "from": {"finished": "wip"}})   # the page thought it was in wip
    assert status == 200 and out["skipped"] == ["finished"] and api("GET", "/api/cards/finished")[1]["board"] == "done", out
    status, out = api("POST", "/api/order", {"board": "wip", "slugs": ["finished"], "from": {"finished": "done"}})
    assert status == 200 and out["skipped"] == [] and api("GET", "/api/cards/finished")[1]["board"] == "wip", out

    # SVG answers are sandboxed and every answer says nosniff; a javascript: repo from frontmatter is text, not a link
    status, out = raw(port, "GET", "/static/icons/konbini.svg")
    head = out.split(b"\r\n\r\n")[0].decode().lower()
    assert status == 200 and "content-security-policy: default-src 'none'; style-src 'unsafe-inline'; sandbox" in head and "x-content-type-options: nosniff" in head, head
    assert "x-content-type-options: nosniff" in raw(port, "GET", "/api/cards")[1].split(b"\r\n\r\n")[0].decode().lower()
    html = body_of(raw(port, "GET", "/p/kura")[1]).decode()
    assert "javascript:alert(1)" in html and 'href="javascript:' not in html.lower(), "the repo value is shown as text, never as a link"
finally:
    for p in procs:
        p.terminate()
    errs = b"".join(p.communicate(timeout=10)[1] or b"" for p in procs)
import re                                                                       # the log has no raw control character (encoded text is fine)
assert not re.search(rb"[\x00-\x09\x0b-\x1f\x7f]", errs), errs[:400]

# the export: one note with a conflict marker is held out of the commit and the rest of the batch goes
from store import Store            # noqa: E402
from writer import Writer          # noqa: E402
g = tempfile.mkdtemp(); os.makedirs(g + "/Projects")
for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
    subprocess.run(["git", "-C", g] + args, check=True)
open(g + "/Projects/Kura.md", "w").write(NOTE)
subprocess.run(["git", "-C", g, "add", "-A"], check=True); subprocess.run(["git", "-C", g, "commit", "-qm", "init"], check=True)
st = Store(g + "/db/k.db", g); st.rebuild()
w = Writer(st)
w.create({"title": "Good", "area": "projects", "board": "backlog"}, "me", "test")
open(g + "/Projects/Bad.md", "w").write(NOTE.replace("Kura", "Bad") + "\nTitle\n=======\n")
w.commit(force=True)
tracked = subprocess.run(["git", "-C", g, "ls-files"], capture_output=True, text=True).stdout.split("\n")
assert "Projects/Good.md" in tracked and "Projects/Bad.md" not in tracked, tracked        # the good card went, the bad one stayed out
assert "Bad.md" in w.error and "conflict markers" in w.error, w.error
assert w.pending and "held back" in w.pending[0][1], w.pending
print("sweep tests: all passed")
