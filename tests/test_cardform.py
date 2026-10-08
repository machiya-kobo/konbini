"""The card's description, its single edit form, closing a card (Archive, Won't do), changing a card's lane, and
Group By Stream. The writer's rules run against a throwaway vault; the web forms against a board on 127.0.0.1 (as a
browser posts them: form encoding, CRLF line breaks, the o_<name> originals). See also test_outbox.py for the same
forms while offline."""
import json, os, re, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request
from urllib.parse import urlencode

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from store import Store  # noqa: E402
from writer import Writer, WriteError, lead_of, merge_note, set_lead  # noqa: E402

# -- the description: the lead of a note ---------------------------------------------------------------------------
note = "---\ntitle: T\n---\n\n# T\n\nfirst\n\nsecond\n\n## Log\n\n| a |\n"
assert lead_of(note) == "first\n\nsecond"
assert lead_of("---\ntitle: T\n---\nplain lead\n\n## Next\n") == "plain lead"          # a note with no title heading
assert lead_of("---\ntitle: T\n---\n# T\n\n```\n# not a heading\n```\n\n## Real\n") == "```\n# not a heading\n```"
assert lead_of("---\ntitle: T\n---\n# T\n\n> Stub created by Konbini. Flesh out as needed.\n\n## Overview\n\nx\n") == ""
out = set_lead(note, "new\n\n- a\n- b")
assert out.endswith("# T\n\nnew\n\n- a\n- b\n\n## Log\n\n| a |\n") and lead_of(out) == "new\n\n- a\n- b", out     # the rest is untouched
assert set_lead(note, "").endswith("# T\n\n## Log\n\n| a |\n")
for bad in ("a\n## heading", "open\n```\nfence"):
    try:
        set_lead(note, bad)
        raise SystemExit("accepted " + repr(bad))
    except WriteError as e:
        assert e.status == 422

# the merge after a pull: the board's description edit survives an upstream edit elsewhere, never one to the description
base = "---\ntitle: T\nstatus: wip\n---\n# T\n\nold\n\n## Log\n\nrow1\n"
mine, theirs_log, theirs_desc = base.replace("old", "mine"), base.replace("row1", "row1\nrow2"), base.replace("old", "theirs")
merged = merge_note(base, mine, theirs_log)
assert merged.endswith("# T\n\nmine\n\n## Log\n\nrow1\nrow2\n"), merged
assert merge_note(base, mine, theirs_desc) is None                      # both wrote it: nothing guessed
assert merge_note(base, base, theirs_desc).endswith("theirs\n\n## Log\n\nrow1\n")   # only upstream did: upstream's

# -- the writer ----------------------------------------------------------------------------------------------------
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
open(d + "/Projects/Kura.md", "w").write(
    "---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\n  - area/crafts\n"
    "project: kura\nstatus: wip\n---\n\n# Kura\n\nA reader.\n\n## Log\n\n| Date | Category | Change | Details |\n|---|---|---|---|\n"
    "| 2026-09-20 | milestone | v1 | x |\n")
open(d + "/Projects/Other.md", "w").write("---\ntitle: Other\ntags:\n  - type/project\n  - area/projects\n  - area/tools\nstatus: ready\n---\n# Other\n")
subprocess.run(["git", "-C", d, "init", "-q"], check=True)
st = Store(d + "/db/k.db", d)
st.rebuild()
w = Writer(st)

c = w.update("kura", {"description": "New words.\r\n\r\n- one\r\n- two\n=======\n", "title": "  Kura Reader ", "summary": "a\nb"}, "me", "test")
text = open(d + "/Projects/Kura.md").read()
assert lead_of(text) == "New words.\n\n- one\n- two\n =======", repr(lead_of(text))      # CRLF folded; a conflict-looking line indented
assert "## Log" in text and "| 2026-09-20 | milestone | v1 | x |" in text           # the rest of the note is as it was
assert (c["title"], c["summary"]) == ("Kura Reader", "a b")
ev = st.events(card="kura", limit=1)[0]
assert ev["type"] == "edit" and set(ev["changes"]) == {"description", "title", "summary"}, ev
assert w.description(c) == lead_of(text)
for field in ({"title": "  "}, {"description": ["x"]}, {"description": "x" * 20001}, {"outcome": "wontdo"}, {"outcome": "nope"}):
    try:
        w.update("other", field, "me", "test")
        raise SystemExit("accepted %r" % field)
    except WriteError as e:
        assert e.status == 422, (field, e.status)

c = w.update("kura", {"area": "crafts"}, "me", "test")                                # the lane: swap the area/* tag
assert c["area"] == "crafts" and "area/tools" not in c["tags"] and "area/projects" in c["tags"], c["tags"]
assert st.events(card="kura", limit=1)[0]["changes"]["area"] == ["tools", "crafts"]
try:
    w.update("kura", {"area": "brand-new"}, "me", "test", areas=False)                # a new lane is a maintainer's to make
    raise SystemExit("made a lane")
except WriteError as e:
    assert e.status == 403

c = w.update("kura", {"board": "archived", "outcome": "wontdo", "reason": "not  worth\nit"}, "me", "test")
assert c["board"] == "archived" and st.closeout("kura") == {**st.closeout("kura"), "outcome": "wontdo", "reason": "not worth it"}
w.update("kura", {"board": "ready"}, "me", "test")
w.update("kura", {"board": "archived"}, "me", "test")
assert st.closeout("kura")["outcome"] == "", st.closeout("kura")                        # the newest archive decides

n = w.create({"title": "Fresh", "area": "tools", "description": "Why.\n\nMore.", "stream": "Lanterns", "priority": "high",
              "summary": "short"}, "me", "test")
body = open(d + "/" + n["path"]).read()
assert body.endswith("# Fresh\n\nWhy.\n\nMore.\n") and n["stream"] == "Lanterns" and n["priority"] == 1, body
n2 = w.create({"title": "Plain", "area": "tools", "summary": "just a summary"}, "me", "test")
assert open(d + "/" + n2["path"]).read().endswith("# Plain\n\njust a summary\n")       # no description: the summary leads the note

# -- the web forms ---------------------------------------------------------------------------------------------------
SERVER = textwrap.dedent('''
    import sys, threading
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
procs = []


def start():
    root = tempfile.mkdtemp(dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    os.makedirs(root + "/vault/Projects")
    for slug, front in (("alpha", "status: ready\nstream: Lanterns\npriority: high"), ("bravo", "status: wip"), ("charlie", "status: done"),
                        ("delta", "status: ready")):
        title = slug.title()
        open(root + "/vault/Projects/%s.md" % title, "w").write(
            "---\ntitle: %s\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/%s\nproject: %s\n%s\n---\n\n"
            "# %s\n\nOne <script>alert(1)</script> two [[Washi paper|paper]] and [[Elsewhere]].\n\n## Log\n\n"
            "| Date | Category | Change | Details |\n|---|---|---|---|\n| 2026-09-20 | milestone | shipped | x |\n"
            % (title, "tools" if slug != "delta" else "crafts", slug, front, title))
    subprocess.run(["git", "-C", root + "/vault", "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=root + "/vault", KANBAN_DB=root + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", PYTHONDONTWRITEBYTECODE="1")
    for k in ("KANBAN_NIWA_URL", "KANBAN_KURA_URL", "MACHIYA_IDENTITY_FILE", "KANBAN_SIGNIN", "KANBAN_BOARD_URL"):
        env.pop(k, None)
    open(root + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, root + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL,
                            stderr=open(root + "/server.log", "w"))      # a file: an unread pipe fills up and stalls the board
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port, root
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    raise SystemExit("board did not start: " + open(root + "/server.log").read()[-500:])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(port, method, path, headers=None, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method,
                                 headers=dict({"Host": "127.0.0.1:%d" % port}, **(headers or {})))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


try:
    port, root = start()
    form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://127.0.0.1:%d" % port}
    post = lambda path, fields: call(port, "POST", path, form, urlencode(fields).encode())
    card = lambda slug: json.loads(call(port, "GET", "/api/cards/" + slug)[1])
    page = lambda path: call(port, "GET", path)[1]

    # the card page: one editable page, no table repeating the form; the description rendered safely above it
    html = page("/p/alpha")
    for name in ("title", "summary", "description", "stream", "area", "priority", "next", "due", "blocked_by", "dependsOn", "goal", "comment"):
        assert re.search(r'name="%s"' % name, html), name
    assert "<th>Summary</th>" not in html and "<th>Next</th>" not in html and "<th>Due</th>" not in html, "the form is on the page twice"
    assert '<textarea name="description"' in html and "A stream is a project" in html
    desc = html[html.index('<section class="desc nbody">'):html.index("</section>", html.index('<section class="desc nbody">'))]
    assert "<script" not in desc and "alert" not in desc and "[[" not in desc and "two paper and Elsewhere" in desc, desc   # data, never code; [[links]] as plain text
    assert 'name="post"' not in html                                              # Post is for finished cards
    assert 'name="post"' in page("/p/charlie")
    assert card("alpha")["description"].startswith("One <script>alert(1)</script> two"), card("alpha")["description"]

    # saving the description as a browser posts it (CRLF), with the originals; a stale original is refused
    o = {"o_description": card("alpha")["description"].replace("\n", "\r\n")}
    status, _ = post("/p/alpha", dict(o, description="First line\r\n\r\nSecond line"))
    assert status == 302, status
    assert card("alpha")["description"] == "First line\n\nSecond line"
    note = open(root + "/vault/Projects/Alpha.md").read()
    assert "# Alpha\n\nFirst line\n\nSecond line\n\n## Log" in note.replace("\r\n", "\n") and "shipped" in note, note
    status, body = post("/p/alpha", dict(o, description="from an old page"))
    assert status == 409 and "description changed since you opened this page" in body, (status, body[-200:])
    assert card("alpha")["description"] == "First line\n\nSecond line"
    status, body = post("/p/alpha", {"o_description": "First line\n\nSecond line", "description": "## a heading"})
    assert status == 422 and "headings" in body, (status, body[-200:])

    # title and summary edit; the lane changes (an existing one only)
    assert post("/p/bravo", {"o_title": "Bravo", "title": "Bravo Two", "o_summary": "", "summary": "now it has one"})[0] == 302
    assert (card("bravo")["title"], card("bravo")["summary"], card("bravo")["slug"]) == ("Bravo Two", "now it has one", "bravo")
    assert post("/p/bravo", {"o_area": "tools", "area": "crafts"})[0] == 302 and card("bravo")["area"] == "crafts"
    assert post("/p/bravo", {"o_area": "crafts", "area": "no-such-lane"})[0] == 409 and card("bravo")["area"] == "crafts"   # the form never confirms a new tag

    # a new card with details; Capture writes the link and notes into the description
    status, _ = post("/new", {"title": "Made Here", "area": "tools", "summary": "sum", "stream": "Lanterns", "priority": "2",
                              "description": "Why this exists.\r\nSecond line."})
    assert status == 302 and card("made-here")["stream"] == "Lanterns" and card("made-here")["priority"] == 2
    assert card("made-here")["description"] == "Why this exists.\nSecond line."
    assert '<option value="Lanterns">' in page("/") and 'name="description"' in page("/")
    assert post("/share", {"title": "A link", "url": "https://example.org/x", "text": "worth reading", "area": "tools"})[0] == 302
    assert card("a-link")["description"] == "worth reading\n\nhttps://example.org/x"

    # Group By Stream: lanes are the projects
    lanes = re.findall(r'data-lane="([^"]*)"', page("/?group=stream"))
    assert "Lanterns" in lanes and "no stream" in lanes, lanes
    assert ">Stream (Project)<" in page("/") and "Stream (Project)" in page("/settings")

    # closing a card: Archive keeps it as finished work; Won't do records why, and stays out of Posts
    assert "Archive</button>" in page("/p/delta") and "Won&rsquo;t do" in page("/p/delta")
    status, _ = post("/p/charlie", {"board": "archived", "o_board": "done"})
    assert status == 302 and card("charlie")["board"] == "archived"
    status, _ = post("/p/delta", {"board": "archived", "o_board": "ready", "outcome": "wontdo", "reason": "not this year"})
    assert status == 302 and card("delta")["board"] == "archived"
    html = page("/p/delta")
    assert "Won&rsquo;t do: not this year" in html and "Move it back to a column to reopen it" in html and 'class="archiveform"' not in html
    assert "won&rsquo;t do" in page("/archived") and "not this year" in page("/archived")
    ready = page("/posts?show=ready")
    assert "Charlie" in ready and "Delta" not in ready, "Posts: an archived card is a project to write up, a won't do isn't"
    assert 'data-slug="delta"' not in page("/") and 'data-slug="charlie"' not in page("/")           # off the board
    assert post("/p/delta", {"board": "archived", "o_board": "ready", "outcome": "wontdo"})[0] == 409     # it isn't there any more
    assert post("/move", {"slug": "delta", "board": "backlog"})[0] == 302 and card("delta")["board"] == "backlog"   # reopened

    # the API: the same writes (pm and agents)
    api = {"Content-Type": "application/json", "X-Agent": "test"}
    status, body = call(port, "PATCH", "/api/cards/bravo", api, json.dumps({"description": "From the API", "board": "archived",
                                                                          "outcome": "wontdo", "reason": "scope"}).encode())
    assert status == 200 and card("bravo")["description"] == "From the API" and card("bravo")["board"] == "archived", (status, body)
    assert call(port, "PATCH", "/api/cards/alpha", api, json.dumps({"outcome": "wontdo"}).encode())[0] == 422
    print("cardform tests: all passed")
finally:
    for p in procs:
        p.kill()
