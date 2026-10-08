"""Helpers the board's pages share: filters, facets, staleness, history folding, event lines, colors, and
the per-request context.
"""
import datetime
import html

from store import COLUMNS

SHOWN = [c for c in COLUMNS if c != "archived"]
FILTERS = ("area", "topic", "machine", "agent", "effort", "stream", "q")
STALE_DAYS = 14


def qget(query, key):
    return ((query or {}).get(key) or [""])[0].strip()


def claim_who(claim):
    if not claim:
        return ""
    return claim["agent"] if claim["agent"] not in ("web", "api") else (claim.get("actor") or "")


def filter_cards(cards, query, claims):
    """GET filters: area, topic, machine, agent (claimed by; 'any'), effort, stream, q (text)."""
    area, topic, machine, agent, effort, stream, q = (qget(query, k) for k in FILTERS)
    q = q.lower()
    out = []
    for c in cards:
        if area and area not in (c.get("areas") or [c["area"]]):
            continue
        if topic and topic not in (c.get("topics") or []):
            continue
        if machine and machine not in (c.get("machines") or []):
            continue
        if effort and c.get("effort") != effort:
            continue
        if stream and (c.get("stream") or "").lower() != stream.lower():
            continue
        if agent:
            who = claim_who((claims or {}).get(c["slug"]))
            if (agent == "any" and not who) or (agent != "any" and who != agent):
                continue
        if q:
            hay = " ".join([c["title"], c.get("summary") or "", c.get("next") or "", c.get("blocked_by") or "",
                            " ".join(c.get("tags") or []), c.get("family") or "", c.get("stream") or "",
                            c.get("goal") or ""]).lower()
            if q not in hay:
                continue
        out.append(c)
    return out


def facets(cards, claims):
    """The values the filter bar offers."""
    areas, topics, machines, agents, streams = set(), set(), set(), set(), set()
    for c in cards:
        areas.update(c.get("areas") or [c["area"]])
        topics.update(c.get("topics") or [])
        machines.update(c.get("machines") or [])
        if c.get("stream"):
            streams.add(c["stream"])
        who = claim_who((claims or {}).get(c["slug"]))
        if who:
            agents.add(who)
    return {"area": sorted(areas), "topic": sorted(topics), "machine": sorted(machines),
            "agent": sorted(agents), "effort": ["s", "m", "l"], "stream": sorted(streams, key=str.lower)}


def stale_days(card, activity, today=None):
    """Days since the last board change or event, for WIP/Ready cards idle 14+ days; else None."""
    if card.get("board") not in ("wip", "ready"):
        return None
    last = max(card.get("updated") or "", ((activity or {}).get(card["slug"]) or "")[:10])
    try:
        d = datetime.date.fromisoformat(last[:10])
    except ValueError:
        return None
    days = ((today or datetime.date.today()) - d).days
    return days if days >= STALE_DAYS else None


def lane_of(card, group):
    if group == "family":
        return card.get("family") or "other"
    if group == "stream":
        return card.get("stream") or "no stream"
    return card["area"]


def collapse_history(events, window=3600):
    """Consecutive notes from the same agent within an hour fold into one group:
    [("event", ev)] or [("group", agent, [events])]."""
    out = []
    for ev in events:
        who = ev.get("agent") if ev.get("agent") not in (None, "web", "api") else (ev.get("actor") or "")
        if ev.get("type") == "comment" and out and out[-1][0] == "group" and out[-1][1] == who:
            prev = out[-1][2][-1]
            try:
                gap = abs((datetime.datetime.fromisoformat(prev["ts"].replace("Z", "+00:00"))
                           - datetime.datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))).total_seconds())
            except ValueError:
                gap = window + 1
            if gap <= window:
                out[-1][2].append(ev)
                continue
        if ev.get("type") == "comment":
            out.append(("group", who, [ev]))
        else:
            out.append(("event", ev))
    return [x if x[0] == "event" or len(x[2]) > 1 else ("event", x[2][0]) for x in out]

COLUMN_COLOR = {"backlog": "comment", "ready": "blue", "wip": "orange",
                "blocked": "red", "done": "green", "archived": "comment"}
PRIORITY_COLOR = {1: "red", 2: "yellow", 3: "comment"}


def e(text):
    return html.escape(str(text or ""), quote=True)


class Ctx:
    """Per-request rendering choices."""

    def __init__(self, theme, text="standard", extra=None):
        # the shell's names (vaultkit.shell): system | night | day, with the old `auto` read as system
        self.theme = "system" if theme == "auto" else (theme if theme in ("night", "day", "system") else "system")
        self.text = text
        self.extra = extra or {}        # other per-device settings from cookies (group, doneCards)
        self.status = None              # the footer's status line (shell.footer)
        self.alert = ""             # board header warning (broken note, stuck sync)
        self.alert_links = []       # [(label, href)] shown after it


def event_line(ev):
    what = ev.get("type", "")
    ch = ev.get("changes") or {}
    if what == "move" and "board" in ch:
        what = "moved %s -> %s" % (ch["board"][0] or "-", ch["board"][1])
        if ev.get("outcome") == "wontdo":
            what += " (won't do%s)" % (": " + ev["reason"] if ev.get("reason") else "")
    elif what == "edit":
        what = "edited " + ", ".join(k for k in ch)
    elif what == "comment":
        what = "comment: " + ev.get("body", "")
    elif what == "create":
        what = "created in " + ev.get("board", "")
    who = ev.get("agent") if ev.get("agent") not in (None, "web", "api") else ev.get("actor", "")
    return "%s &middot; %s &middot; %s" % (e(ev.get("ts", "")[:16].replace("T", " ")), e(who), e(what))


KIND_MARK = {"done": ("[x]", "green"), "started": (">", "blue"), "milestone": ("*", "yellow"),
             "systems": ("#", "cyan"), "idea": ("+", "magenta"), "write": ("!", "magenta")}
