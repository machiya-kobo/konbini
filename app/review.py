"""The weekly review (/review): what needs a decision this week, from the cards and the board's events.

One screen with WIP over the limit, stale WIP/Ready, cards blocked for a week or more, cards with no next
action, what got done this week and the ideas waiting in Backlog. Each card shows once, in the first
section that applies (the order below); the other reasons ride along as chips.
"""
import datetime
import os

from common import stale_days
from store import WIP_LIMIT, sort_key
from timeline import local_date

BLOCKED_DAYS = 7

SECTIONS = [
    ("wip", "WIP Over the Limit", "Pick what to pause: each area has a WIP limit."),
    ("blocked", "Blocked a Week or More", "Unblock, drop the reason, or park them in Backlog."),
    ("stale", "Stale", "In WIP or Ready with no board change for 14 days or more."),
    ("nonext", "No Next Action", "Give each one a concrete next step."),
    ("done", "Done This Week", "Since Monday."),
    ("ideas", "Waiting in Backlog", "Oldest first: promote to Ready, or archive."),
]


def wip_limits(env=None):
    """{area: limit} from KANBAN_WIP_LIMITS ("ops=4,docs=5"); other areas get WIP_LIMIT."""
    out = {}
    for part in (env if env is not None else os.environ.get("KANBAN_WIP_LIMITS", "")).split(","):
        area, _, n = part.partition("=")
        if area.strip() and n.strip().isdigit():
            out[area.strip()] = int(n)
    return out


def limit_of(area, limits):
    return limits.get(area, WIP_LIMIT)


def is_blocked(card):
    """Blocked when the column says so, a `waiting:` reason is set, or a dependency isn't done (deps.decorate)."""
    return card.get("board") == "blocked" or bool(card.get("waiting") or card.get("blocked_by") or card.get("_waiting_on"))


def blocked_since(card, events):
    """Date of the last move into Blocked, else the card's `updated` date, else None."""
    for ev in events:                                   # newest first
        ch = (ev.get("changes") or {}).get("board")
        if ev.get("type") == "move" and ch and ch[1] == "blocked":
            return local_date(ev.get("ts", ""))
    try:
        return datetime.date.fromisoformat((card.get("updated") or "")[:10])
    except ValueError:
        return None


def done_on(card, events, week_start):
    """The day a card was finished this week (completedDate or a move to done), else None."""
    try:
        d = datetime.date.fromisoformat((card.get("completedDate") or "")[:10])
        if d >= week_start:
            return d
    except ValueError:
        pass
    for ev in events:
        ch = (ev.get("changes") or {}).get("board")
        if ev.get("type") == "move" and ch and ch[1] == "done":
            d = local_date(ev.get("ts", ""))
            return d if d and d >= week_start else None
    return None


def build(cards, events_of, activity, limits=None, today=None):
    """{"sections": [(key, title, hint, [(card, [reasons])])], "areas": [(area, wip, limit)], "counts": {key: n}}.

    events_of(slug) -> that card's events, newest first. activity: slug -> last event ts."""
    today = today or datetime.date.today()
    limits = limits if limits is not None else wip_limits()
    week_start = today - datetime.timedelta(days=today.weekday())
    live = [c for c in cards if c.get("board") not in (None, "", "archived")]

    wip_by_area = {}
    for c in live:
        if c["board"] == "wip":
            wip_by_area.setdefault(c["area"], []).append(c)
    over = {a for a, cs in wip_by_area.items() if len(cs) > limit_of(a, limits)}
    areas = sorted(((a, len(cs), limit_of(a, limits)) for a, cs in wip_by_area.items()),
                   key=lambda t: (t[1] <= t[2], -(t[1] - t[2]), t[0]))

    reasons, placed, every = {}, {}, {}
    for c in live:
        slug, why = c["slug"], []
        evs = events_of(slug)
        if c["board"] == "wip" and c["area"] in over:
            why.append(("wip", "%s over its limit" % c["area"]))
        if is_blocked(c) and c["board"] not in ("done",):
            since = blocked_since(c, evs)
            days = (today - since).days if since else None
            if days is not None and days >= BLOCKED_DAYS:
                why.append(("blocked", "blocked %dd" % days))
        stale = stale_days(c, activity, today)
        if stale:
            c = dict(c, _stale=stale)
            why.append(("stale", "idle %dd" % stale))
        if c["board"] in ("wip", "ready") and not (c.get("next") or "").strip():
            why.append(("nonext", "no next action"))
        if c["board"] == "done":
            d = done_on(c, evs, week_start)
            if d:
                why.append(("done", "done %s" % d.strftime("%a")))
        if c["board"] == "backlog":
            try:
                age = (today - datetime.date.fromisoformat((c.get("created") or "")[:10])).days
            except ValueError:
                age = None
            why.append(("ideas", ("waiting %dd" % age) if age is not None else "waiting"))
        if why:
            order = [k for k, _, _ in SECTIONS]
            first = min(why, key=lambda w: order.index(w[0]))[0]
            placed.setdefault(first, []).append(c)
            # staleness already shows as the card's own "stale Nd" chip
            reasons[slug] = [text for key, text in why if key not in (first, "stale")]
            every[slug] = [{"key": key, "text": text} for key, text in why]

    def order_in(key, cs):
        if key == "wip":          # by area (most over first), then idle longest first
            rank = {a: i for i, (a, _, _) in enumerate(areas)}
            return sorted(cs, key=lambda c: (rank.get(c["area"], 99), -(c.get("_stale") or 0), sort_key(c)))
        if key in ("blocked", "stale"):
            return sorted(cs, key=lambda c: (-(c.get("_stale") or 0), sort_key(c)))
        if key == "ideas":
            return sorted(cs, key=lambda c: ((c.get("created") or "9999"), sort_key(c)))
        return sorted(cs, key=sort_key)

    sections = [(key, title, hint, [(c, reasons.get(c["slug"], [])) for c in order_in(key, placed.get(key, []))])
                for key, title, hint in SECTIONS]
    return {"sections": sections, "areas": areas, "counts": {k: len(v) for k, _, _, v in sections},
            "week_start": week_start, "reasons": every}


def as_json(data):
    """/api/review: the page's sections, each card once with every reason (the first is its section's)."""
    keep = ("slug", "title", "board", "area", "path", "priority", "next", "waiting", "updated")
    return {
        "week_start": data["week_start"].isoformat(),
        "counts": data["counts"],
        "areas": [{"area": a, "wip": n, "limit": lim, "over": n > lim} for a, n, lim in data["areas"]],
        "sections": [{"key": key, "title": title, "hint": hint,
                      "cards": [dict({k: c.get(k) for k in keep}, waiting_on=c.get("_waiting_on") or [],
                                     reasons=data["reasons"].get(c["slug"], [])) for c, _ in rows]}
                     for key, title, hint, rows in data["sections"]],
    }
