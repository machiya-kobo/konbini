import datetime, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import deps
import review
from store import Store
from writer import Writer, WriteError, merge_note


def card(slug, title, board, path=None, **kw):
    c = {"slug": slug, "title": title, "board": board, "path": path or "Projects/%s.md" % title, "area": "tools",
         "priority": None, "rank": None, "next": "x", "updated": "2026-09-30", "created": "2026-09-01",
         "waiting": "", "blocked_by": "", "completedDate": "", "dependsOn": []}
    c.update(kw)
    return c


# -- build: vault resolution first, then slug/title; waiting_on only for unfinished dependencies
cards = [card("kura", "Kura", "done"), card("niwa", "Niwa", "wip"),
         card("konbini", "Konbini", "wip", dependsOn=["Kura", "Projects/Niwa", "No Such Thing", "Konbini"]),
         card("shiori", "Shiori", "ready", dependsOn=["konbini"])]
vault = {"kura": "Projects/Kura.md", "projects/niwa": "Projects/Niwa.md", "niwa": "Projects/Niwa.md"}
resolve = lambda t: vault.get(t.lower()) or vault.get(t.split("/")[-1].lower())
g = deps.build(cards, resolve)
titles = lambda xs: [c["title"] for c in xs]
assert titles(g["konbini"]["waits_for"]) == ["Kura", "Niwa"], g["konbini"]
assert titles(g["konbini"]["waiting_on"]) == ["Niwa"], g["konbini"]           # Kura is done
assert g["konbini"]["unresolved"] == ["No Such Thing", "Konbini"], g["konbini"]  # itself doesn't count
assert titles(g["kura"]["unblocks"]) == ["Konbini"] and titles(g["niwa"]["unblocks"]) == ["Konbini"]
assert titles(g["shiori"]["waits_for"]) == ["Konbini"]                        # by slug, not in the vault stub
dec = {c["slug"]: c for c in deps.decorate(cards, g)}
assert dec["konbini"]["_waiting_on"] == ["Niwa"] and dec["kura"]["_waiting_on"] == []
chart = deps.mermaid(cards, g)
assert chart.startswith("flowchart LR") and chart.count("-->") == 3, chart
assert deps.link_for(cards[0]) == "[[Kura]]"

# -- review: an unfinished dependency counts as blocked
assert review.is_blocked(dec["konbini"]) and not review.is_blocked(dec["niwa"])

# -- writer: dependsOn as a quoted block list; re-saving the same deps doesn't rewrite them
d = tempfile.mkdtemp(); os.makedirs(d + "/Projects")
for t, extra in (("Kura", ""), ("Niwa", ""), ("Konbini", 'dependsOn:\n  - "[[Projects/Kura|kura]]"\n')):
    open(d + "/Projects/%s.md" % t, "w").write(
        "---\ntitle: %s\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n  - area/tools\nproject: %s\n"
        "status: wip\n%s---\n# %s\n" % (t, t.lower(), extra, t))
st = Store(d + "/db/k.db", d)
for c in st.scan():
    st.upsert(c)
w = Writer(st)
fm = lambda t: open(d + "/Projects/%s.md" % t).read().split("---")[1]
before = fm("Konbini")
w.update("konbini", {"dependsOn": "Projects/Kura"}, "me", "test")        # same card, other spelling: no write
assert fm("Konbini") == before, fm("Konbini")
w.update("konbini", {"dependsOn": "Kura, niwa"}, "me", "test")
t = fm("Konbini")
assert 'dependsOn:\n  - "[[Kura]]"\n  - "[[Niwa]]"' in t, t
assert st.card("konbini")["dependsOn"] == ["Kura", "Niwa"]
assert any("dependsOn" in (e.get("changes") or {}) for e in st.events(card="konbini"))
w.update("konbini", {"dependsOn": ""}, "me", "test")
assert "dependsOn" not in fm("Konbini")
try:
    w.update("konbini", {"dependsOn": ["Konbini"]}, "me", "test"); raise SystemExit("no error")
except WriteError as e:
    assert e.status == 422

# -- merge: the board's dependsOn list wins over an unrelated upstream edit
base = "---\ntitle: X\nstatus: wip\n---\nbody\n"
ours = '---\ntitle: X\nstatus: wip\ndependsOn:\n  - "[[Kura]]"\n---\nbody\n'
theirs = "---\ntitle: X\nstatus: wip\nsummary: new\n---\nbody changed\n"
m = merge_note(base, ours, theirs)
assert m and '"[[Kura]]"' in m and "summary: new" in m and "body changed" in m, m
print("deps tests: all passed")
