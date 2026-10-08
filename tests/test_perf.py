"""The speed-ups don't change what they speed up: the importer's cache of unchanged notes (and its fresh scan), the
timeline's notes (the same ones, in the same order, as vaultkit's read_notes), the per-note commit lists from one
git log, the review asking for events only where it needs them, and the events index."""
import contextlib, io, os, subprocess, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "app"))
tmp = tempfile.mkdtemp(prefix="konbini-perf-")
subprocess.run([os.path.join(ROOT, "tools", "demo-vault"), tmp + "/vault"], check=True, capture_output=True)
os.environ["KANBAN_REPO_SUBDIR"] = "personal"
import review, timeline as tl
from store import Store, VAULT
from vaultkit.notes import read_notes

store = Store(tmp + "/k.sqlite3", tmp + "/vault")
log = io.StringIO()
with contextlib.redirect_stdout(log):
    first = store.scan()
    again = store.scan()                                   # every note from the cache
    fresh = store.scan(fresh=True)                         # every note read again
assert first == again == fresh and len(first) == 10, len(first)
assert store.all_tags and store.scan(fresh=True) == first

# a changed note is read again, a new one found, a deleted one gone, whatever the cache holds
note = os.path.join(tmp, "vault", VAULT, "Projects", "Lantern.md")
text = open(note).read()
with contextlib.redirect_stdout(log):
    open(note, "w").write(text.replace("status: wip", "status: blocked"))
    assert {c["slug"]: c["board"] for c in store.scan()}["lantern"] == "blocked"
    open(os.path.join(tmp, "vault", VAULT, "Projects", "New one.md"), "w").write("---\nstatus: ready\n---\n# New one\n")
    assert "new-one" in {c["slug"] for c in store.scan()}
    os.remove(os.path.join(tmp, "vault", VAULT, "Projects", "New one.md"))
    assert "new-one" not in {c["slug"] for c in store.scan()} and "New one.md" not in " ".join(store._parsed)
    open(note, "w").write(text)

# the timeline's notes are vaultkit's read_notes: the same notes in the same order, parsed once for both readers
t = tl.Timeline(store)
root = os.path.join(tmp, "vault", VAULT)
mine, theirs = t.read_changed(root), read_notes(root)
assert [(r, f, x) for r, f, x in mine] == [(r, f, x) for r, f, x in theirs], "timeline notes differ from read_notes"
assert t.read_changed(root) == mine and all(p in store._parsed for p in [os.path.join(root, r) for r, _, _ in mine])

# the commits of every note from one git log are what a git log per note says
from kit import Kits, SKIP_COMMIT_RE
open(note, "a").write("\nA later line.\n")
subprocess.run(["git", "-C", tmp + "/vault", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-am", "edit"],
               check=True, capture_output=True)
store.rebuild()
kits = Kits(store, None, t, None, "http://x")
by_note = kits.vault_log()
assert by_note, "no commits found"
for rel, commits in by_note.items():
    one = subprocess.run(["git", "-C", tmp + "/vault", "log", "--format=%as\x1f%s", "--", os.path.join(VAULT, rel)],
                         capture_output=True, text=True).stdout.splitlines()
    assert [tuple(l.split("\x1f", 1)) for l in one] == commits, rel

# the review asks for a card's events only when it is blocked or done
asked = []
cards = [{"slug": s, "title": s, "board": b, "area": "ops", "priority": None, "rank": None, "next": "x", "updated": "2026-09-30",
          "created": "2026-09-01", "waiting": "", "blocked_by": "", "completedDate": ""} for s, b in
         (("a", "wip"), ("b", "ready"), ("c", "blocked"), ("d", "done"), ("e", "backlog"))]
import datetime
review.build(cards, lambda s: asked.append(s) or [], {}, limits={}, today=datetime.date(2026, 10, 1))
assert sorted(asked) == ["c", "d"], asked

# the events table has the indexes the per-card queries use
store.add_event({"ts": "2026-10-01T00:00:00", "card": "lantern", "type": "note", "actor": "t", "client_id": "abc"})
plan = " ".join(r[3] for r in store.db.execute("EXPLAIN QUERY PLAN SELECT data FROM events WHERE card = ? ORDER BY ts DESC, id DESC LIMIT 9", ("lantern",)))
assert "events_card_ts" in plan, plan
plan = " ".join(r[3] for r in store.db.execute("EXPLAIN QUERY PLAN SELECT data FROM events WHERE json_extract(data, '$.client_id') = ?", ("abc",)))
assert "events_client" in plan, plan
assert store.event_by_client("abc")["card"] == "lantern" and store.count() == 10
print("perf tests: all passed")
