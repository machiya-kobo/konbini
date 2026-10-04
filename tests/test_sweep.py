"""Fixes from the 2026-10 security sweep (KONB-*): no control character reaches a response header (a crafted
/garden/x%0D%0ASet-Cookie link used to inject one), a request the handler can't take is a 400 or a JSON 500 and never a
dropped connection, a newline in a title or summary can't write a bare ======= (which stopped the export for every
card), one bad note is held out of a commit while the rest goes, and a card's file name is never empty. Each board
runs in its own process on 127.0.0.1 over a throwaway vault, and is talked to over raw HTTP."""
import json, os, socket, subprocess, sys, tempfile, textwrap, time

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
NOTE = "---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\nproject: kura\nstatus: wip\n---\n# Kura\n"
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
