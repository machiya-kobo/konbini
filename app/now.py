"""What's being worked on: the Now page and GET /api/now (the Machiya konbini-api contract).

A card is working when something happened to it in the window (common.NOW_DAYS, the board's days), from any of:

  - commits on the card's repos: the read-only checkout under KANBAN_REPOS (the writing kit's) when there is one, else
    the dated "Recent commits" lines (and `last_commit`) of the vault's repo note, `<name>.git.md`, matched to the
    card's `repos` by name or by the last segment of the note's forgejo/github URL
  - board events (not a drag-and-drop reorder) and live claims
  - change-log rows (Systems/Change Logs/) with a [[link]] to the card's note
  - the card's own Log rows

The line a card shows is the latest thing that happened: from its latest day, and on that day from the heaviest source,
in that order (agents add Log rows in batches, so they count least). WIP cards with nothing in the window are quiet.
Change-log rows in the window that link no card are listed by host, read-only: nothing here proposes a card. Rows the
triage agent wrote (the change text starts with the robot emoji) are left out of that list, since incidents track them;
one that links a card still counts as that card's activity.
"""
import datetime
import os
import re
import subprocess
import threading
import time

from common import NOW_DAYS, now_since
from store import commit_filter, repo_name
from timeline import LINK_RE, clean, log_rows, parse_date, system_host

CHANGE_LOGS = "Systems/Change Logs/"
TRIAGE_MARK = "\U0001F916"                     # the triage agent's rows start with the robot emoji
WEIGHT = {"commit": 3, "event": 2, "claim": 2, "changelog": 1, "log": 0}
COMMIT_RE = re.compile(r"^\s*[-*]\s+(\d{4}-\d{2}-\d{2}):\s+(.+?)\s*$")
COLUMN = {"backlog": "Backlog", "ready": "Ready", "wip": "WIP", "blocked": "Blocked", "done": "Done", "archived": "Archived"}


def event_text(ev):
    """A board event as a plain line, or "" for one that isn't work (a reorder). Names an agent, never a login."""
    kind, ch = ev.get("type", ""), ev.get("changes") or {}
    if kind == "move" and "board" in ch:
        text = "Moved to " + COLUMN.get(ch["board"][1], ch["board"][1] or "?")
        if ev.get("outcome") == "wontdo":
            text += " (won't do)"
    elif kind == "edit":
        keys = [k for k in ch if k != "rank"]
        if not keys:
            return ""
        nxt = ch.get("next")
        if keys == ["next"] and isinstance(nxt, list) and nxt[1:] and nxt[1]:
            text = "Next: " + nxt[1]
        else:
            text = "Edited " + ", ".join(keys)
    elif kind == "comment":
        text = ev.get("body", "")
    elif kind == "create":
        text = "Created in " + COLUMN.get(ev.get("board"), ev.get("board") or "?")
    elif kind == "topic_created":
        text = "Created the tag " + ev.get("tag", "")
    else:
        text = kind
    who = ev.get("agent") if ev.get("agent") not in (None, "", "web", "api") else ""
    return clean(text) + (" (%s)" % who if who else "")


SKIP_COMMITS = commit_filter("KANBAN_SKIP_COMMITS")


class Checkouts:
    """Commits from the read-only checkouts under `root` (KANBAN_REPOS), one directory per repo name, matched without
    regard to case: name -> [(UTC ts, subject)] newest first, or None without a checkout. One `git log` per repo,
    kept for `ttl` seconds."""

    def __init__(self, root, ttl=120):
        self.root, self.ttl = root, ttl
        self.lock = threading.Lock()
        self.cache = {}

    def __call__(self, name):
        try:
            dirs = {d.lower(): d for d in os.listdir(self.root)}
        except OSError:
            return None
        path = os.path.join(self.root, dirs.get(name.lower(), ""))
        if name.lower() not in dirs or not os.path.isdir(os.path.join(path, ".git")):
            return None
        with self.lock:
            hit = self.cache.get(path)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        try:
            out = subprocess.run(["git", "-C", path, "log", "-n", "200", "--format=%cI\x1f%s"], capture_output=True,
                                 text=True, timeout=20, check=True).stdout
        except (subprocess.SubprocessError, OSError):
            out = None
        commits = None
        if out is not None:
            commits = []
            for line in out.splitlines():
                when, _, subject = line.partition("\x1f")
                try:
                    ts = datetime.datetime.fromisoformat(when).astimezone(datetime.timezone.utc)
                except ValueError:
                    continue
                if not SKIP_COMMITS.match(subject):
                    commits.append((ts.strftime("%Y-%m-%dT%H:%M:%SZ"), subject))
        with self.lock:
            self.cache[path] = (time.time(), commits)
        return commits


def repo_index(notes):
    """lowercased repo name -> [(rel, name, [(date, subject)], last_commit date or None)] from the vault's repo notes."""
    out = {}
    for rel, fm, text in notes:
        base = os.path.basename(rel)
        if not base.lower().endswith(".git.md"):
            continue
        name = base[:-7]
        commits = [(parse_date(m.group(1)), m.group(2)) for m in map(COMMIT_RE.match, text.splitlines()) if m]
        entry = (rel, name, [(d, s) for d, s in commits if d], parse_date(fm.get("last_commit")))
        for n in {name.lower()} | {repo_name(fm.get(k)).lower() for k in ("forgejo", "github")} - {""}:
            out.setdefault(n, []).append(entry)
    return out


def build(cards, notes, events, last_events, claims, resolve, today, tz, now=None, checkouts=None):
    """The /api/now answer. cards: the board's cards; notes: (rel, frontmatter, text) for the vault; events: the board
    events since the window's start (newest first); last_events: slug -> its latest event's ts, all time; claims: the
    live claims; resolve: a [[link]] target -> a note's rel or None (vaultkit's rule); checkouts: a Checkouts."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now_since(today, tz)
    start = since.date()
    by_path = {c["path"]: c for c in cards if c.get("board")}
    by_slug = {c["slug"]: c for c in by_path.values()}
    acts = {slug: [] for slug in by_slug}           # slug -> activity in the window
    last = {}                                       # slug -> (day, ts) of its latest activity, all time

    def local_day(ts):
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(tz).date()
        except (ValueError, AttributeError):
            return None

    def seen(slug, day, ts, source, line, seq=0):
        if slug not in acts or not day or day > today:
            return
        if day >= start and line:
            acts[slug].append((day, WEIGHT[source], ts, seq, source, line))
        if (day, ts) > last.get(slug, (datetime.date.min, "")):
            last[slug] = (day, ts)

    # commits on the card's repos
    repos = repo_index(notes)
    for c in by_path.values():
        done = set()
        for r in c.get("repos") or []:
            local = checkouts(r) if checkouts else None
            if local is not None:
                for i, (ts, subject) in enumerate(local):
                    line = subject if subject.lower().startswith(r.lower() + ":") else "%s: %s" % (r, subject)
                    seen(c["slug"], local_day(ts), ts, "commit", clean(line), -i)
                continue
            for rel, name, commits, last_commit in repos.get(r.lower(), []):
                if rel in done:
                    continue
                done.add(rel)
                for i, (d, subject) in enumerate(commits):
                    line = subject if subject.lower().startswith(name.lower() + ":") else "%s: %s" % (name, subject)
                    seen(c["slug"], d, d.isoformat(), "commit", clean(line), -i)        # the list is newest first
                if last_commit and not any(d == last_commit for d, _ in commits):
                    seen(c["slug"], last_commit, last_commit.isoformat(), "commit", "Committed to " + name, -len(commits))

    # board events and claims
    for ev in events:
        text = event_text(ev)
        if text:                                    # a reorder isn't work
            seen(ev.get("card"), local_day(ev.get("ts", "")), ev.get("ts", ""), "event", text)
    for slug, ts in (last_events or {}).items():
        seen(slug, local_day(ts or ""), ts or "", "event", "")
    stamp = now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for slug, claim in (claims or {}).items():
        who = claim.get("agent") if claim.get("agent") not in (None, "", "web", "api") else ""
        seen(slug, now.astimezone(tz).date(), stamp, "claim", "Claimed by " + who if who else "Claimed")

    # change-log rows: a row with a [[link]] to a card counts for that card; the others are listed by host, except the triage
    # agent's (incidents track those)
    uncarded = {}
    for rel, fm, text in notes:
        if not rel.startswith(CHANGE_LOGS):
            continue
        host = system_host(rel, fm)
        for i, (d, cells) in enumerate(log_rows(text)):
            if not d or d > today:
                continue
            change = clean(cells[1]) if len(cells) > 1 else ""
            named = {by_path[p]["slug"] for p in (resolve(m.group(1)) for m in LINK_RE.finditer(" | ".join(cells)))
                     if p in by_path}
            for slug in named:
                seen(slug, d, d.isoformat(), "changelog", "%s: %s" % (host, change), -i)    # a change log is newest first
            if not named and d >= start and not change.startswith(TRIAGE_MARK):
                uncarded.setdefault(host, []).append({"date": d.isoformat(), "change": change, "path": rel})

    # the card's own Log rows
    notes_at = {rel: text for rel, _, text in notes if rel in by_path}
    for rel, c in by_path.items():
        for i, (d, cells) in enumerate(log_rows(notes_at.get(rel, ""))):
            change = clean(cells[1]) if len(cells) > 1 else ""
            seen(c["slug"], d, d.isoformat() if d else "", "log", change, i)               # a Log table is oldest first

    working = []
    for slug, items in acts.items():
        if items:
            day, weight, ts, seq, source, line = max(items, key=lambda a: a[:4])
            c = by_slug[slug]
            working.append(((day, weight, ts), {"slug": slug, "title": c["title"], "path": c["path"], "board": c["board"],
                                                "at": ts, "line": line, "source": source, "live": []}))
    working.sort(key=lambda t: t[1]["title"].lower())
    working.sort(key=lambda t: t[0], reverse=True)
    quiet = sorted(({"slug": c["slug"], "title": c["title"], "path": c["path"],
                     "last_at": last[c["slug"]][1] if c["slug"] in last else None}
                    for c in by_slug.values() if c["board"] == "wip" and not acts[c["slug"]]),
                   key=lambda q: (last.get(q["slug"], (datetime.date.min, "")), q["title"].lower()))
    hosts = sorted(uncarded, key=lambda h: (-max(datetime.date.fromisoformat(r["date"]).toordinal() for r in uncarded[h]),
                                            h.lower()))
    return {"days": NOW_DAYS, "since": since.isoformat(), "working": [w for _, w in working], "quiet": quiet,
            "uncarded": [{"host": h, "rows": sorted(uncarded[h], key=lambda r: r["date"], reverse=True)} for h in hosts],
            "live": []}
