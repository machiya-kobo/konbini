"""Dated activity for the calendar and roundups.

Everything is derived from what's in git, so a rebuild or a fresh clone
gives the same history:

  - board events (.board/events/*.jsonl): moves to done/wip, new cards, notes
  - note frontmatter: `started` (or `date`) for project starts; for cards that
    were finished before the board existed, the last dated Log row or
    `last_activity` stands in for the end date (marked approximate)
  - Log tables in project notes (milestone/release/status rows)
  - change-log tables in Systems/: monthly notes Systems/Change Logs/<host> YYYY-MM.md (`host:` in the frontmatter), or
    the older Systems/<host>.md
  - the vault's git history, for commits that aren't covered above
"""
import datetime
import os
import re
import subprocess
from zoneinfo import ZoneInfo

from store import VAULT, _str, commit_filter
from vaultkit.notes import read_notes

TZ = ZoneInfo(os.environ.get("TZ") or "UTC")      # the board's days (calendar, roundups): set TZ in the deploy
ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|(.*)\|\s*$")
TAGS_RE = re.compile(r"#[\w/-]+")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# commits left out of the calendar: KANBAN_SKIP_COMMITS (everywhere) and KANBAN_CALENDAR_SKIP_COMMITS (commits the events
# and Log tables already cover), comma-separated subject prefixes
SKIP_COMMITS = commit_filter("KANBAN_SKIP_COMMITS", "KANBAN_CALENDAR_SKIP_COMMITS")

# Roundup sections, in display order.
SECTIONS = [
    ("done", "Done"),
    ("started", "Started"),
    ("milestone", "Milestones"),
    ("systems", "Systems"),
    ("idea", "New cards and ideas"),
    ("note", "Notes"),
    ("commit", "Other vault changes"),
]


class Item:
    __slots__ = ("date", "kind", "slug", "title", "text", "source", "approx", "cat")

    def __init__(self, date, kind, title, text="", slug="", source="", approx=False, cat=""):
        self.date, self.kind, self.title, self.text = date, kind, title, text
        self.slug, self.source, self.approx, self.cat = slug, source, approx, cat

    def as_dict(self):
        return {k: getattr(self, k) if k != "date" else self.date.isoformat() for k in self.__slots__}


def local_date(ts):
    """'2026-01-15T09:30:00Z' -> local date."""
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(TZ).date()


def parse_date(value):
    text = _str(value)[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def clean(text, limit=240):
    text = LINK_RE.sub(lambda m: (m.group(2) or m.group(1)).split("/")[-1], text)
    text = text.replace("<br>", "; ").replace("\\|", "|").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip(" ;")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "\u2026"


def log_rows(text):
    """Rows of any change-log style table: Date | Category | Change | Details | Status | Tags."""
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", m.group(2))]
        if len(cells) < 2:
            continue
        yield parse_date(m.group(1)), cells


def system_host(rel, fm):
    """The machine a Systems/ note's change log is about: its `host:` (a monthly note, "kiln 2026-10", says
    host: kiln), else its title, else its file name."""
    return _str(fm.get("host")) or _str(fm.get("title")) or os.path.splitext(os.path.basename(rel))[0]


class Timeline:
    def __init__(self, store):
        self.store = store
        self.repo = store.repo
        self._cache = (None, None)

    # -- sources -------------------------------------------------------

    def notes(self):
        """(rel, frontmatter, text) for every note, cached per git HEAD."""
        head = self.store.meta("head") + self.store.meta("rev")
        if self._cache[0] == head:
            return self._cache[1]
        out = read_notes(os.path.join(self.repo, VAULT))   # Templates/, dot dirs and LiveSync conflict copies left out
        self._cache = (head, out)
        return out

    def items(self, start, end):
        """Everything dated start <= date < end."""
        cards = {c["path"]: c for c in self.store.cards()}
        by_slug = {c["slug"]: c for c in cards.values()}
        items = []
        done_by_event, started_by_event = set(), set()

        # board events
        since = datetime.datetime.combine(start - datetime.timedelta(days=1), datetime.time()).isoformat()
        until = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time()).isoformat()
        for ev in self.store.events(since=since, until=until, limit=100000):
            d = local_date(ev.get("ts", ""))
            if not d or not start <= d < end:
                continue
            card = by_slug.get(ev.get("card"), {})
            title = card.get("title") or ev.get("card", "")
            who = ev.get("agent") if ev.get("agent") not in (None, "web", "api") else ""
            if ev.get("type") == "move":
                old, new = (ev.get("changes") or {}).get("board", [None, None])
                if new == "done":
                    items.append(Item(d, "done", title, card.get("summary", ""), ev["card"], "board"))
                    done_by_event.add(ev["card"])
                elif new == "wip" and old in (None, "backlog", "ready"):
                    items.append(Item(d, "started", title, "moved to WIP", ev["card"], "board"))
                    started_by_event.add(ev["card"])
            elif ev.get("type") == "create":
                items.append(Item(d, "idea", title, card.get("summary", ""), ev["card"], "board"))
            elif ev.get("type") == "comment":
                items.append(Item(d, "note", title, ev.get("body", "") + (" (%s)" % who if who else ""),
                                  ev["card"], "board"))

        for rel, fm, text in self.notes():
            card = cards.get(rel)
            slug = card["slug"] if card else ""
            title = _str(fm.get("title")) or os.path.splitext(os.path.basename(rel))[0]
            is_system = rel.startswith("Systems/")
            is_project = card is not None or "type/project" in (fm.get("tags") or [])

            if is_project and not is_system:
                explicit = parse_date(fm.get("started"))
                started = explicit or parse_date(fm.get("created"))
                if started and start <= started < end and slug not in started_by_event:
                    # Without `started:`, a note's creation date only counts as a
                    # start once the card is (or was) actually worked on.
                    kind = "started" if explicit or not card or card.get("board") in ("wip", "done", "archived") \
                        else "idea"
                    if kind == "idea" and any(i.kind == "idea" and i.slug == slug for i in items):
                        pass
                    else:
                        items.append(Item(started, kind, title, card.get("summary", "") if card else "",
                                          slug, "note"))

            for d, cells in log_rows(text):
                if not d or not start <= d < end:
                    continue
                category = cells[0].lower() if cells else ""
                change = clean(cells[1]) if len(cells) > 1 else ""
                details = clean(cells[2]) if len(cells) > 2 else ""
                if is_system:
                    host = system_host(rel, fm)
                    items.append(Item(d, "systems", host, change, "", "log:" + rel))
                elif is_project:
                    if category == "start" or (category == "status" and "done" in change.lower()):
                        continue  # covered by started/done
                    text_ = change + (": " + details if details and len(details) < 140 else "")
                    items.append(Item(d, "milestone", title, text_, slug, "log:" + rel, cat=category))

            # Finished before the board existed: approximate the end date.
            if card and card.get("board") == "done" and slug not in done_by_event:
                last = max((d for d, _ in log_rows(text) if d), default=None)
                completed = parse_date(fm.get("completedDate"))
                end_date = completed or last or parse_date(fm.get("last_activity")) or parse_date(fm.get("updated"))
                if end_date and start <= end_date < end and not self.store.events(card=slug, limit=1):
                    items.append(Item(end_date, "done", title, card.get("summary", ""), slug, "note", approx=not completed))

        items.extend(self.commits(start, end))
        items.sort(key=lambda i: (i.date, i.kind, i.title.lower()))
        return items

    def commits(self, start, end):
        out = self.store.git("log", "--since=%s 00:00" % start.isoformat(), "--until=%s 00:00" % end.isoformat(),
                             "--format=%aI\x1f%an\x1f%s")
        items, seen = [], set()
        for line in out.splitlines():
            try:
                when, author, subject = line.split("\x1f", 2)
            except ValueError:
                continue
            if SKIP_COMMITS.match(subject):
                continue  # covered by board events and Log tables
            d = local_date(when)
            if d and start <= d < end and subject not in seen:
                seen.add(subject)
                items.append(Item(d, "commit", subject[:140], author, "", "git"))
        return items

    # -- periods -------------------------------------------------------

    @staticmethod
    def period(kind, anchor):
        if kind == "day":
            start = anchor
            end = anchor + datetime.timedelta(days=1)
            label = anchor.strftime("%A %Y-%m-%d")
        elif kind == "week":
            start = anchor - datetime.timedelta(days=anchor.weekday())
            end = start + datetime.timedelta(days=7)
            label = "Week of %s (ISO %d-W%02d)" % (start.isoformat(), *start.isocalendar()[:2])
        elif kind == "year":
            start = datetime.date(anchor.year, 1, 1)
            end = datetime.date(anchor.year + 1, 1, 1)
            label = str(anchor.year)
        else:
            kind = "month"
            start = anchor.replace(day=1)
            end = (start + datetime.timedelta(days=32)).replace(day=1)
            label = start.strftime("%B %Y")
        prev = start - datetime.timedelta(days=1)
        return kind, start, end, label, prev, end

    def roundup(self, kind, anchor):
        kind, start, end, label, prev, nxt = self.period(kind, anchor)
        items = self.items(start, end)
        sections = []
        for key, name in SECTIONS:
            rows = [i for i in items if i.kind == key]
            if key in ("milestone", "systems", "note"):
                # group by project/host to keep long periods readable
                groups = {}
                for i in rows:
                    groups.setdefault((i.title, i.slug), []).append(i)
                rows = [(t, s, g) for (t, s), g in sorted(groups.items(), key=lambda kv: kv[0][0].lower())]
            if rows:
                sections.append((key, name, rows))
        if kind in ("month", "year"):
            # finished projects nobody has written up yet (the writing kit is one click away)
            posts = {c["slug"]: c.get("post") for c in self.store.cards()}
            rows = [i for i in items if i.kind == "done" and posts.get(i.slug) not in ("published", "skipped")]
            if rows:
                sections.append(("write", "Write about it", rows))
        return {"kind": kind, "start": start, "end": end, "label": label, "prev": prev, "next": nxt,
                "sections": sections, "count": len(items)}

    def markdown(self, r):
        lines = ["## Roundup: %s" % r["label"], ""]
        for key, name, rows in r["sections"]:
            lines.append("### " + name)
            for row in rows:
                if isinstance(row, tuple):
                    title, _slug, group = row
                    if len(group) == 1:
                        lines.append("- **%s**: %s%s" % (title, group[0].text, "" if r["kind"] == "day" else
                                                         " (%s)" % group[0].date.strftime("%b %d")))
                    else:
                        lines.append("- **%s**" % title)
                        lines.extend("  - %s%s" % (i.text, "" if r["kind"] == "day" else " (%s)" % i.date.strftime("%b %d"))
                                     for i in group)
                elif key == "commit":
                    lines.append("- %s" % row.title)
                else:
                    extra = (": " + row.text) if row.text else ""
                    when = "" if r["kind"] == "day" else " (%s%s)" % ("~" if row.approx else "", row.date.strftime("%b %d"))
                    lines.append("- **%s**%s%s" % (row.title, extra, when))
            lines.append("")
        if not r["sections"]:
            lines.append("_Nothing recorded._")
        return "\n".join(lines).rstrip() + "\n"

    def span(self, card, fm):
        """(start, end) of a card's work: `started` (else `created`/`date`) to the day it moved to done (else
        `completedDate`, else its last activity); end is None while it's open."""
        s = parse_date(fm.get("started")) or parse_date(fm.get("created"))
        e = None
        if card.get("board") in ("done", "archived"):
            evs = [ev for ev in self.store.events(card=card["slug"], limit=200)
                   if ev.get("type") == "move" and (ev.get("changes") or {}).get("board", [0, 0])[1] == "done"]
            e = local_date(evs[0]["ts"]) if evs else (parse_date(fm.get("completedDate")) or parse_date(fm.get("last_activity"))
                                                      or parse_date(fm.get("updated")))
        return s, e

    def range(self, start, end, cards, group="area"):
        """The timeline (/timeline): cards whose work overlaps [start, end) or that are due in it, grouped by area
        or stream: {"groups": [(name, [row])]}, row = {"card", "start", "end", "due", "milestones": [(date, text)]}.
        Backlog cards without a `started` date only show when they're due in the range."""
        notes = {r: (f, t) for r, f, t in self.notes()}
        groups = {}
        for c in cards:
            if not c.get("board"):
                continue
            fm, text = notes.get(c["path"], ({}, ""))
            s, e = self.span(c, fm)
            due = parse_date(c.get("due"))
            if c["board"] == "backlog" and not parse_date(fm.get("started")):
                s = None
            if c["board"] == "archived" and not e:
                continue                        # archived with no known finish: no honest bar to draw
            if c["board"] == "done" and not e:
                e = s                           # finished, date unknown: a one-day mark, not an open bar
            working = s and s < end and (e is None or e >= start)
            if not working and not (due and start <= due < end):
                continue
            miles = []
            for d, cells in log_rows(text):
                category = cells[0].lower() if cells else ""
                if d and start <= d < end and not (category == "start" or (category == "status" and "done" in (cells[1] if len(cells) > 1 else "").lower())):
                    miles.append((d, clean(cells[1]) if len(cells) > 1 else category))
            key = (c.get("stream") or "no stream") if group == "stream" else c["area"]
            groups.setdefault(key, []).append({"card": c, "start": s if working else None, "end": e, "due": due,
                                               "milestones": miles[:12]})
        order = sorted(groups, key=lambda k: (k in ("no stream",), k.lower()))
        return {"groups": [(k, sorted(groups[k], key=lambda r: (r["start"] or r["due"] or end, r["card"]["title"].lower())))
                           for k in order]}

    def month(self, anchor):
        start = anchor.replace(day=1)
        end = (start + datetime.timedelta(days=32)).replace(day=1)
        items = self.items(start, end)
        days = {}
        for i in items:
            if i.kind in ("done", "started", "milestone", "systems", "idea"):
                days.setdefault(i.date, []).append(i)
        # project spans overlapping the month
        spans = []
        notes = {r: f for r, f, _ in self.notes()}
        for c in self.store.cards():
            if not c.get("board"):
                continue
            s, e = self.span(c, notes.get(c["path"], {}))
            if s and s < end and (e is None or e >= start):
                spans.append((s, e, c))
        spans.sort(key=lambda t: (t[0], t[2]["title"].lower()))
        return {"start": start, "end": end, "days": days, "spans": spans,
                "prev": start - datetime.timedelta(days=1), "next": end}


def today():
    return datetime.datetime.now(TZ).date()
