"""Card index: parse vault note frontmatter into SQLite.

The notes are the source of truth. This database is a cache that `rebuild`
recreates from a clone of the vault repo at any time: a card is any note
in the notes folder whose frontmatter has a board column as `status:` (the
Machiya frontmatter schema). Notes tagged
type/project without one land in the Unsorted tray.

Field names follow the Machiya frontmatter schema (`status`, `waiting`, `priority`
as high/normal/low, `created`); the old names (`board`, `blocked_by`,
`date`, integer `priority`, `status/*` tags) are not read. A note that still
carries one is listed in Store.legacy (logged at import, shown on /api/status) so a
stale sync shows up instead of a card quietly vanishing. The card dict keeps its
/api/cards keys (`board` = the column, `priority` 1-3, `blocked_by` = the waiting
text, `status` = the old-style value derived from the column) with the newer fields
beside them.
"""
import datetime
import json
import os
import re
import sqlite3
import subprocess
import threading
import time

import yaml

# Frontmatter, conflict markers, LiveSync conflict copies: shared with Kura and Niwa (vendored, see app/vaultkit/).
from vaultkit.front import (CONFLICT_RE, FRONT_RE, PHONE_CONFLICT, WIKILINK_RE, _str, _unlink,  # noqa: F401
                            note_front, tags_of)
from vaultkit.notes import RACY_NS, read_file

def commit_filter(*settings):
    """The commit subjects the calendar, roundups and kits leave out: the board's own (`board: `) and merges, plus the
    comma-separated prefixes in the given settings (case-insensitive), e.g. KANBAN_SKIP_COMMITS="nightly backup,wip"."""
    prefixes = ["board: ", "Merge "]
    for name in settings:
        prefixes += [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]
    return re.compile("^(?:%s)" % "|".join(re.escape(p) for p in prefixes), re.I)


# The folder of the repo that holds the notes (the rest of the repo is ignored); KANBAN_REPO_SUBDIR, default: the repo
# root (""). GIT_SCOPE is the same as a git pathspec.
VAULT = os.environ.get("KANBAN_REPO_SUBDIR", "").strip().strip("/")
if ".." in VAULT.split("/"):
    raise SystemExit("konbini: KANBAN_REPO_SUBDIR must be a folder inside the repo, not %r" % VAULT)
GIT_SCOPE = VAULT or "."
COLUMNS = ["backlog", "ready", "wip", "blocked", "done", "archived"]
COLUMN_TITLES = {
    "backlog": "Backlog", "ready": "Ready", "wip": "WIP",
    "blocked": "Blocked / On Hold", "done": "Done", "archived": "Archived",
}
WIP_LIMIT = 3
# The old-style status value for a column: /api/cards keeps exposing it as a card's `status` (Niwa and Shiori read it).
STATUS_FOR = {"backlog": "draft", "ready": "active", "wip": "active",
              "blocked": "on-hold", "done": "archive", "archived": "archive"}
NOTE_STATUSES = ("draft", "active", "archive", "on-hold")      # `status:` on notes that aren't cards
PRIORITY_WORDS = {"high": 1, "normal": 2, "low": 3}
PRIORITY_NAMES = {v: k for k, v in PRIORITY_WORDS.items()}
POST_STATES = ("none", "idea", "outlined", "drafting", "published", "skipped")
SKIP_DIRS = {"Templates", ".obsidian", ".trash"}

CHECK_RE = re.compile(r"^\s*[-*] \[([ xX])\]", re.M)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    slug TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    board TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    card TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS events_card_ts ON events (card, ts);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS events_client ON events (json_extract(data, '$.client_id'));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS links (
    url TEXT PRIMARY KEY, first_seen TEXT, last_checked TEXT, status TEXT, http INTEGER, fails INTEGER,
    archive_url TEXT, archived_at TEXT, backend TEXT, died_at TEXT, notes TEXT,
    private_url TEXT, private_at TEXT, private_backend TEXT, private_checked TEXT);
CREATE TABLE IF NOT EXISTS tags (tag TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS claims (
    card TEXT PRIMARY KEY,
    actor TEXT,
    agent TEXT,
    expires REAL NOT NULL
);
"""


def file_key(st):
    """What tells that a file is unchanged: device, inode, size and both times. None when it changed so recently that a
    second change in the same (coarse) clock tick would go unseen (git's "racy" rule), so it is read again next time."""
    key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    return None if max(st.st_mtime_ns, st.st_ctime_ns) >= time.time_ns() - RACY_NS else key


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "card"


def parse_note(text, rel, fm=None):
    """Return a card dict for a note, or None if it isn't a card. fm: the note's frontmatter when the caller has parsed it
    already (scan does: parsing YAML twice per note was half of an import)."""
    m = FRONT_RE.match(text)
    if not m:
        return None
    if not isinstance(fm, dict):
        try:
            fm = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            return None
    if not isinstance(fm, dict):
        return None

    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    tags = [str(t).lstrip("#").strip() for t in tags if t]

    status_field = _str(fm.get("status")).lower()
    board = status_field if status_field in COLUMNS else ""
    if not board and "type/project" not in tags:
        return None

    stem = os.path.splitext(os.path.basename(rel))[0]
    areas = [t[5:] for t in tags if t.startswith("area/") and t != "area/projects"]
    body = text[m.end():]
    checks = CHECK_RE.findall(body)

    priority = parse_priority(fm.get("priority"))
    waiting = _str(fm.get("waiting"))

    return {
        "slug": _str(fm.get("project")) or slugify(stem),
        "title": _str(fm.get("title")) or stem,
        "path": rel,
        "board": board or None,
        "priority": priority,
        "summary": _str(fm.get("summary")),
        "next": _str(fm.get("next")),
        "blocked_by": waiting,
        "waiting": waiting,
        "area": areas[0] if areas else "projects",
        "areas": areas,
        "effort": next((t[7:] for t in tags if t.startswith("effort/")), ""),
        "topics": [t[6:] for t in tags if t.startswith("topic/")],
        "machines": [t[8:] for t in tags if t.startswith("machine/")],
        "type": next((t[5:] for t in tags if t.startswith("type/")), ""),
        "status": (status_field if status_field in NOTE_STATUSES else "") or STATUS_FOR.get(board, ""),
        "tags": tags,
        "family": _unlink(fm.get("family")),
        "repo": _str(fm.get("repo")),
        "publish": bool(fm.get("publish")),
        "growth": _str(fm.get("growth")),
        "updated": _str(fm.get("updated") or fm.get("last_activity") or fm.get("created")),
        "created": _str(fm.get("created"))[:10],
        "started": _str(fm.get("started"))[:10],
        "completedDate": _str(fm.get("completedDate"))[:10],
        "due": _str(fm.get("due"))[:10],
        "stream": _unlink(fm.get("stream")),
        "goal": _unlink(fm.get("goal")),
        "dependsOn": links_of(fm.get("dependsOn")),
        # blog post tracking (writing kits): post: none|idea|outlined|drafting|published; a bare
        # post_url (or the older blog: field) counts as published
        "post_url": _str(fm.get("post_url") or fm.get("blog")),
        "post": (_str(fm.get("post")).lower() if _str(fm.get("post")).lower() in POST_STATES else "")
                or ("published" if _str(fm.get("post_url") or fm.get("blog")) else ""),
        "rank": fm.get("rank") if isinstance(fm.get("rank"), (int, float)) else None,
        "checks_done": sum(1 for c in checks if c.lower() == "x"),
        "checks_total": len(checks),
    }


def parse_priority(value):
    """high/normal/low -> 1/2/3 (the integer is what /api/cards exposes); anything else, including the old 1-3, -> None."""
    if isinstance(value, str) and value.strip().lower() in PRIORITY_WORDS:
        return PRIORITY_WORDS[value.strip().lower()]
    return None


def legacy_names(fm, tags):
    """The old field names a note still carries (they are not read): board, blocked_by, date,
    an integer priority, status/* tags."""
    out = [k for k in ("board", "blocked_by", "date") if k in fm]
    if str(fm.get("priority", "")).strip() in ("1", "2", "3"):
        out.append("priority")
    if any(t.startswith("status/") for t in tags):
        out.append("status/*")
    return out


def links_of(value):
    """dependsOn: a list of "[[Note]]" links (or one) -> link targets, without [[ ]] or |alias."""
    items = value if isinstance(value, list) else ([value] if value else [])
    out = []
    for item in items:
        m = WIKILINK_RE.search(_str(item))
        target = (m.group(1) if m else _str(item)).strip()
        if target and target not in out:
            out.append(target)
    return out


class Store:
    def __init__(self, db_path, repo):
        self.repo = repo
        self.lock = threading.Lock()
        self._said = set()          # local-only git conditions already reported (see git())
        self.broken = []            # [(path, reason)] notes that look like cards but don't parse
        self.legacy = []            # [{slug, path, field}] notes still carrying the old field names (not read)
        self.phone_conflicts = []   # LiveSync conflict copies waiting to be merged
        self._scanned = {}          # path -> (file_key, what read_note made of it): see scan
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(links)")}
        for col in ("private_url", "private_at", "private_backend", "private_checked"):  # added for Hister
            if col not in have:
                self.db.execute("ALTER TABLE links ADD COLUMN %s TEXT" % col)
        self.db.commit()

    # -- import --------------------------------------------------------

    def scan(self, fresh=False):
        """Every card in the notes folder, and the book-keeping of the import (broken and legacy notes, the tags in use).
        A note whose modification time, size and inode are as at the last scan isn't read or parsed again (parsing YAML
        is most of an import's time); fresh=True reads everything, as the periodic drift check does."""
        root = os.path.join(self.repo, VAULT)
        cards, seen, broken, phone, legacy = [], set(), [], [], []
        self.all_tags = set()
        old, kept = ({} if fresh else self._scanned), {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                if os.path.islink(full):        # a link is never a note (vaultkit v0.22: read_notes skips them too)
                    continue
                rel = os.path.relpath(full, root)
                if PHONE_CONFLICT in name:
                    phone.append(rel)
                    continue
                try:
                    key = file_key(os.stat(full))
                    hit = old.get(full)
                    if key is not None and hit and hit[0] == key:
                        info = hit[1]
                    else:
                        text = read_file(full)
                        if text is None:            # not a regular file
                            continue
                        info = self.read_note(text, rel, note_front(text))
                except OSError:
                    continue
                kept[full] = (key, info)
                tags, why, old_names, card = info
                self.all_tags.update(tags)
                if why:
                    broken.append((rel, why))
                if old_names:
                    legacy.append({"slug": (card or {}).get("slug", ""), "path": rel, "field": ", ".join(old_names)})
                if not card:
                    continue
                card = dict(card)               # the slug may change below; the cached one doesn't
                slug, n = card["slug"], 2
                while card["slug"] in seen:
                    card["slug"] = "%s-%d" % (slug, n)
                    n += 1
                seen.add(card["slug"])
                cards.append(card)
        if not fresh:
            self._scanned = kept
        self.broken = broken
        self.phone_conflicts = sorted(phone)
        self.legacy = legacy
        for rel, why in broken:
            print("import: %s: %s" % (rel, why), flush=True)
        seen_before = getattr(self, "_legacy_logged", set())
        now = {(x["path"], x["field"]) for x in legacy}
        for path, field in sorted(now - seen_before):        # once per note and field set, not on every import
            print("import: %s: old field names ignored: %s (see the Machiya frontmatter schema)" % (path, field), flush=True)
        self._legacy_logged = now
        return cards

    @staticmethod
    def read_note(text, rel, fm):
        """(tags, why it is broken or "", old field names, card or None) for one note's text and frontmatter."""
        tags = tags_of(fm)
        why = ""
        if CONFLICT_RE.search(text):
            why = "unresolved git conflict markers"
        elif fm is None and FRONT_RE.match(text) and re.search(r"^(status:|  - type/project)", text, re.M):
            why = "frontmatter doesn't parse"
        card = parse_note(text, rel, fm)
        return tags, why, (legacy_names(fm, tags_of(fm)) if fm else []), card

    def load_events(self):
        events = []
        d = os.path.join(self.repo, ".board", "events")
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.endswith(".jsonl"):
                    with open(os.path.join(d, name), encoding="utf-8") as f:
                        for line in f:
                            try:
                                events.append(json.loads(line))
                            except ValueError:
                                continue
        events.sort(key=lambda e: e.get("ts", ""))
        return events

    def rebuild(self):
        cards = self.scan()
        events = self.load_events()
        head = self.git("rev-parse", "HEAD").strip()
        with self.lock, self.db:
            self.db.execute("DELETE FROM cards")
            self.db.executemany(
                "INSERT INTO cards (slug, path, board, data) VALUES (?, ?, ?, ?)",
                [(c["slug"], c["path"], c["board"], json.dumps(c)) for c in cards])
            self.db.execute("DELETE FROM events")
            self.db.executemany(
                "INSERT INTO events (ts, card, type, actor, data) VALUES (?, ?, ?, ?, ?)",
                [(e.get("ts", ""), e.get("card", ""), e.get("type", ""), e.get("actor", ""), json.dumps(e))
                 for e in events])
            self.db.execute("DELETE FROM tags")
            self.db.executemany("INSERT OR IGNORE INTO tags VALUES (?)", [(t,) for t in self.all_tags])
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('head', ?)", (head,))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('imported', ?)",
                            (datetime.datetime.now().isoformat(timespec="seconds"),))
        self.bump()
        return len(cards)

    # -- git -----------------------------------------------------------

    # A repo with no commits or no origin (a fresh install, a local-only vault) fails some git calls every time. Said
    # once, plainly, not on every call; a failure in a repo that has both is always printed.
    def _probe(self, *args):
        r = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout

    def _local_only(self, err):
        """(key, message) when `err` is just a repo with no commits or no origin, else None."""
        if any(n in err for n in ("does not have any commits yet", "unknown revision or path", "ambiguous argument 'HEAD'")) \
                and self._probe("rev-parse", "-q", "--verify", "HEAD")[0] != 0:
            return "commits", "no commits yet in the vault repo: the board's first export makes one"
        if any(n in err for n in ("no such branch", "no upstream configured", "does not appear to be a git repository")) \
                and "origin" not in self._probe("remote")[1].split():
            return "origin", "no origin remote: commits stay local"
        return None

    def git(self, *args):
        try:
            return subprocess.run(["git", "-C", self.repo, *args], capture_output=True,
                                  text=True, timeout=300, check=True).stdout
        except (subprocess.SubprocessError, OSError) as e:
            err = (getattr(e, "stderr", "") or str(e)).strip()
            known = self._local_only(err)
            if known:
                self.note_once(*known)
                return ""
            print("git %s failed: %s" % (" ".join(a for a in args if not a.startswith("user.")), err), flush=True)
            return ""

    def note_once(self, key, message):
        if key not in self._said:
            self._said.add(key)
            print("startup: " + message, flush=True)

    def has_origin(self):
        return "origin" in self._probe("remote")[1].split()

    def sync(self):
        """Pull; rebuild when HEAD moved. Returns True if the index changed."""
        before = self.meta("head")
        self.git("pull", "--ff-only", "-q")
        if self.git("rev-parse", "HEAD").strip() != before:
            self.rebuild()
            return True
        return False

    # -- queries -------------------------------------------------------

    def meta(self, key):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else ""

    def cards(self):
        with self.lock:
            rows = self.db.execute("SELECT data FROM cards").fetchall()
        return [json.loads(r[0]) for r in rows]

    def count(self):
        """How many cards there are, without loading them."""
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]

    def upsert(self, card):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO cards (slug, path, board, data) VALUES (?, ?, ?, ?)",
                            (card["slug"], card["path"], card["board"], json.dumps(card)))

    def add_event(self, ev):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events (ts, card, type, actor, data) VALUES (?, ?, ?, ?, ?)",
                            (ev["ts"], ev["card"], ev["type"], ev.get("actor", ""), json.dumps(ev)))

    def event_by_client(self, cid):
        """The event a client's own id (client_id) was recorded with, or None: a retry is not done twice."""
        with self.lock:
            row = self.db.execute("SELECT data FROM events WHERE json_extract(data, '$.client_id') = ? LIMIT 1",
                                  (cid,)).fetchone()
        return json.loads(row[0]) if row else None

    def events(self, card=None, limit=50, since=None, until=None, etype=None):
        sql, args = "SELECT data FROM events WHERE 1=1", []
        if card:
            sql += " AND card = ?"
            args.append(card)
        if etype:
            sql += " AND type = ?"
            args.append(etype)
        if since:
            sql += " AND ts >= ?"
            args.append(since)
        if until:
            sql += " AND ts < ?"
            args.append(until)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [json.loads(r[0]) for r in rows]

    def closeout(self, slug):
        """How an archived card was closed: {"outcome": "wontdo" or "", "reason": text, "ts": when} from the move
        into Archived (the newest one), or None when no such move is known (a note archived by hand)."""
        for ev in self.events(card=slug, limit=200, etype="move"):
            if ((ev.get("changes") or {}).get("board") or [None, None])[1] == "archived":
                return {"outcome": ev.get("outcome") or "", "reason": ev.get("reason") or "", "ts": ev.get("ts") or ""}
        return None

    # -- links (link rot) ---------------------------------------------

    def link(self, url):
        rows = self.links("url = ?", (url,), 1)
        return rows[0] if rows else None

    def links(self, where="", args=(), limit=100000):
        with self.lock:
            cur = self.db.execute("SELECT * FROM links %s ORDER BY first_seen LIMIT ?" % (("WHERE " + where) if where else ""),
                                  (*args, limit))
            keys = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return [dict(zip(keys, r)) for r in rows]

    def link_set(self, url, **fields):
        with self.lock, self.db:
            cur = self.db.execute("SELECT url FROM links WHERE url = ?", (url,)).fetchone()
            if cur:
                if fields:
                    self.db.execute("UPDATE links SET %s WHERE url = ?" % ", ".join("%s = ?" % k for k in fields),
                                    (*fields.values(), url))
            else:
                cols = ["url"] + list(fields)
                self.db.execute("INSERT INTO links (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                                (url, *fields.values()))

    def last_activity(self):
        """slug -> timestamp of its latest event."""
        with self.lock:
            rows = self.db.execute("SELECT card, MAX(ts) FROM events GROUP BY card").fetchall()
        return {r[0]: r[1] for r in rows}

    def known_tags(self):
        with self.lock:
            return {r[0] for r in self.db.execute("SELECT tag FROM tags")}

    def bump(self):
        """Revision counter the page polls to know when to refresh."""
        with self.lock, self.db:
            row = self.db.execute("SELECT value FROM meta WHERE key = 'rev'").fetchone()
            rev = int(row[0]) + 1 if row else 1
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('rev', ?)", (str(rev),))
        return rev

    def claim(self, slug, actor, agent, minutes):
        with self.lock, self.db:
            if minutes <= 0:
                self.db.execute("DELETE FROM claims WHERE card = ?", (slug,))
            else:
                self.db.execute("INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?)",
                                (slug, actor, agent, time.time() + minutes * 60))
        self.bump()

    def claims(self):
        with self.lock:
            rows = self.db.execute("SELECT card, actor, agent, expires FROM claims WHERE expires > ?",
                                   (time.time(),)).fetchall()
        return {r[0]: {"actor": r[1], "agent": r[2], "expires": r[3]} for r in rows}

    def card(self, slug):
        with self.lock:
            row = self.db.execute("SELECT data FROM cards WHERE slug = ?", (slug,)).fetchone()
        return json.loads(row[0]) if row else None


def sort_key(card):
    return (card["rank"] if card["rank"] is not None else 1e9,
            card["priority"] or 9, card["title"].lower())
