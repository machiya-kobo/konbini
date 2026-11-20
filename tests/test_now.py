"""The Now page's data (now.build, GET /api/now): the window's edge in the board's days (Pacific time), the order of
Working on, a card made active by a change-log row alone, quiet WIP against working, the uncarded rows by host, and
commits from a card's repos. Then /api/now and /now from a board on a throwaway vault."""
import datetime, json, os, socket, subprocess, sys, tempfile, textwrap, time, urllib.request
import yaml
from zoneinfo import ZoneInfo

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import common  # noqa: E402
import now  # noqa: E402
from store import parse_note  # noqa: E402
from vaultkit.vault import resolve_in  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
TODAY = datetime.date(2026, 11, 20)                     # the window: 2026-11-14 00:00 PST (08:00 UTC) on
NOW = datetime.datetime(2026, 11, 20, 20, 0, tzinfo=datetime.timezone.utc)
TABLE = "\n## Log\n\n| Date | Category | Change | Details | Status | Tags |\n|---|---|---|---|---|---|\n"


def project(title, status, extra="", log=()):
    return ("---\ntitle: %s\nstatus: %s\n%stags:\n  - type/project\n  - area/crafts\n---\n# %s\n" % (title, status, extra, title)
            + ((TABLE + "".join("| %s | milestone | %s | | ✅ | |\n" % r for r in log)) if log else ""))


def changelog(host, rows):
    return ("---\ntitle: %s 2026-11\nhost: %s\n---\n# %s change log\n" % (host, host, host)
            + TABLE + "".join("| %s | config | %s | %s | ✅ | |\n" % r for r in rows))


NOTES = {
    "Projects/Edge In.md": project("Edge In", "wip"),             # an event at 00:00 PST on the window's first day
    "Projects/Edge Out.md": project("Edge Out", "wip"),           # one second earlier: quiet
    "Projects/Row In.md": project("Row In", "wip", log=[("2026-11-14", "first day of the window")]),
    "Projects/Row Out.md": project("Row Out", "wip", log=[("2026-11-13", "the day before"), ("2026-11-21", "tomorrow")]),
    "Projects/Bench.md": project("Bench", "wip", "repos:\n  - Bench-Tools\n  - bench-tools\n",
                                 log=[("2026-11-19", "bench log row")]),
    "Projects/Kit.md": project("Kit", "ready"),                   # active only through a change-log row
    "Projects/Old.md": project("Old", "wip", "repo: https://git.example.com/user/old-thing.git\n",
                               log=[("2026-10-01", "long ago")]),
    "Projects/Never.md": project("Never", "wip"),
    "Projects/Claimed.md": project("Claimed", "backlog"),
    "Projects/Reordered.md": project("Reordered", "wip"),          # only a drag-and-drop reorder: not work
    "Projects/Idea.md": "---\ntitle: Idea\n---\n# Idea\n",        # not a card
    "Repos/bench-tools.git.md": ("---\ntitle: bench-tools.git\nlast_commit: 2026-11-19\n---\n# bench-tools.git\n\n"
                                 "**Recent commits (`main`)**\n\n- 2026-11-19: cut list for the top\n- 2026-11-12: older\n"),
    "Repos/old-thing.git.md": "---\ntitle: old-thing.git\nlast_commit: 2026-09-30\n---\n# old-thing.git\n",
    "Systems/Change Logs/shop 2026-11.md": changelog("shop", [
        ("2026-11-18", "Packed the kit's paste", "For [[Projects/Kit\\|the kit]]"),
        ("2026-11-17", "Glue gun swapped", ""),
        ("2026-11-15", "Lights rewired", "see [[Notes/Wiring]]"),        # links a note that isn't a card
        ("2026-11-10", "Swept", ""),                                     # before the window
    ]),
    "Systems/Change Logs/garage 2026-11.md": changelog("garage", [("2026-11-19", "Dehumidifier at 45%", "")]),
    "Systems/Change Logs/attic 2026-11.md": changelog("attic", [("2026-11-16", "Boxes moved", "")]),
    "Notes/Wiring.md": "---\ntitle: Wiring\n---\n# Wiring\n",
}
EVENTS = [
    {"ts": "2026-11-14T08:00:00Z", "card": "edge-in", "type": "comment", "body": "at midnight Pacific", "agent": "helper",
     "actor": "user@example.com"},
    {"ts": "2026-11-14T07:59:59Z", "card": "edge-out", "type": "comment", "body": "a second before", "agent": "web"},
    {"ts": "2026-11-19T18:00:00Z", "card": "bench", "type": "move", "changes": {"board": ["ready", "wip"]}, "agent": "web",
     "actor": "user@example.com"},
    {"ts": "2026-11-19T19:00:00Z", "card": "reordered", "type": "edit", "changes": {"rank": [10, 20]}, "agent": "web"},
]


LAST = {"edge-out": "2026-11-14T07:59:59Z"}             # store.last_activity(): each card's latest event, all time


def build(notes=NOTES, events=EVENTS, claims=None, last=LAST, checkouts=None):
    rows = [(rel, {}, text) for rel, text in notes.items()]
    for i, (rel, _, text) in enumerate(rows):            # the frontmatter as the vault index reads it
        rows[i] = (rel, yaml.safe_load(text.split("---")[1]) or {}, text)
    cards = [c for c in (parse_note(text, rel) for rel, _, text in rows) if c]
    by_name = {}
    for rel, _, _ in rows:
        by_name.setdefault(os.path.splitext(os.path.basename(rel))[0].lower(), rel)
        by_name.setdefault(rel[:-3].lower(), rel)
    return now.build(cards, rows, [e for e in events if e["ts"] >= "2026-11-14T08:00:00Z"], last, claims or {},
                     lambda t: resolve_in(by_name, t), TODAY, PT, NOW, checkouts=checkouts)


# -- the rule's one home ----------------------------------------------------------------------------------------------
assert common.NOW_DAYS == 7 and common.STALE_DAYS == 14
assert common.now_since(TODAY, PT).isoformat() == "2026-11-14T00:00:00-08:00"
assert common.now_since(datetime.date(2026, 3, 9), PT).isoformat() == "2026-03-03T00:00:00-08:00"    # across the DST change
assert common.now_since(datetime.date(2026, 3, 14), PT).isoformat() == "2026-03-08T00:00:00-08:00"

data = build()
json.dumps(data)
assert set(data) == {"days", "since", "working", "quiet", "uncarded", "live"} and data["live"] == [], data.keys()
assert data["days"] == 7 and data["since"] == "2026-11-14T00:00:00-08:00", data["since"]
work = {w["slug"]: w for w in data["working"]}
quiet = {q["slug"]: q for q in data["quiet"]}
print([(w["slug"], w["at"], w["source"]) for w in data["working"]])
print(data["quiet"]); print(data["uncarded"])
for w in data["working"]:
    assert set(w) == {"slug", "title", "path", "board", "at", "line", "source", "live"} and w["live"] == [], w
for q in data["quiet"]:
    assert set(q) == {"slug", "title", "path", "last_at"}, q

# -- the window's edge, in Pacific time ---------------------------------------------------------------------------
assert "edge-in" in work and work["edge-in"]["line"] == "at midnight Pacific (helper)", work.get("edge-in")
assert "user@example.com" not in json.dumps(data), "a login never reaches the line"
assert "edge-out" in quiet and "edge-out" not in work
assert work["row-in"]["source"] == "log" and work["row-in"]["at"] == "2026-11-14", work["row-in"]
assert "row-out" in quiet and quiet["row-out"]["last_at"] == "2026-11-13", quiet["row-out"]    # a future row is no activity

# -- the line: the latest day, then the heaviest source; commits from the repo note -------------------------------
b = work["bench"]
assert (b["source"], b["at"], b["line"]) == ("commit", "2026-11-19", "bench-tools: cut list for the top"), b  # over the move and the Log row
k = work["kit"]
assert (k["source"], k["board"], k["line"]) == ("changelog", "ready", "shop: Packed the kit's paste"), k      # a change-log row alone

# -- ordering: newest first (day, then weight, then time) ---------------------------------------------------------
order = [w["slug"] for w in data["working"]]
assert order == ["bench", "kit", "edge-in", "row-in"], order

# -- quiet vs working: WIP with nothing in the window, oldest first, never first ----------------------------------
assert [q["slug"] for q in data["quiet"]] == ["never", "reordered", "old", "row-out", "edge-out"], data["quiet"]
assert quiet["old"]["last_at"] == "2026-10-01" and quiet["never"]["last_at"] is None, quiet   # Log row beats the repo's 09-30
assert "kit" not in quiet and "claimed" not in quiet and "idea" not in work and "idea" not in quiet

# -- no card yet: rows that link no card, by host (newest host first), newest row first, nothing before the window ---
assert data["uncarded"] == [
    {"host": "garage", "rows": [{"date": "2026-11-19", "change": "Dehumidifier at 45%", "path": "Systems/Change Logs/garage 2026-11.md"}]},
    {"host": "shop", "rows": [{"date": "2026-11-17", "change": "Glue gun swapped", "path": "Systems/Change Logs/shop 2026-11.md"},
                              {"date": "2026-11-15", "change": "Lights rewired", "path": "Systems/Change Logs/shop 2026-11.md"}]},
    {"host": "attic", "rows": [{"date": "2026-11-16", "change": "Boxes moved", "path": "Systems/Change Logs/attic 2026-11.md"}]},
], data["uncarded"]

# -- claims count, a backlog card included; older events only set last_at -------------------------------------------
d2 = build(claims={"claimed": {"actor": "user@example.com", "agent": "kura", "expires": 0}},
           last={"never": "2026-11-02T10:00:00Z", "edge-in": "2026-11-14T08:00:00Z"})
w2 = {w["slug"]: w for w in d2["working"]}
assert w2["claimed"]["source"] == "claim" and w2["claimed"]["line"] == "Claimed by kura" and d2["working"][0]["slug"] == "claimed"
assert {q["slug"]: q for q in d2["quiet"]}["never"]["last_at"] == "2026-11-02T10:00:00Z", d2["quiet"]
assert now.event_text({"type": "edit", "changes": {"next": ["a", "glue the skin"]}, "agent": "kura"}) == "Next: glue the skin (kura)"
assert now.event_text({"type": "move", "changes": {"board": ["wip", "archived"]}, "outcome": "wontdo"}) == "Moved to Archived (won't do)"

# -- a checkout under KANBAN_REPOS wins over the repo note: its commits carry a time, counted in Pacific days ---------
root = tempfile.mkdtemp()
git = ["git", "-C", root + "/bench-tools", "-c", "user.name=Demo", "-c", "user.email=demo@example.invalid",
       "-c", "commit.gpgsign=false"]
subprocess.run(["git", "init", "-q", root + "/bench-tools"], check=True)
for when, subject in (("2026-11-13T23:00:00-08:00", "before the window"), ("2026-11-19T23:30:00-08:00", "glue jig drawing"),
                      ("2026-11-19T23:40:00-08:00", "board: a housekeeping commit")):
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", subject], check=True,
                   env=dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when))
os.makedirs(root + "/old-thing")                       # not a checkout: the repo note stands in
checkouts = now.Checkouts(root)
assert checkouts("Bench-Tools")[0] == ("2026-11-20T07:30:00Z", "glue jig drawing"), checkouts("bench-tools")
assert checkouts("old-thing") is None and checkouts("missing") is None
d3 = build(checkouts=checkouts)
b3 = {w["slug"]: w for w in d3["working"]}["bench"]
assert (b3["at"], b3["line"], b3["source"]) == ("2026-11-20T07:30:00Z", "Bench-Tools: glue jig drawing", "commit"), b3
assert {q["slug"]: q for q in d3["quiet"]}["old"]["last_at"] == "2026-10-01"

# -- /api/now and /now on a board -------------------------------------------------------------------------------------
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
d = tempfile.mkdtemp()
today = datetime.datetime.now(PT).date()
for rel, text in {"Projects/Lantern.md": project("Lantern", "wip", log=[(today.isoformat(), "Second frame glued")]),
                  "Projects/LED.md": project("LED", "wip"),
                  "Systems/Change Logs/shop.md": changelog("shop", [(today.isoformat(), "Glue <b>gun</b> swapped", "")])}.items():
    os.makedirs(os.path.dirname(os.path.join(d, "vault", rel)), exist_ok=True)
    open(os.path.join(d, "vault", rel), "w").write(text)
subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port), KANBAN_BIND="127.0.0.1",
           KANBAN_AUTH="open", TZ="America/Los_Angeles", PYTHONDONTWRITEBYTECODE="1")
for k in ("MACHIYA_IDENTITY_FILE", "KANBAN_BOARD_URL", "KANBAN_REPO_SUBDIR"):
    env.pop(k, None)
open(d + "/server.py", "w").write(SERVER)
proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env, stdout=subprocess.DEVNULL,
                        stderr=open(d + "/server.log", "w"))
try:
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.05)

    def get(path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers={"Host": "127.0.0.1:%d" % port})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    st, h, body = get("/api/now")
    api = json.loads(body)
    assert st == 200 and h["Content-Type"].startswith("application/json"), (st, h["Content-Type"])
    assert [w["slug"] for w in api["working"]] == ["lantern"] and [q["slug"] for q in api["quiet"]] == ["led"], api
    assert api["since"].startswith((today - datetime.timedelta(days=6)).isoformat() + "T00:00:00-0"), api["since"]
    assert api["uncarded"][0]["host"] == "shop" and api["live"] == [], api
    st, h, page = get("/now")
    assert st == 200 and "Working on" in page and "Second frame glued" in page and "Quiet WIP" in page, page[-2000:]
    assert "No Card Yet" in page and "Glue &lt;b&gt;gun&lt;/b&gt; swapped" in page and "<b>gun</b>" not in page
    blocked = page.index('nowhead col-blocked">Blocked')
    assert page.index('id="n-working"') < page.index("Quiet WIP") < page.index('id="n-uncarded"') < blocked
    assert "<form" not in page[page.index('id="n-uncarded"'):blocked], "the rows are read-only"
finally:
    proc.kill()
print("now tests: all passed")
