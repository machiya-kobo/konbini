"""Machine change logs in Systems/: the monthly notes (Systems/Change Logs/<host> YYYY-MM.md, `host:` in the
frontmatter) and the older one-note-per-host tables are both read, and both name the machine, never the month note
("kiln", not "kiln 2026-10"): in the timeline and roundups, the digest's one entry per host per day, and a
writing kit's Systems list. A host note's "## Change Log" list of links adds nothing."""
import datetime, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import digest
from blog import Blog
from garden import Garden
from kit import Kits
from store import Store
from timeline import Timeline, system_host

d = tempfile.mkdtemp()
for folder in ("Projects", "Systems/Change Logs"):
    os.makedirs(os.path.join(d, folder))
TABLE = "| Date | Category | Change | Details |\n|---|---|---|---|\n"
notes = {
    "Projects/Lantern.md": "---\ntitle: Lantern\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/crafts\n"
                           "  - machine/kiln\nproject: lantern\nstatus: wip\n---\n# Lantern\n",
    # the host note keeps its overview and a list of links to the months: no rows of its own
    "Systems/kiln.md": "---\ntitle: kiln\ntags:\n  - type/system\n---\n# kiln\n\nThe home server.\n\n## Change Log\n\n"
                          "One note per month, newest first:\n\n- [[Systems/Change Logs/kiln 2026-10|2026-10]]\n"
                          "- [[Systems/Change Logs/kiln 2026-09|2026-09]]\n",
    "Systems/Change Logs/kiln 2026-10.md": "---\ntitle: kiln 2026-10\nhost: kiln\nmonth: 2026-10\ntags:\n  - type/log\n"
                                              "  - machine/kiln\n---\n# kiln 2026-10\n\n" + TABLE +
                                              "| 2026-10-05 | config | Lantern board deployed | the lantern stack |\n"
                                              "| 2026-10-05 | update | Packages | apt upgrade |\n"
                                              "| 2026-10-06 | reboot | Rebooted | kernel |\n",
    # a month note without host: still reads, under its title as before
    "Systems/Change Logs/oldnote 2026-10.md": "---\ntitle: oldnote 2026-10\n---\n" + TABLE + "| 2026-10-06 | update | Packages | |\n",
    # the older layout: the table in the host's own note
    "Systems/pi.md": "---\ntitle: pi\n---\n# pi\n\n## Change Log\n\n" + TABLE + "| 2026-10-05 | update | Lantern sensor | |\n",
}
for rel, text in notes.items():
    open(os.path.join(d, rel), "w").write(text)
subprocess.run(["git", "-C", d, "init", "-q"], check=True)
subprocess.run(["git", "-C", d, "add", "-A"], check=True)
subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "notes"], check=True)

st = Store(d + "/db/k.db", d)
st.rebuild()
tl = Timeline(st)

assert system_host("Systems/Change Logs/kiln 2026-10.md", {"title": "kiln 2026-10", "host": "kiln"}) == "kiln"
assert system_host("Systems/pi.md", {"title": "pi"}) == "pi" and system_host("Systems/Change Logs/x 2026-10.md", {}) == "x 2026-10"

# the timeline and roundups: one item per row, named after the machine; the host note's links add nothing
start, end = datetime.date(2026, 10, 1), datetime.date(2026, 11, 1)
systems = [i for i in tl.items(start, end) if i.kind == "systems"]
got = sorted((i.date.isoformat(), i.title, i.text) for i in systems)
assert got == [("2026-10-05", "kiln", "Lantern board deployed"), ("2026-10-05", "kiln", "Packages"),
               ("2026-10-05", "pi", "Lantern sensor"), ("2026-10-06", "kiln", "Rebooted"),
               ("2026-10-06", "oldnote 2026-10", "Packages")], got
week = tl.roundup("week", datetime.date(2026, 10, 6))
assert "kiln 2026-10" not in tl.markdown(week) and "kiln" in tl.markdown(week), tl.markdown(week)

# the digest: one entry per host per day
entries = [e for e in digest.board_part(st, tl, start, end, {})[1] if e.get("kind") == "systems"]
assert sorted((e["host"], e["date"].isoformat() if hasattr(e["date"], "isoformat") else e["date"], e["count"]) for e in entries) == \
    [("kiln", "2026-10-05", 2), ("kiln", "2026-10-06", 1), ("oldnote 2026-10", "2026-10-06", 1), ("pi", "2026-10-05", 1)], entries

# a writing kit lists the machine changes that mention the card, by machine
kits = Kits(st, Garden(st, tl), tl, Blog(d + "/no-blog", "", ""), "")
k = kits.build(st.card("lantern"), remote=False)
assert sorted((s["host"], s["change"]) for s in k["systems"]) == [("kiln", "Lantern board deployed"), ("pi", "Lantern sensor")], k["systems"]
# a repository named after a machine, without the card's machine/ tag, doesn't pull in that machine's whole log
open(os.path.join(d, "Projects/Stack.md"), "w").write(
    "---\ntitle: Media stack\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/ops\nproject: media-stack\n"
    "status: wip\nrepo: kiln\n---\n# Media stack\n")
st.rebuild()
k = kits.build(st.card("media-stack"), remote=False)
assert k["systems"] == [], k["systems"]
print("systems tests: all passed")
