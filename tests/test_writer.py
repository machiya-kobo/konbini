import os, sys, tempfile, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from store import Store
from writer import Writer, WriteError
today = datetime.date.today().isoformat()
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
# A note that still carries the old names: they are not read (the note isn't a card) and it is reported.
OLD = """---
title: Old One
date: 2026-01-02
tags:
  - type/project
  - area/projects
  - area/tools
  - status/draft
project: old-one
board: backlog
priority: 2
blocked_by: ""
---
# Old One
"""
NEW = """---
title: New One
created: 2026-02-03
tags:
  - type/project
  - area/projects
  - area/tools
project: new-one
status: backlog
priority: normal
waiting: the review
dependsOn:
  - "[[Old One]]"
  - "[[Projects/Other|other]]"
stream: "[[Machiya]]"
goal: Ship it
due: 2026-12-01
---
# New One
"""
open(d + "/Projects/Old One.md", "w").write(OLD)
open(d + "/Projects/New One.md", "w").write(NEW)
st = Store(d + "/db/k.db", d); st.rebuild = st.rebuild  # no git: rebuild uses git rev-parse, ok to fail
cards = {c["slug"]: c for c in st.scan()}
THIRD = NEW.replace("New One", "Third One").replace("new-one", "third-one").replace("status: backlog", "status: ready").replace(
    "waiting: the review\n", "")
open(d + "/Projects/Third One.md", "w").write(THIRD)
cards = {c["slug"]: c for c in st.scan()}
for c in cards.values(): st.upsert(c)
n = cards["new-one"]
assert n["board"] == "backlog" and n["priority"] == 2 and n["blocked_by"] == "the review" == n["waiting"], n
assert n["dependsOn"] == ["Old One", "Projects/Other"] and n["stream"] == "Machiya" and n["goal"] == "Ship it", n
assert n["due"] == "2026-12-01" and n["created"] == "2026-02-03" and n["status"] == "draft", n
# board: is not read, so Old One is not a card; it carries type/project, so the board lists it as Unsorted
assert "old-one" in cards and cards["old-one"]["board"] is None and cards["old-one"]["priority"] is None, cards.get("old-one")
assert cards["old-one"]["created"] == "" and cards["old-one"]["blocked_by"] == "", cards["old-one"]
assert st.legacy == [{"slug": "old-one", "path": "Projects/Old One.md",
                      "field": "board, blocked_by, date, priority, status/*"}], st.legacy
assert not any(x["path"] != "Projects/Old One.md" for x in st.legacy)

w = Writer(st)
def fm(name): return open(d + "/Projects/%s.md" % name).read().split("---")[1]
# move to wip: status:, started set; to done: completedDate; back to ready: removed; no status/* tags appear
w.update("third-one", {"board": "wip", "priority": "high"}, "me", "test")
t = fm("Third One"); assert "status: wip" in t and "status/" not in t and "board:" not in t, t
assert "started: " + today in t and "priority: high" in t, t
w.update("third-one", {"board": "done"}, "me", "test"); assert "completedDate: " + today in fm("Third One")
w.update("third-one", {"board": "ready"}, "me", "test"); assert "completedDate" not in fm("Third One")
# status: written, no tags touched, waiting kept as waiting, priority as a word
w.update("new-one", {"status": "blocked", "waiting": "a person", "priority": 3}, "me", "test")
t = fm("New One"); assert "status: blocked" in t and "board:" not in t and "status/" not in t, t
assert "waiting: a person" in t and "blocked_by" not in t and "priority: low" in t, t
# leaving blocked clears waiting
w.update("new-one", {"board": "wip"}, "me", "test")
t = fm("New One"); assert "status: wip" in t and "waiting" not in t and "started: " + today in t, t
c = st.card("new-one"); assert c["board"] == "wip" and c["blocked_by"] == "" and c["dependsOn"] == ["Old One", "Projects/Other"], c
# bad priority word
try: w.update("new-one", {"priority": "urgent"}, "me", "test"); raise SystemExit("no error")
except WriteError as e: assert e.status == 422
# events keep the old keys
evs = st.events(card="new-one"); assert any("board" in (e.get("changes") or {}) for e in evs), evs
# create writes the new schema
st.known_tags = lambda: {"area/projects", "area/tools"}
c = w.create({"title": "Fresh Card", "area": "tools", "board": "wip", "priority": "high", "summary": "s"}, "me", "test")
t = fm("Fresh Card")
assert "status: wip" in t and "created: " + today in t and "priority: high" in t and "started: " + today in t, t
assert "board:" not in t and "status/" not in t and "\ndate:" not in t, t
assert c["board"] == "wip" and c["priority"] == 1 and c["created"] == today, c
w.update(c["slug"], {"board": "done"}, "me", "test"); t = fm("Fresh Card")
assert "status: done" in t and "completedDate: " + today in t and "status/" not in t, t
# inputs: board / blocked_by / status / waiting are all accepted, only the new names are written
w.update("third-one", {"board": "blocked", "blocked_by": "x"}, "me", "test")
t = fm("Third One"); assert "status: blocked" in t and "waiting: x" in t and "board:" not in t and "blocked_by" not in t, t
w.update("third-one", {"status": "ready", "priority": "2"}, "me", "test")
t = fm("Third One"); assert "status: ready" in t and "waiting" not in t and "priority: normal" in t, t
c = st.card("third-one"); assert c["board"] == "ready" and c["priority"] == 2, c
# a status/* tag is not the board's: a move leaves the tags alone, and adding one is an ordinary (unknown) tag
w.update("third-one", {"board": "wip"}, "me", "test"); assert "status/" not in fm("Third One")
try: w.update("third-one", {"tags_add": ["status/active"]}, "me", "test"); raise SystemExit("no error")
except WriteError as e: assert e.status == 409 and e.extra.get("code") == "unknown_tag", (e.status, e.extra)
# merge_note: a move takes the board's status, tags follow upstream
from writer import merge_note
base = "---\ntitle: M\ntags:\n  - type/project\nstatus: backlog\npriority: normal\n---\nbody\n"
ours = base.replace("status: backlog", "status: wip")
theirs = base.replace("tags:\n  - type/project", "tags:\n  - type/project\n  - topic/x").replace("body", "body2")
m = merge_note(base, ours, theirs)
assert m and "status: wip" in m and "topic/x" in m and "body2" in m and "status/" not in m, m
print("writer tests: all passed")
