"""A card's repos (the Machiya frontmatter schema): `repos:` (a list, or names separated by commas) when present, else
`repo:` as a one-entry list; a URL counts as its last segment with `.git` dropped; names compare without regard to case.
Writing them (0.31): PATCH `repos` (the Konbini API contract), the line edit it makes, and the card page's repo chips."""
import json, os, re, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request
from urllib.parse import urlencode
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from store import Store, parse_note, repo_name, repos_of  # noqa: E402
from writer import Writer, WriteError, merge_note, repo_list  # noqa: E402

assert repos_of({"repos": ["Techo", "workshop", "techo", "https://example.com/u/dotfiles.git"]}) == ["Techo", "workshop", "dotfiles"]
assert repos_of({"repos": "techo, workshop ,", "repo": "ignored"}) == ["techo", "workshop"]
assert repos_of({"repo": "git@example.com:user/flynn.git"}) == ["flynn"]
assert repos_of({"repo": "https://git.example.com/user/old-thing/"}) == ["old-thing"]
assert repos_of({"repos": [], "repo": "kept"}) == ["kept"] and repos_of({}) == [] and repos_of({"repo": "a b"}) == []

assert repo_name("https://example.com/u/Kura.git/") == "Kura" and repo_name("") == "" and repo_name(None) == ""
assert repo_name("x" * 100) and not repo_name("x" * 101)

note = "---\ntitle: Workshop\nstatus: wip\nrepo: https://example.com/u/techo\nrepos:\n  - techo\n  - workshop\n  - dotfiles\n---\n# W\n"
card = parse_note(note, "Projects/Workshop.md")
assert card["repos"] == ["techo", "workshop", "dotfiles"] and card["repo"] == "https://example.com/u/techo", card
assert parse_note("---\ntitle: A\nstatus: wip\nrepo: https://example.com/u/a.git\n---\n", "Projects/A.md")["repos"] == ["a"]
assert parse_note("---\ntitle: B\nstatus: wip\n---\n", "Projects/B.md")["repos"] == []

# -- the names a write accepts ---------------------------------------------------------------------------------------
assert repo_list(["Techo", "workshop", "techo", "https://example.com/u/dotfiles.git"]) == ["Techo", "workshop", "dotfiles"]
assert repo_list(" techo, Workshop ,, TECHO,") == ["techo", "Workshop"] and repo_list("") == [] and repo_list([]) == []
assert repo_list(None) == [] and repo_list(["git@example.com:u/flynn.git"]) == ["flynn"]
for bad in (["a b"], "ok, not ok", ["x" * 101], [1], {"a": 1}, 7, ["ok", ["nested"]], [".."], ["u/."], ["b@d"]):
    try:
        repo_list(bad)
        raise SystemExit("accepted %r" % (bad,))
    except WriteError as err:
        assert err.status == 422, (bad, err.status)
try:
    repo_list(["r%d" % i for i in range(51)])
    raise SystemExit("accepted 51 repos")
except WriteError as err:
    assert err.status == 422
try:
    repo_list(["fine", "has space", "also bad!"])
except WriteError as err:
    assert err.extra["repos"] == ["has space", "also bad!"], err.extra

# -- the writer: a line edit of repos:, the legacy repo: gone in the same write, an event --------------------------
d = tempfile.mkdtemp(dir="/var/tmp" if os.path.isdir("/var/tmp") else None); os.makedirs(d + "/Projects")
LEGACY = ("---\ntitle: Kura\n# a comment the board keeps\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n"
          "repo: https://example.com/u/kura.git\nstatus: wip\nnext: 'ship it: soon'\nweird:   spacing\n---\n\n# Kura\n\nA reader.\n\n"
          "## Log\n\n| Date | Category | Change | Details |\n|---|---|---|---|\n| 2026-09-20 | milestone | v1 | x |\n")
open(d + "/Projects/Kura.md", "w").write(LEGACY)
open(d + "/Projects/Niwa.md", "w").write("---\ntitle: Niwa\ntags:\n  - type/project\nstatus: ready\nrepos: niwa, garden\n---\n# Niwa\n")
open(d + "/Projects/Plain.md", "w").write("---\ntitle: Plain\ntags:\n  - type/project\nstatus: ready\n---\n# Plain\n")
subprocess.run(["git", "-C", d, "init", "-q"], check=True)
st = Store(d + "/db/k.db", d)
st.rebuild()
w = Writer(st)
assert st.card("kura")["repos"] == ["kura"]

c = w.update("kura", {"repos": "Kura, vaultkit, KURA, 1.0, yes"}, "me", "agent-x")
text = open(d + "/Projects/Kura.md").read()
assert c["repos"] == ["Kura", "vaultkit", "1.0", "yes"] and c["repo"] == "", c
assert "repo:" not in text and "\nrepos:\n  - Kura\n  - vaultkit\n  - \"1.0\"\n  - \"yes\"\n" in text, text   # plain names, quoted when YAML would read them as something else
# every other line is as it was, in its place: only repo: went and repos: + updated: came
before = [l for l in LEGACY.split("\n") if not l.startswith("repo:")]
after = [l for l in text.split("\n") if not l.startswith(("repos:", "  - Kura", "  - vaultkit", '  - "1.0"', '  - "yes"', "updated:"))]
assert before == after, (before, after)
ev = st.events(card="kura", limit=1)[0]
assert ev["type"] == "edit" and ev["changes"] == {"repos": [["kura"], ["Kura", "vaultkit", "1.0", "yes"]]}, ev
assert (ev["actor"], ev["agent"]) == ("me", "agent-x"), ev
n = len(st.events(card="kura", limit=100))
w.update("kura", {"repos": ["Kura", "vaultkit", "1.0", "yes"]}, "me", "agent-x")               # the same list again: no write, no event
assert open(d + "/Projects/Kura.md").read() == text and len(st.events(card="kura", limit=100)) == n
c = w.update("kura", {"repos": ["vaultkit"]}, "me", "agent-x")
assert c["repos"] == ["vaultkit"] and "\nrepos:\n  - vaultkit\n" in open(d + "/Projects/Kura.md").read()
c = w.update("kura", {"repos": []}, "me", "agent-x")                                          # [] removes it
assert c["repos"] == [] and "repos" not in open(d + "/Projects/Kura.md").read()
assert st.events(card="kura", limit=1)[0]["changes"] == {"repos": [["vaultkit"], []]}
assert w.update("kura", {"repos": ""}, "me", "agent-x")["repos"] == [] and len(st.events(card="kura", limit=100)) == n + 2

# "" removes both repos: and a legacy repo:
open(d + "/Projects/Both.md", "w").write("---\ntitle: Both\ntags:\n  - type/project\nstatus: ready\nrepo: old\nrepos:\n  - new\n---\n# B\n")
st.rebuild()
c = w.update("both", {"repos": ""}, "me", "agent-x")
assert c["repos"] == [] and "repo" not in open(d + "/Projects/Both.md").read()
# confirming the mapping repo: gave moves it to repos: (a write, logged), keeping the name as written
open(d + "/Projects/Conf.md", "w").write("---\ntitle: Conf\ntags:\n  - type/project\nstatus: ready\nrepo: git@example.com:u/Conf.git\n---\n# C\n")
st.rebuild()
c = w.update("conf", {"repos": st.card("conf")["repos"]}, "me", "agent-x")
assert c["repos"] == ["Conf"] and "repo:" not in open(d + "/Projects/Conf.md").read() and "repos:\n  - Conf\n" in open(d + "/Projects/Conf.md").read()
assert st.events(card="conf", limit=1)[0]["changes"] == {"repos": [["Conf"], ["Conf"]]}
# a string repos: becomes the block list
c = w.update("niwa", {"repos": ["niwa", "garden"]}, "me", "agent-x")
assert "repos:\n  - niwa\n  - garden\n" in open(d + "/Projects/Niwa.md").read() and "repos: niwa" not in open(d + "/Projects/Niwa.md").read()
# a bad name refuses the whole write
plain = open(d + "/Projects/Plain.md").read()
try:
    w.update("plain", {"repos": ["good", "b@d"], "next": "x"}, "me", "agent-x")
    raise SystemExit("accepted a bad repo")
except WriteError as err:
    assert err.status == 422 and err.extra["repos"] == ["b@d"]
assert open(d + "/Projects/Plain.md").read() == plain
# the merge after a pull knows repos: is a list the board writes, and drops repo: when the board did
base = "---\ntitle: T\nstatus: wip\nrepo: a\n---\n# T\n\nx\n\n## Log\n"
ours = "---\ntitle: T\nstatus: wip\nrepos:\n  - a\n  - b\n---\n# T\n\nx\n\n## Log\n"
merged = merge_note(base, ours, base.replace("## Log\n", "## Log\n\nrow\n"))
assert merged and "repos:\n  - a\n  - b\n" in merged and "repo: a" not in merged and merged.endswith("row\n"), merged

# Confirm shows only when the chips are what repo: gave (not when a repos: line beside it wins)
import modern  # noqa: E402
assert 'class="repoconfirm"' in modern.repos_form({"slug": "x", "repo": "https://example.com/u/Old.git", "repos": ["Old"]})
assert 'class="repoconfirm"' not in modern.repos_form({"slug": "x", "repo": "old", "repos": ["new"]})
assert 'class="repoconfirm"' not in modern.repos_form({"slug": "x", "repo": "", "repos": ["new"]})
assert 'class="repoconfirm"' not in modern.repos_form({"slug": "x", "repo": "a b", "repos": []})
assert '<span class="chip repo">&lt;b&gt;</span>' in modern.repos_form({"slug": "x", "repo": "", "repos": ["<b>"]})   # escaped

# -- the API and the card page ----------------------------------------------------------------------------------------
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
root = tempfile.mkdtemp(dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
os.makedirs(root + "/vault/Projects")
for slug, front in (("alpha", "repo: https://example.com/u/alpha.git"), ("bravo", "repos:\n  - bravo\n  - shared"), ("charlie", ""),
                    ("delta", "repo: git@example.com:u/delta.git")):
    open(root + "/vault/Projects/%s.md" % slug.title(), "w").write(
        "---\ntitle: %s\ntags:\n  - type/project\n  - area/projects\nstatus: wip\n%s\n---\n\n# %s\n\nWords.\n"
        % (slug.title(), front, slug.title()))
subprocess.run(["git", "-C", root + "/vault", "init", "-q"], check=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=root + "/vault", KANBAN_DB=root + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
           KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", PYTHONDONTWRITEBYTECODE="1")
for k in ("KANBAN_NIWA_URL", "KANBAN_KURA_URL", "MACHIYA_IDENTITY_FILE", "KANBAN_SIGNIN", "KANBAN_BOARD_URL"):
    env.pop(k, None)
open(root + "/server.py", "w").write(SERVER)
proc = subprocess.Popen([sys.executable, root + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL,
                        stderr=open(root + "/server.log", "w"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(method, path, headers=None, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method,
                                 headers=dict({"Host": "127.0.0.1:%d" % port}, **(headers or {})))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


try:
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            if proc.poll() is not None:
                raise SystemExit("board did not start: " + open(root + "/server.log").read()[-500:])
            time.sleep(0.05)
    api = {"Content-Type": "application/json", "X-Agent": "test-agent"}
    patch = lambda slug, body: call("PATCH", "/api/cards/" + slug, api, json.dumps(body).encode())
    rows = lambda: {c["slug"]: c for c in json.loads(call("GET", "/api/cards")[1])["cards"]}
    note = lambda slug: open(root + "/vault/Projects/%s.md" % slug.title()).read()

    assert rows()["alpha"]["repos"] == ["alpha"]
    status, body = patch("alpha", {"repos": ["alpha", "Alpha", "https://example.com/u/vaultkit.git"]})
    assert status == 200 and json.loads(body)["repos"] == ["alpha", "vaultkit"], (status, body)
    assert "repo:" not in note("alpha") and "repos:\n  - alpha\n  - vaultkit\n" in note("alpha")
    assert rows()["alpha"]["repos"] == ["alpha", "vaultkit"] and rows()["alpha"]["repo"] == ""      # /api/cards after a write
    status, body = patch("charlie", {"repos": "techo, workshop"})                                    # the string form
    assert status == 200 and rows()["charlie"]["repos"] == ["techo", "workshop"], body
    status, body = patch("charlie", {"repos": ["fine", "not fine"]})
    assert status == 422 and json.loads(body)["repos"] == ["not fine"], (status, body)
    assert patch("charlie", {"repos": 5})[0] == 422 and rows()["charlie"]["repos"] == ["techo", "workshop"]
    assert patch("charlie", {"repos": []})[0] == 200 and rows()["charlie"]["repos"] == [] and "repos" not in note("charlie")
    evs = [x for x in json.loads(call("GET", "/api/events")[1])["events"] if x.get("card") == "charlie"]
    assert [x["changes"]["repos"] for x in evs if x["type"] == "edit"][-2:] in ([[[], ["techo", "workshop"]], [["techo", "workshop"], []]],
                                                                                 [[["techo", "workshop"], []], [[], ["techo", "workshop"]]]), evs
    assert all(x["agent"] == "test-agent" for x in evs if x["type"] == "edit"), evs

    # the card page: chips with a remove each, an add box, Confirm only for a mapping from repo:
    form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://127.0.0.1:%d" % port}
    post = lambda path, fields: call("POST", path, form, urlencode(fields).encode())
    html = call("GET", "/p/delta")[1]
    sec = html[html.index('<section class="tagsec repos">'):]
    sec = sec[:sec.index("</section>")]
    assert '<h3 class="sechead">Repos</h3>' in sec and '<span class="chip repo">delta</span>' in sec, sec
    assert 'action="/p/delta/repos"' in sec and 'name="remove" value="delta"' in sec and 'name="add"' in sec
    assert 'class="repoconfirm"' in sec and "Confirm" in sec and "Commits in these repos show on Now." in sec
    assert "<script" not in sec and " on" not in re.sub(r'"[^"]*"', '""', sec).replace(" on Now", "")       # the CSP: no inline handlers
    assert 'class="repoconfirm"' not in call("GET", "/p/bravo")[1]                                       # repos: is already confirmed
    assert post("/p/delta/repos", {})[0] == 302                                                           # Confirm
    assert "repo:" not in note("delta") and "repos:\n  - delta\n" in note("delta") and rows()["delta"]["repos"] == ["delta"]
    assert 'class="repoconfirm"' not in call("GET", "/p/delta")[1]
    assert post("/p/delta/repos", {"add": "techo  workshop,https://example.com/u/DELTA.git"})[0] == 302    # add: spaces or commas
    assert rows()["delta"]["repos"] == ["delta", "techo", "workshop"]
    assert post("/p/delta/repos", {"remove": "TECHO"})[0] == 302 and rows()["delta"]["repos"] == ["delta", "workshop"]
    status, body = post("/p/delta/repos", {"add": "b@d"})
    assert status == 422 and rows()["delta"]["repos"] == ["delta", "workshop"], (status, body[:300])
    assert call("POST", "/p/delta/repos", {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"},
                urlencode({"remove": "delta"}).encode())[0] == 403                                         # same-origin only
    assert post("/p/nosuch/repos", {"add": "x"})[0] == 404
    html = call("GET", "/p/charlie")[1]
    assert '<span class="chip repo">' not in html and 'name="add" placeholder="name or URL"' in html   # none yet: just the box
    print("repos tests: all passed")
finally:
    proc.kill()
