"""Goals (the Machiya frontmatter schema): a card names one goal in `goal:` and may carry
`due: YYYY-MM-DD`. Goals exist because cards name them (no goal notes). A goal's target is the latest `due` among
its cards; its progress is done/total of its cards (archived left out)."""
import datetime

DONE = ("done", "archived")


def due_date(card):
    try:
        return datetime.date.fromisoformat((card.get("due") or "")[:10])
    except ValueError:
        return None


def due_state(card, today=None):
    """'overdue' | 'soon' (within 7 days) | 'later' | None, for an unfinished card with a due date."""
    d = due_date(card)
    if not d or card.get("board") in DONE:
        return None
    days = (d - (today or datetime.date.today())).days
    return "overdue" if days < 0 else "soon" if days <= 7 else "later"


def build(cards, today=None):
    """[{"name", "cards", "done", "total", "target", "state"}], soonest target first (goals without one last)."""
    today = today or datetime.date.today()
    by = {}
    for c in cards:
        if c.get("board") and c.get("goal") and c["board"] != "archived":
            by.setdefault(c["goal"], []).append(c)
    out = []
    for name, cs in by.items():
        dues = [d for d in (due_date(c) for c in cs) if d]
        target = max(dues) if dues else None
        done = sum(1 for c in cs if c["board"] == "done")
        state = "done" if done == len(cs) else ("overdue" if target and target < today else
                                                 "soon" if target and (target - today).days <= 14 else "open")
        out.append({"name": name, "cards": sorted(cs, key=lambda c: (c["board"] == "done", due_date(c) or datetime.date.max,
                                                                     c["title"].lower())),
                    "done": done, "total": len(cs), "target": target, "state": state})
    return sorted(out, key=lambda g: (g["state"] == "done", g["target"] or datetime.date.max, g["name"].lower()))


def due_soon(cards, today=None, days=14):
    """Unfinished cards due within `days` or overdue, soonest first."""
    today = today or datetime.date.today()
    rows = [(due_date(c), c) for c in cards if c.get("board") and c["board"] not in DONE and due_date(c)]
    return [c for d, c in sorted(rows, key=lambda t: (t[0], t[1]["title"].lower())) if (d - today).days <= days]
