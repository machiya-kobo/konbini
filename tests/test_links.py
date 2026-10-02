"""Link checker defaults: no Wayback unless asked, Hister is read-only unless KANBAN_HISTER_SAVE, and the kit's related
notes come out in a fixed order (they were built from sets, so the order and the cut changed per process)."""
import json, os, socket, subprocess, sys, tempfile, textwrap
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import links

# KANBAN_ARCHIVE: none by default; only the exact `wayback` turns the lookup on; anything else is none with a warning
for v in (None, "", " none ", "none"):
    assert links.archive_mode(v) == ("none", ""), v
assert links.archive_mode("wayback") == links.archive_mode(" wayback ") == ("wayback", "")
for v in ("WayBack", "archive.org", "1"):
    mode, warn = links.archive_mode(v)
    assert mode == "none" and "stay off" in warn and repr(v) in warn, (v, mode, warn)

# Hister: the lookup always, the save only with hister_save
class Backend:
    def __init__(self, held=None): self.held, self.saved = held, []
    def lookup(self, url): return self.held
    def save(self, url): self.saved.append(url); return ("http://hister/p", "2026-09-30")
class Store:
    def __init__(self): self.fields = {}
    def link_set(self, url, **f): self.fields.update(f)
rec = {"url": "https://example.org/a", "status": "live"}
for flag, calls in ((False, []), (True, ["https://example.org/a"])):
    b, st = Backend(), Store()
    out = links.Links(st, None, hister=b, hister_save=flag).private_copy(rec)
    assert b.saved == calls and (out is not None) == flag, (flag, b.saved, out)
b, st = Backend(("http://hister/copy", "2026-09-01")), Store()          # a copy Hister already holds is shown either way
assert links.Links(st, None, hister=b).private_copy(rec) == "http://hister/copy" and b.saved == [] and st.fields["private_backend"] == "hister"
assert links.Links(Store(), None).hister_save is False
# KANBAN_HISTER_SAVE parsing: off unless 1, on or true
assert [links.setting_on(v) for v in (None, "", "0", "off", "no", "yes", "1", "on", "true", " TRUE ")] == [False] * 6 + [True] * 4
assert 'links_mod.setting_on(os.environ.get("KANBAN_HISTER_SAVE"))' in open(os.path.join(APP, "app.py")).read()

# commit subjects left out of the calendar and kits: built in `board: ` and merges, plus comma-separated prefixes from the settings
import store
os.environ.pop("KANBAN_SKIP_COMMITS", None); os.environ.pop("KANBAN_CALENDAR_SKIP_COMMITS", None)
f = store.commit_filter("KANBAN_SKIP_COMMITS", "KANBAN_CALENDAR_SKIP_COMMITS")
assert f.match("board: 1 change") and f.match("Merge branch x") and not f.match("nightly backup") and not f.match("wip(a): b")
os.environ["KANBAN_SKIP_COMMITS"] = "Nightly Backup, chore "
os.environ["KANBAN_CALENDAR_SKIP_COMMITS"] = "wip(,docs("
f = store.commit_filter("KANBAN_SKIP_COMMITS", "KANBAN_CALENDAR_SKIP_COMMITS")
assert f.match("nightly backup 2026") and f.match("Chore: tidy") and f.match("wip(a): b") and f.match("docs(x)") and not f.match("fix: wip")
assert not store.commit_filter("KANBAN_SKIP_COMMITS").match("wip(a): b")          # the calendar-only setting stays out of the kits

# a blog's categories and tags the kit ignores (kit.json): the most common category wins unless ignored
from blog import Blog
b = tempfile.mkdtemp(); os.makedirs(b + "/_posts/2026")
for i, cat in enumerate(("imported", "imported", "tech")):
    open("%s/_posts/2026/2026-01-0%d-post.md" % (b, i + 1), "w").write("---\ntitle: P%d\ncategory: %s\ntags: shell\n---\nbody\n" % (i, cat))
blog = Blog(b, "https://blog.example")
assert blog.category_for(["shell"]) == "imported" and blog.category_for(["shell"], ["imported"]) == "tech"
# a post's address: KANBAN_BLOG_URL + KANBAN_BLOG_PERMALINK ({year}, {slug}); default /{year}/{slug}/; a bad pattern falls back
assert {p.url for p in blog.posts()} == {"https://blog.example/2026/post/"}
assert {p.url for p in Blog(b, "https://blog.example/", "/writing/{year}/{slug}.html").posts()} == {"https://blog.example/writing/2026/post.html"}
assert {p.url for p in Blog(b, "https://blog.example", "/{nope}/").posts()} == {"https://blog.example/2026/post/"}

# the kit's related notes: the same under different hash seeds, in sorted order
HARNESS = textwrap.dedent('''
    import json, sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    kit = app.kits.build(app.store.card("main"))
    print("RESULT " + json.dumps([r["rel"] for r in kit["related"]]))
''')
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
names = ["Zulu", "Alpha", "Mike", "Echo", "Kilo", "Bravo", "Hotel", "Delta", "Lima", "Gamma", "Oscar", "Juliet", "Papa", "India", "Quebec", "Foxtrot"]
body = " ".join("[[%s]]" % n for n in names)
open(d + "/Projects/Main.md", "w").write("---\ntitle: Main\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\nproject: main\nstatus: wip\n---\n# Main\n\n" + body + "\n")
for n in names:
    open("%s/%s.md" % (d, n), "w").write("---\ntitle: %s\ncreated: 2026-09-01\ntags:\n  - type/reference\n  - area/tools\n---\n# %s\n" % (n, n))
h = os.path.join(d, "harness.py"); open(h, "w").write(HARNESS)
seen = []
for seed in ("1", "2", "3"):
    env = dict(os.environ, KANBAN_REPO=d, KANBAN_DB="%s/db%s/k.db" % (d, seed), KANBAN_AUTH="open", KANBAN_BIND="127.0.0.1",
               KANBAN_TAILNET_PORT="0", PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, h, APP], env=env, capture_output=True, text=True, timeout=120)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RESULT ")]
    assert lines, (r.stdout[-400:], r.stderr[-600:])
    seen.append(json.loads(lines[-1][7:]))
assert seen[0] == seen[1] == seen[2], seen
assert seen[0] == sorted(seen[0]) and len(seen[0]) == 14 and seen[0][0] == "Alpha.md", seen[0]
print("links tests: all passed")
