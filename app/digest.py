"""The board half of the stream, served at /api/digest.

The stream itself is Niwa's (machiya-kobo/niwa: stream.py renders it and adds the garden
half: planted, tended, stages, suggestions, links that died). Konbini computes what only the board knows: a
"now" block (WIP and Blocked cards with their next step) and, for the last N days, one entry per project per
day (column moves, the one or two most significant Log rows, a count of everything else, the next step) plus
machine change logs collapsed to one entry per host per day. Vault housekeeping commits are hidden and agent
chatter folds into the counts."""
import datetime

from store import VAULT, sort_key
from timeline import local_date, today

RANK = {"release": 0, "milestone": 1, "status": 2}
LABEL = {"backlog": "Backlog", "ready": "Ready", "wip": "WIP", "blocked": "Blocked", "done": "Done",
         "archived": "Archived", None: "new", "": "new"}


def _entry(slug, date):
    return {"kind": "project", "slug": slug, "date": date, "title": "", "moves": [], "rows": [], "updates": 0}


def _top(rows, n=2):
    seen, out = set(), []
    for rank, text in sorted(rows, key=lambda r: r[0]):
        if text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= n:
            break
    return out


def window(days):
    end = today() + datetime.timedelta(days=1)
    return end - datetime.timedelta(days=days + 1), end


def board_part(store, timeline, start, end, published):
    """The board half of the stream: (now, entries). now = WIP and Blocked cards with their next step; entries =
    one per project per day (moves, top Log rows, counts) plus one per host per day (systems). `published` maps a
    note path to its published garden note ({} when the garden isn't known: then note_slug is empty and callers
    use the entry's `path`). Served at /api/digest for Niwa, which adds the garden half."""
    cards = {c["slug"]: c for c in store.cards()}
    claims = store.claims()

    # -- now: what is in progress ------------------------------------------------
    def brief(c):
        claim = claims.get(c["slug"])
        note = published.get(c["path"])
        return {"slug": c["slug"], "title": c["title"], "next": c.get("next") or "", "board": c["board"],
                "blocked_by": c.get("blocked_by") or "", "updated": c.get("updated") or "",
                "claim": (claim["agent"] if claim["agent"] not in ("web", "api") else claim["actor"]) if claim else "",
                "note_slug": note.slug if note else "", "area": c.get("area") or ""}
    now = {"wip": [brief(c) for c in sorted((c for c in cards.values() if c["board"] == "wip"), key=sort_key)],
           "blocked": [brief(c) for c in sorted((c for c in cards.values() if c["board"] == "blocked"), key=sort_key)]}

    # -- buckets: project x day --------------------------------------------------
    buckets, systems = {}, {}

    def bucket(slug, d, title):
        b = buckets.get((slug, d))
        if not b:
            b = buckets[(slug, d)] = _entry(slug, d)
        b["title"] = b["title"] or title
        return b

    for i in timeline.items(start, end):
        if i.kind == "commit":
            continue  # vault housekeeping stays out of the stream
        if i.kind == "systems":
            systems[(i.title, i.date)] = systems.get((i.title, i.date), 0) + 1
            continue
        b = bucket(i.slug or i.title, i.date, i.title)
        if i.kind == "milestone":
            b["rows"].append((RANK.get(i.cat, 3), i.text))
        elif i.kind == "done":
            if i.source != "board":  # finished before the board existed
                b["rows"].append((0, "finished" + (" (approximate date)" if i.approx else "")))
        elif i.kind == "started":
            if i.source != "board":
                b["rows"].append((1, "started"))
        elif i.kind == "idea":
            b["rows"].append((2, "new card"))
        elif i.kind == "note":
            b["updates"] += 1  # log lines and comments fold into the count

    since = datetime.datetime.combine(start - datetime.timedelta(days=1), datetime.time()).isoformat()
    until = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time()).isoformat()
    for ev in store.events(since=since, until=until, limit=100000):
        d = local_date(ev.get("ts", ""))
        if not d or not start <= d < end:
            continue
        kind = ev.get("type")
        card = cards.get(ev.get("card"), {})
        if kind == "move":
            old, new = (ev.get("changes") or {}).get("board", [None, None])
            b = bucket(ev["card"], d, card.get("title") or ev["card"])
            b["moves"].append((LABEL.get(old, old), LABEL.get(new, new)))
        elif kind == "edit":
            bucket(ev["card"], d, card.get("title") or ev["card"])["updates"] += 1

    # -- entries -----------------------------------------------------------------
    def finish(b):
        c = cards.get(b["slug"], {})
        note = published.get(c.get("path"))
        moves = []
        for old, new in b["moves"]:
            if moves and moves[-1][1] == old:
                moves[-1] = (moves[-1][0], new)  # chain A → B → C into A → C
            else:
                moves.append((old, new))
        round_trips = sum(1 for m in moves if m[0] == m[1])  # out and back the same day: just an update
        moves = [m for m in moves if m[0] != m[1]]
        top = _top(b["rows"])
        return {"kind": "project", "slug": b["slug"], "date": b["date"], "title": b["title"] or c.get("title") or b["slug"],
                "moves": ["%s → %s" % m for m in moves], "top": top,
                "more": max(0, len(b["rows"]) - len(top)) + b["updates"] + round_trips,
                "next": c.get("next") or "", "board": c.get("board") or "", "area": c.get("area") or "",
                "note_slug": note.slug if note else "", "has_card": bool(c), "path": c.get("path") or "",
                "done": any(m[1] == "Done" for m in moves) or any(r[1].startswith("finished") for r in b["rows"]),
                "started": any(m[1] == "WIP" and m[0] in ("Backlog", "Ready", "new") for m in moves)
                or any(r[1] == "started" for r in b["rows"]),
                "rows_n": len(b["rows"])}

    entries = [finish(b) for b in buckets.values()]
    entries += [{"kind": "systems", "date": d, "host": host, "count": n} for (host, d), n in systems.items()]
    return now, entries
