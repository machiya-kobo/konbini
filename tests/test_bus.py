"""The workshop bus's presence (bus.py, stage 3 of the Now page): reading a value (live and not-live states, no card, an
old client's entry, an unknown slug), the snapshot (off, ok, down), session_url never reaching HTML, JSON or the log, the
live agents in now.build and on the page. Then boards on throwaway vaults: a fake bus, the feature off when
KANBAN_BUS_URL is unset, a bus that is down, and one that takes the connection and never answers."""
import datetime, json, os, socket, subprocess, sys, tempfile, textwrap, threading, time, urllib.request
from zoneinfo import ZoneInfo

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
import bus  # noqa: E402
import modern  # noqa: E402
import now  # noqa: E402
from store import parse_note  # noqa: E402

LINK = "https://claude.ai/code/session_ABCdef0123456789"
T = 1795200000                                           # 2026-11-20T18:40:00Z


def val(**kw):
    return json.dumps(kw).encode()


def row(agent, data, headers=None):
    return ("$KV.presence." + agent, data, headers or {})


# -- reading one value ------------------------------------------------------------------------------------------------
w = bus.parse("$KV.presence.helper", val(v=1, state="working", since=T, note="Edit", at=T + 5, status="working: Edit",
                                         model="Opus", session_url=LINK, card="agent-workshop", card_from="focus"))
assert w == {"agent": "helper", "state": "working", "since": "2026-11-20T18:40:00Z", "note": "Edit", "card": "agent-workshop"}, w
assert bus.parse("$KV.presence.planner", val(state="waiting_owner", since=T, note="question: Deploy", card="x", card_from="default"))["card"] == "x"
for state in ("done", "stopped_limit", "error", "offline", "online", "Working", None):
    assert bus.parse("$KV.presence.planner", val(state=state, since=T, card="x", card_from="focus")) is None, state
assert bus.parse("$KV.presence.planner", val(status="listening", at=T)) is None, "an old client's {status, at} isn't live"
nocard = bus.parse("$KV.presence.planner", val(state="working", since=T))
assert nocard["card"] is None and nocard["note"] == "", nocard                          # card absent: no card
assert bus.parse("$KV.presence.planner", val(state="working", card="x"))["card"] is None   # card without card_from
assert bus.parse("$KV.presence.planner", val(state="working", card="x", card_from="guess"))["card"] is None
for bad in ("Bad", "-x", "a/b", "x" * 121, "", 7, None):
    assert bus.parse("$KV.presence.planner", val(state="working", card=bad, card_from="focus"))["card"] is None, bad
for since in ("soon", None, True, 12, 9e12, [T]):
    assert bus.parse("$KV.presence.planner", val(state="working", since=since))["since"] is None, since
for subject in ("$KV.presence.Bad", "$KV.presence.a", "$KV.presence.planner.x", "$KV.holds.planner", "", None):
    assert bus.parse(subject, val(state="working")) is None, subject
for data in (b"", b"not json", b"[1]", b"\xff", b"null"):
    assert bus.parse("$KV.presence.planner", data) is None, data
n = bus.parse("$KV.presence.planner", val(state="working", note='<b>see</b> https://x.example/a "q"\n' + "x" * 200))
assert "<" not in n["note"] and "/" not in n["note"] and '"' not in n["note"] and "\n" not in n["note"], n
assert len(n["note"]) <= bus.NOTE_MAX and n["note"].endswith("…"), n

# entries(): markers dropped, the latest per agent, waiting on the owner first, then by name
got = bus.entries([row("zed", val(state="working")), row("amy", val(state="done")),
                   row("bob", val(state="waiting_owner")), row("cat", val(state="working")),
                   row("dan", b"", {"KV-Operation": "DEL"}), row("eve", val(state="working"), {"Nats-Marker-Reason": "MaxAge"}),
                   row("fay", val(state="working", session_url=LINK), {"KV-Operation": "PURGE"})])
assert [i["agent"] for i in got] == ["bob", "cat", "zed"], got
assert all(set(i) == {"agent", "state", "since", "note", "card"} for i in got)

# -- session_url: never kept --------------------------------------------------------------------------------------------
kept = bus.entries([row("helper", val(state="working", session_url=LINK, card="lantern", card_from="focus"))])
assert "session" not in json.dumps(kept) and "claude.ai" not in json.dumps(kept), kept

# -- the snapshot ---------------------------------------------------------------------------------------------------------
assert bus.Presence().snapshot() == ("off", []) and not bus.Presence().enabled
bus.Presence().start()                                   # off: no thread, and the client is never loaded
assert "nats" not in sys.modules
rows = [row("helper", val(state="working", since=T, card="lantern", card_from="focus", session_url=LINK))]
p = bus.Presence(fetch=lambda: rows)
assert p.snapshot() == ("down", []), "nothing read yet"
p.read_once()
state, items = p.snapshot()
assert state == "ok" and [i["agent"] for i in items] == ["helper"], (state, items)
items[0]["agent"] = "changed"
assert p.snapshot()[1][0]["agent"] == "helper", "a snapshot is a copy"


def boom():
    raise ConnectionRefusedError("no " + LINK)


p.fetch = boom
p.read_once()
assert p.snapshot()[0] == "ok", "one failed read keeps the last good snapshot until it goes stale"
p.stale = 0
time.sleep(0.01)
assert p.snapshot() == ("down", []), p.snapshot()
try:
    bus.Presence("nats://127.0.0.1:1", "Bad Name")
    raise AssertionError("a bad identity is refused")
except ValueError:
    pass
env = bus.Presence.from_env({"KANBAN_BUS_URL": " nats://bus.example.ts.net:4222 ", "KANBAN_BUS_NKEY_FILE": "/run/k.nk"})
assert (env.url, env.identity, env.nkey_file, env.enabled) == ("nats://bus.example.ts.net:4222", "konbini", "/run/k.nk", True)

# -- KANBAN_BUS_AGENTS_FILE: only identities with a session (agent, lead); none set, or a bad file: any valid name ----
agents = tempfile.mkdtemp() + "/agents.yaml"
open(agents, "w").write("identities:\n  helper: {role: agent, host: claude}\n  foreman: {role: lead, host: h}\n"
                        "  room: {role: room, host: h}\n  watcher: {role: observer, host: h}\n")
three = [row(a, val(state="working")) for a in ("helper", "foreman", "room", "watcher", "stray")]
p = bus.Presence(fetch=lambda: three, agents_file=agents)
p.read_once()
assert [i["agent"] for i in p.snapshot()[1]] == ["foreman", "helper"], p.snapshot()
time.sleep(0.01)
open(agents, "w").write("identities:\n  stray: {role: agent}\n")
p.read_once()
assert [i["agent"] for i in p.snapshot()[1]] == ["stray"], "re-read when the file changes"
os.unlink(agents)
p.read_once()
assert len(p.snapshot()[1]) == 5, "a missing file: no filter"
assert len(bus.entries(three)) == 5
assert bus.Presence.from_env({"KANBAN_BUS_AGENTS_FILE": " /repos/workshop/agents.yaml "}).agents_file == "/repos/workshop/agents.yaml"

# -- card_known, now.build and the page ------------------------------------------------------------------------------
lantern = parse_note("---\ntitle: Lantern\nstatus: wip\ntags:\n  - type/project\n---\n# Lantern\n", "Projects/Lantern.md")
quiet = parse_note("---\ntitle: Shade\nstatus: wip\ntags:\n  - type/project\n---\n# Shade\n", "Projects/Shade.md")
cards = [lantern, quiet]
live = bus.mark_known(bus.entries([
    row("helper", val(state="working", since=T, note="Edit", card="lantern", card_from="focus", session_url=LINK)),
    row("planner", val(state="waiting_owner", since=T, note="question: Deploy", card="not-a-card", card_from="focus")),
    row("welder", val(state="working", since=T)),
]), {c["slug"] for c in cards})
assert [(i["agent"], i["card"], i["card_known"]) for i in live] == [
    ("planner", "not-a-card", False), ("helper", "lantern", True), ("welder", None, False)], live
for i in live:
    assert set(i) == {"agent", "state", "since", "note", "card", "card_known"}, i
PT = ZoneInfo("America/Los_Angeles")
NOW = datetime.datetime(2026, 11, 20, 20, 0, tzinfo=datetime.timezone.utc)
data = now.build(cards, [], [], {}, {}, lambda t: None, datetime.date(2026, 11, 20), PT, NOW, live=live)
assert data["live"] == live, data["live"]
work = {x["slug"]: x for x in data["working"]}
assert list(work) == ["lantern"] and work["lantern"]["live"] == ["helper"], data["working"]   # live alone makes it working
assert (work["lantern"]["source"], work["lantern"]["line"]) == ("claim", "Working now (helper)"), work["lantern"]
assert [q["slug"] for q in data["quiet"]] == ["shade"]
assert now.build(cards, [], [], {}, {}, lambda t: None, datetime.date(2026, 11, 20), PT, NOW)["live"] == []

strip = modern.live_strip(cards, data["live"], "ok")
assert 'id="n-live"' in strip and "Agents Now" in strip and '<a class="title" href="/p/lantern">Lantern</a>' in strip, strip
assert strip.count('class="nocard">no card<') == 2 and "Waiting on You" in strip and "question: Deploy" in strip, strip
assert strip.index("planner") < strip.index("helper"), "waiting on the owner first"
assert modern.live_strip(cards, [], "off") == ""
assert "No agents working right now." in modern.live_strip(cards, [], "ok")
assert "Can't reach the workshop bus right now." in modern.live_strip(cards, [], "down")
assert "<b>" not in modern.live_strip(cards, [dict(live[1], note="<b>x</b>", agent="<b>")], "ok")
badge = modern.claim_badge({"actor": "helper", "agent": "helper", "expires": None, "live": [live[1]]})
assert badge == '<span class="chip claim live" title="Working now, on the workshop bus">helper now</span>', badge
both = modern.claim_badge({"actor": "u", "agent": "helper", "expires": time.time() + 600, "live": [live[1]]})
assert both.count('class="chip claim') == 1 and ("helper 10m" in both or "helper 9m" in both), both      # one badge per agent
assert modern.claim_badge({"actor": "u", "agent": "kura", "expires": time.time() + 600}).startswith('<span class="chip claim">kura')


# -- boards on throwaway vaults ----------------------------------------------------------------------------------------
SERVER = textwrap.dedent('''
    import json, sys
    sys.path.insert(0, sys.argv[1])
    import app, bus
    if sys.argv[3] == "fake":
        LINK = %r
        ROWS = [("$KV.presence.helper", json.dumps({"state": "working", "since": 1795200000, "note": "Edit",
                                                    "card": "lantern", "card_from": "focus", "session_url": LINK}).encode(), {}),
                ("$KV.presence.planner", json.dumps({"state": "waiting_owner", "card": "gone", "card_from": "default",
                                                 "session_url": LINK}).encode(), {})]
        app.presence = bus.Presence(fetch=lambda: ROWS, poll=0.2)
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''' % LINK)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


def board(mode, extra_env=None):
    d = tempfile.mkdtemp()
    os.makedirs(d + "/vault/Projects")
    for title in ("Lantern", "Shade"):
        open(d + "/vault/Projects/%s.md" % title, "w").write(
            "---\ntitle: %s\nstatus: wip\ntags:\n  - type/project\n  - area/crafts\n---\n# %s\n" % (title, title))
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    port = free_port()
    env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", TZ="America/Los_Angeles", PYTHONDONTWRITEBYTECODE="1")
    for k in ("MACHIYA_IDENTITY_FILE", "KANBAN_BOARD_URL", "KANBAN_REPO_SUBDIR", "KANBAN_BUS_URL", "KANBAN_BUS_IDENTITY",
              "KANBAN_BUS_NKEY_FILE"):
        env.pop(k, None)
    env.update(extra_env or {})
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port), mode], env=env, stdout=subprocess.DEVNULL,
                            stderr=open(d + "/server.log", "w"))
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.05)

    def get(path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), headers={"Host": "127.0.0.1:%d" % port})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), time.monotonic() - t0
    return proc, get, d


def no_link(text, what):
    assert "claude.ai" not in text and "session_" not in text and "ABCdef0123456789" not in text, what


# a fake bus: the strip, the badge on the Now page, the board and the card page; /api/now's shape; no session link anywhere
proc, get, d = board("fake")
try:
    for _ in range(100):
        api = json.loads(get("/api/now")[1])
        if api["live"]:
            break
        time.sleep(0.05)
    assert [(i["agent"], i["card"], i["card_known"]) for i in api["live"]] == [("planner", "gone", False),
                                                                              ("helper", "lantern", True)], api["live"]
    assert all(set(i) == {"agent", "state", "since", "note", "card", "card_known"} for i in api["live"])
    assert [(x["slug"], x["live"]) for x in api["working"]] == [("lantern", ["helper"])], api["working"]
    pages = {path: get(path)[1] for path in ("/now", "/", "/p/lantern", "/api/now", "/api/cards", "/api/cards/lantern",
                                             "/search?q=lantern", "/review")}
    for path, text in pages.items():
        no_link(text, path)
    page = pages["/now"]
    assert page.index('id="n-live"') < page.index('id="n-working"'), "the strip is at the top"
    assert "Agents Now" in page and "Waiting on You" in page and "no card" in page, page[:3000]
    assert "helper now" in page and "helper now" in pages["/"] and "helper now" in pages["/p/lantern"]
    assert json.loads(pages["/api/cards/lantern"]).get("claim") is None, "the API's claims stay the stored ones"
finally:
    proc.kill()
log = open(d + "/server.log").read()
no_link(log, "the log")

# the feature off: no strip, live: [], and the board works as before
proc, get, d = board("plain")
try:
    st, page, _ = get("/now")
    assert st == 200 and 'id="n-live"' not in page and "Agents Now" not in page and "Working on" in page
    assert json.loads(get("/api/now")[1])["live"] == []
finally:
    proc.kill()
assert "bus:" not in open(d + "/server.log").read()

# a bus that is down (nothing listens), and one that takes the connection and never answers: the page doesn't wait
silent = socket.socket(); silent.bind(("127.0.0.1", 0)); silent.listen(8)
held = []
threading.Thread(target=lambda: [held.append(silent.accept()) for _ in range(8)], daemon=True).start()
seed = tempfile.mkdtemp() + "/k.nk"
open(seed, "w").write("SU" + "A" * 56 + "\n")
for url in ("nats://127.0.0.1:%d" % free_port(), "nats://127.0.0.1:%d" % silent.getsockname()[1]):
    proc, get, d = board("plain", {"KANBAN_BUS_URL": url, "KANBAN_BUS_NKEY_FILE": seed})
    try:
        for _ in range(3):
            st, page, took = get("/now")
            assert st == 200 and took < 2, (url, st, took)
            assert "Can't reach the workshop bus right now." in page and "Working on" in page, page[:3000]
            st, body, took = get("/api/now")
            assert st == 200 and took < 2 and json.loads(body)["live"] == [], (url, body[:200])
            time.sleep(0.3)
        if url.endswith(":%d" % silent.getsockname()[1]):
            continue                                    # a silent bus fails only after the timeouts; the page never waited
        for _ in range(100):                            # a refused one is noticed at once (or the client isn't installed)
            if "bus: can't read presence (" in open(d + "/server.log").read():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("a down bus is logged")
    finally:
        proc.kill()
    log = open(d + "/server.log").read()
    assert "SU" + "A" * 56 not in log, "the seed never reaches the log"
    assert log.count("bus: can't read presence") <= 2, log            # said once per kind of failure, not every round
print("bus tests: all passed")
