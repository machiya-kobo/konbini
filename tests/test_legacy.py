"""The old field names (board, blocked_by, date, integer priority, status/* tags) are not read any more; a note
still carrying one is reported once in the log and listed in Store.legacy (/api/status: legacy_names), never misread."""
import contextlib, io, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from store import Store, legacy_names, parse_note, parse_priority

assert parse_priority("high") == 1 and parse_priority("low") == 3 and parse_priority(2) is None and parse_priority("2") is None
assert legacy_names({"board": "wip", "blocked_by": "x", "date": "2026-01-01", "priority": 2}, ["status/active"]) == \
    ["board", "blocked_by", "date", "priority", "status/*"]
assert legacy_names({"status": "wip", "priority": "high", "created": "2026-01-01"}, ["type/project"]) == []

# a card with the old board: field is not a card (Unsorted if it carries type/project); a bare old note isn't one at all
card = parse_note("---\ntitle: A\ntags:\n  - type/project\nproject: a\nboard: wip\nblocked_by: x\n---\n", "Projects/A.md")
assert card["board"] is None and card["blocked_by"] == "" and card["created"] == "", card
assert parse_note("---\ntitle: B\nboard: wip\n---\n", "Projects/B.md") is None
# the new names alone
card = parse_note("---\ntitle: C\nproject: c\nstatus: blocked\nwaiting: a part\npriority: low\ncreated: 2026-09-01\n---\n", "Projects/C.md")
assert (card["board"], card["blocked_by"], card["priority"], card["created"], card["status"]) == \
    ("blocked", "a part", 3, "2026-09-01", "on-hold"), card

d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
open(d + "/Projects/Old.md", "w").write("---\ntitle: Old\ntags:\n  - type/project\n  - status/draft\nproject: old\nboard: backlog\ndate: 2026-01-02\n---\n")
open(d + "/Projects/Plain.md", "w").write("---\ntitle: Plain\ndate: 2026-01-02\n---\nbody\n")     # not a card, still reported
open(d + "/Projects/Fine.md", "w").write("---\ntitle: Fine\nproject: fine\nstatus: wip\ncreated: 2026-01-02\n---\n")
st = Store(d + "/db/k.db", d)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    cards = {c["slug"]: c for c in st.scan()}
    st.scan()                                           # the next import says nothing new
assert sorted(cards) == ["fine", "old"] and cards["fine"]["board"] == "wip" and cards["old"]["board"] is None, cards.keys()
assert {(x["path"], x["field"]) for x in st.legacy} == {("Projects/Old.md", "board, date, status/*"), ("Projects/Plain.md", "date")}, st.legacy
assert next(x for x in st.legacy if x["path"] == "Projects/Old.md")["slug"] == "old"
lines = [l for l in out.getvalue().splitlines() if "old field names ignored" in l]
assert len(lines) == 2 and any("Projects/Old.md: old field names ignored: board, date, status/*" in l for l in lines), out.getvalue()
print("legacy tests: all passed")
