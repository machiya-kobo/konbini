import os, sys, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import review
T = datetime.date(2026, 10, 1)            # a Thursday; the week starts Mon 2026-09-28
def card(slug, board, area="ops", **kw):
    c = {"slug": slug, "title": slug, "board": board, "area": area, "priority": None, "rank": None, "next": "do it",
         "updated": "2026-09-30", "created": "2026-09-01", "waiting": "", "blocked_by": "", "completedDate": ""}
    c.update(kw); return c
cards = [card("w%d" % i, "wip") for i in range(4)] + [card("s1", "wip", area="tools", next="", updated="2026-09-01"),
         card("b1", "blocked", area="tools"), card("b2", "ready", area="tools", waiting="a part", next="x"),
         card("r1", "ready", area="tools", next=""), card("d1", "done", completedDate="2026-09-29"),
         card("d2", "done", completedDate="2026-09-20"), card("d3", "done"),
         card("i1", "backlog", created="2026-08-01"), card("i2", "backlog", created="2026-09-15"), card("a1", "archived")]
events = {"b1": [{"type": "move", "ts": "2026-09-20T10:00:00Z", "changes": {"board": ["wip", "blocked"]}}],
          "d3": [{"type": "move", "ts": "2026-09-30T10:00:00Z", "changes": {"board": ["wip", "done"]}}]}
activity = {"w0": "2026-09-10T00:00:00Z"}
data = review.build(cards, lambda s: events.get(s, []), activity, limits={}, today=T)
sec = {k: [c["slug"] for c, _ in rows] for k, _, _, rows in data["sections"]}
why = {c["slug"]: w for _, _, _, rows in data["sections"] for c, w in rows}
print(sec); print(data["areas"])
assert sec["wip"] == ["w0", "w1", "w2", "w3"], sec           # ops 4 > 3; tools 1 WIP not over
assert set(sec["blocked"]) == {"b1"}, sec                      # 11 days in Blocked; b2 waiting since 09-30 (< 7d)
assert sec["stale"] == ["s1"] and "no next action" in why["s1"], (sec, why)
assert sec["nonext"] == ["r1"], sec
assert set(sec["done"]) == {"d1", "d3"}, sec                   # d2 finished last week
assert sec["ideas"] == ["i1", "i2"], sec                       # oldest first
assert "a1" not in str(sec)
assert data["areas"][0] == ("ops", 4, 3), data["areas"]
slugs = [s for v in sec.values() for s in v]; assert len(slugs) == len(set(slugs)), "a card shows twice"
assert review.wip_limits("ops=5, tools=2,bad") == {"ops": 5, "tools": 2}
d2 = review.build(cards, lambda s: events.get(s, []), activity, limits={"ops": 5}, today=T)
assert d2["counts"]["wip"] == 0, d2["counts"]
j = review.as_json(data)
assert j["week_start"] == "2026-09-28" and j["counts"]["wip"] == 4, j["counts"]
assert j["areas"][0] == {"area": "ops", "wip": 4, "limit": 3, "over": True}, j["areas"]
s1 = next(c for sec in j["sections"] for c in sec["cards"] if c["slug"] == "s1")
assert [r["key"] for r in s1["reasons"]] == ["stale", "nonext"] and s1["waiting_on"] == [], s1
assert [sec["key"] for sec in j["sections"]] == ["wip", "blocked", "stale", "nonext", "done", "ideas"]
import json; json.dumps(j)
print("review tests: all passed")
