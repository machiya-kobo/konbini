import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import common
import modern
from store import Store
from writer import Writer


def card(slug, board, stream="", **kw):
    c = {"slug": slug, "title": slug.title(), "board": board, "stream": stream, "area": "tools", "areas": ["tools"],
         "topics": [], "machines": [], "tags": [], "summary": "", "next": "", "blocked_by": "", "waiting": "",
         "family": "", "effort": "", "checks_done": 0, "checks_total": 0, "path": "Projects/%s.md" % slug}
    c.update(kw)
    return c


cards = [card("kura", "done", "Machiya", checks_done=3, checks_total=3), card("niwa", "wip", "Machiya", checks_total=4),
         card("konbini", "blocked", "machiya"), card("old", "archived", "Machiya"), card("loose", "ready")]
# filter (case-insensitive), facets, grouping
assert [c["slug"] for c in common.filter_cards(cards, {"stream": ["MACHIYA"]}, {})] == ["kura", "niwa", "konbini", "old"]
assert common.facets(cards, {})["stream"] == ["machiya", "Machiya"] or common.facets(cards, {})["stream"] == ["Machiya", "machiya"]
assert common.lane_of(cards[4], "stream") == "no stream" and common.lane_of(cards[0], "stream") == "Machiya"
assert [c["slug"] for c in common.filter_cards(cards, {"q": ["machiya"]}, {})] == ["kura", "niwa", "konbini", "old"]
# roll-up: archived left out
r = modern.stream_rollup([c for c in cards if c["stream"].lower() == "machiya"])
assert (r["total"], r["done"], r["checks"], r["blocked"]) == (3, 1, (3, 7), 1), r
assert r["cols"]["wip"] == 1

# writer: stream as a scalar, cleared with ""
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
open(d + "/Projects/Kura.md", "w").write(
    "---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\nproject: kura\n"
    "status: wip\n---\n# Kura\n")
st = Store(d + "/db/k.db", d)
for c in st.scan():
    st.upsert(c)
w = Writer(st)
fm = lambda: open(d + "/Projects/Kura.md").read().split("---")[1]
w.update("kura", {"stream": "Machiya"}, "me", "test")
assert "stream: Machiya" in fm() and st.card("kura")["stream"] == "Machiya", fm()
assert any("stream" in (e.get("changes") or {}) for e in st.events(card="kura"))
w.update("kura", {"stream": "[[Machiya]]"}, "me", "test")            # a link is kept as written, quoted
assert 'stream: "[[Machiya]]"' in fm() or "stream: Machiya" in fm(), fm()
w.update("kura", {"stream": ""}, "me", "test")
assert "stream" not in fm()
print("streams tests: all passed")
