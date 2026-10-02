import datetime, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import goals
from store import Store
from timeline import Timeline
from writer import Writer, WriteError

T = datetime.date(2026, 10, 1)
def card(slug, board, goal="", due="", **kw):
    c = {"slug": slug, "title": slug.title(), "board": board, "goal": goal, "due": due, "area": "tools", "stream": ""}
    c.update(kw); return c
cards = [card("a", "done", "Ship v1", "2026-10-05"), card("b", "wip", "Ship v1", "2026-10-20"),
         card("c", "ready", "Ship v1"), card("d", "wip", "Old goal", "2026-09-01"), card("e", "done", "Finished", "2026-09-10"),
         card("f", "backlog", "", "2026-10-03"), card("g", "archived", "Ship v1", "2026-12-01")]
g = {x["name"]: x for x in goals.build(cards, today=T)}
assert (g["Ship v1"]["done"], g["Ship v1"]["total"], g["Ship v1"]["target"]) == (1, 3, datetime.date(2026, 10, 20)), g["Ship v1"]
assert g["Ship v1"]["state"] == "open" and g["Old goal"]["state"] == "overdue" and g["Finished"]["state"] == "done"
assert [x["name"] for x in goals.build(cards, today=T)][0] == "Old goal"          # soonest (overdue) target first
assert goals.due_state(cards[5], T) == "soon" and goals.due_state(cards[3], T) == "overdue" and goals.due_state(cards[0], T) is None
assert [c["slug"] for c in goals.due_soon(cards, T)] == ["d", "f"], goals.due_soon(cards, T)

# writer: goal as a scalar, due validated
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
open(d + "/Projects/Kura.md", "w").write(
    "---\ntitle: Kura\ncreated: 2026-09-01\nstarted: 2026-09-10\ntags:\n  - type/project\n  - area/projects\n  - area/tools\n"
    "project: kura\nstatus: wip\nstream: Machiya\n---\n# Kura\n\n## Log\n\n| Date | Category | Change | Details |\n|---|---|---|---|\n"
    "| 2026-09-20 | milestone | v1 live | first release |\n| 2026-09-12 | start | started | |\n")
st = Store(d + "/db/k.db", d)
for c in st.scan():
    st.upsert(c)
w = Writer(st)
fm = lambda: open(d + "/Projects/Kura.md").read().split("---")[1]
w.update("kura", {"goal": "Ship v1", "due": "2026-10-20"}, "me", "test")
assert "goal: Ship v1" in fm() and "due: 2026-10-20" in fm(), fm()
assert st.card("kura")["due"] == "2026-10-20" and st.card("kura")["goal"] == "Ship v1"
try:
    w.update("kura", {"due": "next week"}, "me", "test"); raise SystemExit("no error")
except WriteError as e:
    assert e.status == 422
w.update("kura", {"due": ""}, "me", "test"); assert "due:" not in fm()

# timeline: the span from started, a Log milestone (not the start row), grouped by stream
tl = Timeline(st)
data = tl.range(datetime.date(2026, 9, 1), datetime.date(2026, 11, 1), st.cards(), group="stream")
(name, rows), = data["groups"]
assert name == "Machiya" and rows[0]["start"] == datetime.date(2026, 9, 10) and rows[0]["end"] is None, data
assert rows[0]["milestones"] == [(datetime.date(2026, 9, 20), "v1 live")], rows[0]["milestones"]
assert tl.range(datetime.date(2026, 1, 1), datetime.date(2026, 3, 1), st.cards())["groups"] == []
print("goals tests: all passed")
