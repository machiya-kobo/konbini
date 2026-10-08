"""Board writes: edit note frontmatter in the board's clone, log events,
and export to git in batches.

Every write changes only frontmatter lines of the card's note (never the
body) in the board's own clone of the vault repo, appends one JSON line
to .board/events/YYYY-MM.jsonl, and refreshes that card in the SQLite
index. The worker commits pending changes as the configured author (KANBAN_GIT_AUTHOR_NAME) once
writes have been idle for EXPORT_IDLE seconds (or EXPORT_MAX after the
first), then fetches, rebases its commits onto origin and pushes. It never
stashes: pulls wait until pending writes are committed. When the rebase
conflicts (someone edited the same frontmatter lines), the board replays its
own changes key by key onto the fresh upstream text (see replay), and it
refuses to commit a file with git conflict markers. Everything the board
knows is in the notes and .board/, so `app.py rebuild` recreates it from a
fresh clone.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import threading
import time

import yaml

from vaultkit.notes import safe_path
from store import (note_front, tags_of, COLUMNS, CONFLICT_RE, FRONT_RE, GIT_SCOPE, PRIORITY_NAMES, PRIORITY_WORDS,
                   VAULT, parse_note, slugify)

EXPORT_IDLE = int(os.environ.get("KANBAN_EXPORT_IDLE", "120"))
EXPORT_MAX = int(os.environ.get("KANBAN_EXPORT_MAX", "900"))
PULL_SECONDS = int(os.environ.get("KANBAN_PULL_SECONDS", "60"))
VERIFY_SECONDS = int(os.environ.get("KANBAN_VERIFY_SECONDS", "3600"))
# Who the board's git commits are by (KANBAN_GIT_AUTHOR_NAME / _EMAIL).
AUTHOR = (os.environ.get("KANBAN_GIT_AUTHOR_NAME", "").strip() or "konbini",
          os.environ.get("KANBAN_GIT_AUTHOR_EMAIL", "").strip() or "konbini@localhost")

SCALARS = ("board", "next", "blocked_by", "priority", "summary", "title", "rank", "updated", "post", "post_url")
POST_STATES = ("none", "idea", "outlined", "drafting", "published", "skipped")
TAG_RE = re.compile(r"^[a-z]+/[A-Za-z0-9][A-Za-z0-9._-]*$")
LISTS = ("dependsOn",)          # list fields the board writes (a block list of quoted links)


CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def client_id(value):
    """A change's own id from a client that may send it twice (the outbox, retrying after a lost answer), or ""."""
    value = str(value or "").strip()
    return value if CLIENT_ID_RE.match(value) else ""


CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def one_line(value, limit):
    """Text for a title or a summary: control characters and every kind of line break collapse to single spaces, then
    the first `limit` characters."""
    return " ".join(CONTROL_CHARS.sub(" ", str(value or "")).split())[:limit].strip()


class WriteError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


# -- the description: the lead of a note's body ------------------------------------------------------------------
# A card's description is the text under the note's title heading, up to the next heading of any level (or, in a
# note with no title heading, the text before the first heading). It is the one part of the body the board writes;
# everything below it is the note's, and stays as it is. A leading "> Stub created by Konbini" line (the old stubs)
# is not part of it.

HEADING_RE = re.compile(r"^#{1,6}[ \t]+\S")
FENCE_RE = re.compile(r"^(```|~~~)")
STUB_RE = re.compile(r"^>[ \t]*Stub created by Konbini\.[^\n]*$", re.M)
DESCRIPTION_MAX = 20000


def lead_span(text):
    """(start, end, titled) character offsets of the description in a whole note: `start` just after the title
    heading's line (or at the body's start when there is none), `end` where the next heading starts (or the end of
    the text); `titled` is whether a title heading precedes it."""
    m = FRONT_RE.match(text)
    pos = m.end() if m else 0
    start, titled, fence = pos, False, False
    first = True
    for line in text[pos:].splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if FENCE_RE.match(bare):
            fence = not fence
        elif not fence and HEADING_RE.match(bare):
            if first and bare.startswith("# ") and not titled:
                titled, start = True, pos + len(line)
                pos += len(line)
                first = False
                continue
            return start, pos, titled
        if bare.strip():
            first = False
        pos += len(line)
    return start, pos, titled


def lead_of(text):
    """The description in a whole note, trimmed: "" when there isn't one."""
    start, end, _ = lead_span(text)
    return STUB_RE.sub("", text[start:end].replace("\r\n", "\n")).strip()


def clean_description(value):
    """A description as the board will write it: text, bounded. A line git would read as a merge conflict (a bare
    =======, or one starting <<<<<<< or >>>>>>>) is indented one space, so pasted text always saves."""
    if value is not None and not isinstance(value, str):
        raise WriteError(422, "description must be text")
    text = CONTROL_CHARS.sub(lambda m: m.group(0) if m.group(0) in "\n\t" else " ", (value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(text) > DESCRIPTION_MAX:
        raise WriteError(422, "the description is too long (%d characters at most)" % DESCRIPTION_MAX)
    return CONFLICT_RE.sub(lambda m: " " + m.group(0), text)


def set_lead(text, description):
    """The whole note with its description replaced (inserted under the title heading when there is none). Raises
    a 422 when the text can't be read back as written: a heading would start a new section, an open code fence would
    swallow the rest of the note."""
    start, end, titled = lead_span(text)
    tail = text[end:]
    block = ("\n" if titled else "") + description + "\n" if description else ("\n" if titled and tail.strip() else "")
    if tail.strip() and description:
        block += "\n"
    out = text[:start] + block + tail
    if lead_of(out) != description:
        raise WriteError(422, "a description can't have headings (a line starting with #) or an unclosed code fence")
    return out


# -- frontmatter line editing ---------------------------------------------

def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text  # YAML date, like every note's date: field
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./()+-]*", text) and not text.endswith(" "):
        try:
            if yaml.safe_load("k: " + text)["k"] == text:
                return text
        except yaml.YAMLError:
            pass
    return json.dumps(text, ensure_ascii=False)  # JSON strings are valid YAML


def key_extent(lines, key):
    """(start, end) of a top-level key and its indented continuation lines."""
    for i, line in enumerate(lines):
        if re.match(r"^%s:(\s|$)" % re.escape(key), line):
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or lines[j].startswith("- ")):
                j += 1
            return i, j
    return None


def edit_front(text, scalars=None, tags=None):
    m = FRONT_RE.match(text)
    if not m:
        raise WriteError(422, "note has no frontmatter")
    lines = m.group(1).split("\n")
    for key, value in (scalars or {}).items():
        ext = key_extent(lines, key)
        if isinstance(value, list):
            new = ["%s:" % key] + ["  - %s" % json.dumps(str(v), ensure_ascii=False) for v in value] if value else []
        else:
            new = [] if value in (None, "") else ["%s: %s" % (key, yaml_scalar(value))]
        if ext:
            lines[ext[0]:ext[1]] = new
        elif new:
            lines.extend(new)
    if tags is not None:
        ext = key_extent(lines, "tags")
        block = ["tags:"] + ["  - %s" % t for t in tags]
        if ext:
            lines[ext[0]:ext[1]] = block
        else:
            lines[1:1] = block
    inner = "\n".join(lines)
    fm = yaml.safe_load(inner)
    if not isinstance(fm, dict):
        raise WriteError(500, "frontmatter edit produced invalid YAML")
    start = text.index(m.group(1))
    return text[:start] + inner + text[start + len(m.group(1)):]


def note_tags(text):
    m = FRONT_RE.match(text)
    fm = yaml.safe_load(m.group(1)) if m else {}
    tags = (fm or {}).get("tags") or []
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    return [str(t).lstrip("#") for t in tags]


def merge_note(base, ours, theirs):
    """Three-way merge of a note the board edited (ours) with an upstream edit
    (theirs). The board writes frontmatter and the description (the lead of the body), so the rest of the body is
    always theirs; a key the board changed takes the board's value, every other key keeps upstream's, tags merge as
    add/remove sets, and the board's description edit is kept unless upstream changed the description too.
    Returns the merged text, or None if it can't be merged safely."""
    fb, fo, ft = note_front(base) or {}, note_front(ours), note_front(theirs)
    if fo is None or ft is None:
        return None
    scalars = {}
    for key in set(fb) | set(fo):
        if key == "tags" or fo.get(key) == fb.get(key) or fo.get(key) == ft.get(key):
            continue
        if key not in LISTS and (isinstance(fo.get(key), (list, dict)) or isinstance(ft.get(key), (list, dict))):
            return None  # the board writes no other lists; don't guess
        scalars[key] = fo.get(key)
    tb, to, tt = tags_of(fb), tags_of(fo), tags_of(ft)
    added = [t for t in to if t not in tb]
    removed = set(tb) - set(to)
    tags = [t for t in tt if t not in removed]
    tags += [t for t in added if t not in tags]
    try:
        merged = edit_front(theirs, scalars, tags if tags != tt else None)
        db, do, dt = lead_of(base), lead_of(ours), lead_of(theirs)
        if do != db and do != dt:
            if dt != db:
                return None             # both sides wrote the description: don't guess
            merged = set_lead(merged, do)
        return merged
    except (WriteError, yaml.YAMLError):
        return None


def version_of(text):
    m = FRONT_RE.match(text)
    return hashlib.sha1((m.group(1) if m else "").encode()).hexdigest()[:12]


# -- writer ---------------------------------------------------------------

class Writer:
    def __init__(self, store):
        self.store = store
        self.repo = store.repo
        self.lock = threading.RLock()
        self.pending = []           # [(slug, summary)] since the last commit
        self.first = self.last = 0.0
        self.last_pull = 0.0
        self.last_verify = time.time()
        self.error = ""
        self.drift = ""
        self.dropped = []           # [(time, text)]: board edits a replay couldn't merge (shown on the board for a day)

    # paths

    def full(self, rel):
        """The path of a note under the vault folder: relative, no `..`, and no symlink on the way (vaultkit.notes.safe_path),
        so a write never lands outside the vault or on a file a link points at."""
        try:
            return safe_path(os.path.join(self.repo, VAULT), rel)
        except ValueError:
            raise WriteError(422, "that note path isn't allowed")

    def read(self, rel):
        with open(self.full(rel), encoding="utf-8") as f:
            return f.read()

    def write_file(self, rel, text):
        path = self.full(rel)
        tmp = path + ".kanban-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

    # events

    def event(self, slug, etype, actor, agent, **data):
        with self.lock:             # a line appended while a pull rebases or resets could be thrown away with the tree
            now = datetime.datetime.now(datetime.timezone.utc)
            ev = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "card": slug, "type": etype,
                  "actor": actor, "agent": agent}
            ev.update({k: v for k, v in data.items() if v not in (None, "", [], {})})
            d = os.path.join(self.repo, ".board", "events")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, now.strftime("%Y-%m") + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self.store.add_event(ev)
            return ev

    def touch(self, slug, summary):
        with self.lock:
            now = time.time()
            if not self.pending:
                self.first = now
            self.last = now
            self.pending.append((slug, summary))
            self.store.bump()

    # tags

    def check_tags(self, tags, confirm, agent, areas=None):
        """New tags: a new area/* tag adds a swimlane and is the maintainer's. `areas` is the caller's konbini areas
        grant (Machiya's identity file): without it no new tag at all is created, confirmed or not. None (no identity
        file): the maintainer is the board's own web UI (`agent == "web"`), as before."""
        known = self.store.known_tags()
        bad = [t for t in tags if not TAG_RE.match(t)]
        if bad:
            raise WriteError(422, "malformed tag(s)", tags=bad)
        new = [t for t in tags if t not in known]
        new_areas = [t for t in new if t.startswith("area/")]
        if areas is False and new:
            raise WriteError(403, "new tags (and area/* swimlanes) need the konbini areas grant", tags=new)
        if new_areas and areas is None and agent != "web":
            raise WriteError(403, "new area/* tags add a swimlane; only a maintainer can create them in the web UI",
                             tags=new_areas)
        if new and not confirm:
            raise WriteError(409, "unknown tag(s); ask the user, then resend with confirm_new_tags: true",
                             code="unknown_tag", tags=new)

    # card updates

    def update(self, slug, fields, actor, agent, if_match=None, areas=None):
        with self.lock:
            card = self.store.card(slug)
            if not card:
                raise WriteError(404, "not found")
            text = self.read(card["path"])
            if note_front(text) is None:    # broken since it was indexed (a phone edit, say): yaml would raise below
                raise WriteError(422, "the note's frontmatter is not valid YAML")
            if if_match and if_match != version_of(text):
                raise WriteError(409, "card changed since you read it", code="version_conflict",
                                 version=version_of(text))
            if "publish" in fields:
                raise WriteError(403, "only a maintainer publishes to the garden, from the web UI")

            fields = dict(fields)
            for key in ("tags_add", "tags_remove"):
                value = fields.get(key)
                if value is not None and (not isinstance(value, list) or not all(isinstance(x, str) for x in value)):
                    raise WriteError(422, "%s must be a list of text" % key)
            if "waiting" in fields and "blocked_by" not in fields:      # API input aliases for the old names
                fields["blocked_by"] = fields.pop("waiting")
            if "status" in fields and "board" not in fields:
                fields["board"] = fields.pop("status")
            scalars, changes = {}, {}
            for key in ("next", "blocked_by", "summary", "title", "stream", "goal"):
                if key in fields:
                    scalars[key] = one_line(fields[key], {"title": 120, "summary": 500, "next": 500, "blocked_by": 300}.get(key, 120))
            if "title" in scalars and not scalars["title"]:
                raise WriteError(422, "title is required")
            area_change = None
            if "area" in fields:         # the swimlane: swap the card's area/* tag (an existing one, unless allowed to make lanes)
                want = str(fields.pop("area") or "").strip().replace("area/", "")
                have = card.get("area") or ""
                if want and want != have:
                    area_change = [have, want]
                    fields["tags_add"] = list(fields.get("tags_add") or []) + ["area/" + want]
                    if have and have != "projects" and "area/" + have in note_tags(text):
                        fields["tags_remove"] = list(fields.get("tags_remove") or []) + ["area/" + have]
            description = None
            if "description" in fields:
                description = clean_description(fields["description"])
            outcome, reason = "", ""
            if "outcome" in fields:      # how a card was closed: "wontdo" (archived without doing it), with an optional reason
                outcome = str(fields["outcome"] or "").strip().lower()
                if outcome not in ("", "wontdo"):
                    raise WriteError(422, "outcome must be wontdo")
                reason = one_line(fields.get("reason"), 300)
            if "due" in fields:
                due = str(fields["due"] or "").strip()
                try:
                    datetime.date.fromisoformat(due) if due else None
                except ValueError:
                    raise WriteError(422, "due must be a date, YYYY-MM-DD")
                scalars["due"] = due
            if "priority" in fields:
                pr = fields["priority"]
                pr = PRIORITY_WORDS.get(pr.strip().lower(), pr) if isinstance(pr, str) else pr
                if pr not in (None, "", 1, 2, 3, "1", "2", "3"):
                    raise WriteError(422, "priority must be high, normal or low (or 1, 2, 3)")
                scalars["priority"] = int(pr) if pr not in (None, "") else None
            if "rank" in fields:
                scalars["rank"] = fields["rank"]
            if "dependsOn" in fields:
                links = self.dependency_links(fields["dependsOn"], card)
                old = card.get("dependsOn") or []
                new = [l[2:-2] for l in links]
                # compared by the card each name points to, so re-saving the form doesn't rewrite
                # [[Projects/X|x]] as [[X]]
                if [self.dep_key(n) for n in new] != [self.dep_key(n) for n in old]:
                    changes["dependsOn"] = [old, new]
                    scalars["dependsOn"] = links
            if "post" in fields:
                state = str(fields["post"] or "").strip().lower()
                if state not in POST_STATES:
                    raise WriteError(422, "post must be one of " + ", ".join(POST_STATES))
                scalars["post"] = None if state == "none" else state
            if "post_url" in fields:
                url = str(fields["post_url"] or "").strip()
                if url and not url.startswith(("http://", "https://")):
                    raise WriteError(422, "post_url must be an http(s) URL")
                scalars["post_url"] = url or None

            tags = note_tags(text)
            new_tags = list(tags)
            if area_change:
                changes["area"] = area_change
            if "board" in fields:
                col = str(fields["board"]).lower()
                if col not in COLUMNS:
                    raise WriteError(422, "board must be one of " + ", ".join(COLUMNS))
                if col != card["board"]:
                    changes["board"] = [card["board"], col]
                scalars["board"] = col
                today = datetime.date.today().isoformat()
                if col != card["board"]:
                    if col == "wip" and not card.get("started"):
                        scalars["started"] = today                    # first move to WIP
                    if col == "done":
                        scalars["completedDate"] = today
                    elif card.get("completedDate") and col not in ("done", "archived"):
                        scalars["completedDate"] = None               # reopened
                if col != "blocked" and "blocked_by" not in fields and card.get("blocked_by"):
                    scalars["blocked_by"] = None
            if outcome and not (changes.get("board") and changes["board"][1] == "archived"):
                raise WriteError(422, "wontdo applies when a card is archived")
            old_description = lead_of(text)
            if description is not None and description != old_description:
                changes["description"] = [old_description[:120], description[:120]]
            add = [t for t in fields.get("tags_add") or [] if t not in new_tags]
            remove = set(fields.get("tags_remove") or [])
            if add:
                self.check_tags(add, fields.get("confirm_new_tags"), agent, areas)
            new_tags = [t for t in new_tags if t not in remove] + add

            for key, value in scalars.items():
                old = card.get(key)
                if key in ("next", "blocked_by", "summary", "title", "priority", "post", "post_url", "stream", "goal", "due") \
                        and (old or None) != (value or None):
                    changes[key] = [old, value]
            if new_tags == tags and all(card.get(k) == v for k, v in scalars.items()
                                        if k in ("board", "rank")) and not (set(scalars) - {"board", "rank"}) \
                    and "description" not in changes:
                return card
            scalars["updated"] = datetime.date.today().isoformat()
            # Written under the new names (the Machiya frontmatter schema): status, waiting, priority as
            # a word. The card dict, the API and the events keep the old keys (board, blocked_by,
            # priority 1-3).
            out = dict(scalars)
            if "board" in out:
                out["status"] = out.pop("board")
            if "blocked_by" in out:
                out["waiting"] = out.pop("blocked_by")
            if out.get("priority"):
                out["priority"] = PRIORITY_NAMES[out["priority"]]
            text2 = edit_front(text, out, new_tags if new_tags != tags else None)
            if "description" in changes:
                text2 = set_lead(text2, description)
            self.write_file(card["path"], text2)
            card2 = self.reindex(card["path"], slug)

            etype = "move" if "board" in changes else "edit"
            ev_changes = dict(changes)
            if add or remove:
                ev_changes["tags"] = {"add": add, "remove": sorted(remove)}
            if ev_changes:
                self.event(slug, etype, actor, agent, changes=ev_changes, outcome=outcome, reason=reason)
            summary = ("%s->%s" % (slug, changes["board"][1])) if "board" in changes else slug
            if ev_changes or "rank" in fields:
                self.touch(slug, summary)
            return card2

    def dep_key(self, name):
        name = name.strip().lower()
        for c in self.store.cards():
            if name in (c["slug"].lower(), c["title"].lower(), c["path"][:-3].lower(),
                        c["path"].rsplit("/", 1)[-1][:-3].lower()) or name.split("/")[-1] == c["path"].rsplit("/", 1)[-1][:-3].lower():
                return c["slug"]
        return name

    def dependency_links(self, value, card):
        """dependsOn from the API or the form (a list, or names separated by commas): each name is a card's
        slug or title, or a note name; written as quoted wikilinks to the note's file name."""
        from deps import link_for
        names = value if isinstance(value, list) else str(value or "").split(",")
        cards = self.store.cards()
        by_key = {}
        for c in cards:
            by_key.setdefault(c["slug"].lower(), c)
            by_key.setdefault(c["title"].lower(), c)
        out = []
        for name in names:
            name = str(name).strip()
            m = re.fullmatch(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", name)
            name = (m.group(1) if m else name).strip()
            if not name:
                continue
            dep = by_key.get(name.lower()) or by_key.get(name.split("/")[-1].lower())
            if dep and dep["slug"] == card["slug"]:
                raise WriteError(422, "a card can't depend on itself")
            link = link_for(dep) if dep else "[[%s]]" % name
            if link not in out:
                out.append(link)
        return out

    def order(self, slugs, column, actor, agent, areas=None, origin=None):
        """Set rank 10, 20, ... for cards in display order (drag and drop). origin: {slug: the column the page showed it in}:
        a card that is somewhere else now (moved by someone meanwhile) is left alone, so a stale drag can't move a done card
        back. Returns the slugs it skipped."""
        skipped = []
        with self.lock:
            for i, slug in enumerate(slugs):
                card = self.store.card(slug)
                if not card:
                    continue
                if origin and isinstance(origin.get(slug), str) and card["board"] != origin[slug]:
                    skipped.append(slug)
                    continue
                fields = {"rank": (i + 1) * 10}
                if column and card["board"] != column:
                    fields["board"] = column
                if card.get("rank") != fields["rank"] or "board" in fields:
                    self.update(slug, fields, actor, agent, areas=areas)
        return skipped

    def create(self, fields, actor, agent, areas=None):
        cid = client_id(fields.get("client_id"))
        with self.lock:
            if cid:                     # a retry of a create whose answer was lost (an outbox): the card it made
                done = self.store.event_by_client(cid)
                if done and done.get("type") == "create" and self.store.card(done["card"]):
                    return self.store.card(done["card"])
            # Text that ends up in a note is one line of plain text: a newline in a summary could write a bare "=======" (a
            # Markdown heading underline, and a git conflict marker to the export, which then refused every batch).
            for key in ("title", "summary", "area", "project", "stream"):
                if fields.get(key) is not None and not isinstance(fields.get(key), str):
                    raise WriteError(422, "%s must be text" % key)
            for key in ("topics", "machines"):
                value = fields.get(key)
                if value is not None and (not isinstance(value, list) or not all(isinstance(x, str) for x in value)):
                    raise WriteError(422, "%s must be a list of text" % key)
            title = one_line(fields.get("title"), 120)
            summary = one_line(fields.get("summary"), 500)
            stream = one_line(fields.get("stream"), 120)
            description = clean_description(fields.get("description")) or summary    # the lead; the summary when none is given
            fields = dict(fields, summary=summary)
            if not title:
                raise WriteError(422, "title is required")
            area = str(fields.get("area") or "").strip().replace("area/", "")
            if not area:
                raise WriteError(422, "area is required (it picks the swimlane)")
            col = str(fields.get("board") or fields.get("status") or "backlog").lower()
            if col not in COLUMNS:
                raise WriteError(422, "board must be one of " + ", ".join(COLUMNS))
            slug = slugify(fields.get("project") or title)
            if self.store.card(slug):
                raise WriteError(409, "a card with slug %s exists" % slug, code="exists", slug=slug)
            name = re.sub(r'[\\/:*?"<>|#^\[\]]', "", title).strip().lstrip(".")[:100].strip() or slug   # a file name, never ".md"
            rel = os.path.join("Projects", name + ".md")
            if os.path.exists(self.full(rel)):
                raise WriteError(409, "note %s already exists" % rel, code="exists")

            tags = list(dict.fromkeys(["type/" + ("project" if fields.get("type") == "project" else "idea"),
                                       "area/projects", "area/" + area]))      # a "projects" card: the tag once
            tags += ["topic/" + t.replace("topic/", "") for t in fields.get("topics") or []]
            tags += ["machine/" + m.replace("machine/", "") for m in fields.get("machines") or []]
            if fields.get("effort") in ("s", "m", "l"):
                tags.append("effort/" + fields["effort"])
            self.check_tags([t for t in tags if not t.startswith("type/")], fields.get("confirm_new_tags"), agent, areas)

            # A stub is written in the new schema (the Machiya frontmatter schema): status:, created:,
            # priority as a word, no status/* tag.
            today = datetime.date.today().isoformat()
            lines = ["---", "title: " + yaml_scalar(title), "created: " + today, "tags:"]
            lines += ["  - " + t for t in tags]
            lines += ["aliases: []", "project: " + slug, "status: " + col]
            pr = fields.get("priority")
            pr = PRIORITY_WORDS.get(pr.strip().lower(), pr) if isinstance(pr, str) else pr
            if pr in (1, 2, 3, "1", "2", "3"):
                lines.append("priority: " + PRIORITY_NAMES[int(pr)])
            if col == "wip":
                lines.append("started: " + today)
            if stream:
                lines.append("stream: " + yaml_scalar(stream))
            lines += ["summary: " + yaml_scalar(summary),
                      "created_by: " + yaml_scalar("%s (%s)" % (actor, agent)),
                      "updated: " + today, "publish: false", "---", "", "# " + title, ""]
            note_text = "\n".join(lines)
            os.makedirs(os.path.dirname(self.full(rel)), exist_ok=True)
            self.write_file(rel, set_lead(note_text, description) if description else note_text)
            card = self.reindex(rel, slug)
            self.event(slug, "create", actor, agent, path=rel, board=col, client_id=cid)
            self.touch(slug, slug + " (new)")
            return card

    def description(self, card):
        """The card's description (the lead of its note), or ""."""
        try:
            return lead_of(self.read(card["path"]))
        except OSError:
            return ""

    def reindex(self, rel, slug):
        card = parse_note(self.read(rel), rel)
        if card:
            card["slug"] = slug
            self.store.upsert(card)
        return card

    # -- git export --------------------------------------------------------

    def git(self, *args):
        return self.store.git("-c", "user.name=%s" % AUTHOR[0], "-c", "user.email=%s" % AUTHOR[1],
                              "-c", "commit.gpgsign=false", *args)

    def ensure_gitattributes(self):
        path = os.path.join(self.repo, ".gitattributes")
        line = ".board/events/*.jsonl merge=union"
        existing = open(path).read() if os.path.exists(path) else ""
        if line not in existing:
            with open(path, "a") as f:
                f.write(("" if existing.endswith("\n") or not existing else "\n") + line + "\n")

    def dirty(self):
        return bool(self.store.git("status", "--porcelain", "--", GIT_SCOPE, ".board", ".gitattributes").strip())

    def commit(self, force=False):
        with self.lock:
            if not self.pending and not (force and self.dirty()):
                return
            if not self.pending:
                self.pending = [("", "sync")]
            seen, parts = set(), []
            for slug, summary in self.pending:
                if summary not in seen:
                    seen.add(summary)
                    parts.append(summary)
            msg = "board: %d change%s (%s)" % (len(self.pending), "" if len(self.pending) == 1 else "s",
                                              ", ".join(parts[:8]) + (", ..." if len(parts) > 8 else ""))
            self.ensure_gitattributes()
            self.git("add", "-A", "--", GIT_SCOPE, ".board", ".gitattributes")
            bad = self.conflicted()
            if bad:
                # only the bad notes stay out of the commit: one note's text must not stop every other change from being
                # exported (the board shows the alert until someone fixes the note)
                self.git("reset", "-q", "--", *bad)
                self.error = "not committed: git conflict markers in " + ", ".join(bad[:3])
                print("export: " + self.error, flush=True)
            if self.store.git("diff", "--cached", "--name-only").strip():
                self.git("commit", "-q", "-m", msg)
            self.pending = [("", "held back: " + ", ".join(bad[:3]))] if bad else []
            print("export: " + msg, flush=True)

    def ahead(self):
        out = self.store.git("rev-list", "--count", "@{u}..HEAD").strip()
        return int(out) if out.isdigit() else 0

    def conflicted(self):
        """Staged files whose change adds git conflict marker lines (markers
        already in HEAD aren't the board's doing and don't block it)."""
        bad, current = [], None
        for line in self.store.git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff").splitlines():
            if line.startswith("+++ "):
                name = line[4:].rstrip("\t").strip('"')  # paths with spaces end in a tab; odd ones are quoted
                current = name[2:] if name.startswith("b/") else None
            elif line.startswith("+") and current and CONFLICT_RE.match(line[1:]) and current not in bad:
                bad.append(current)
        return bad

    def rebasing(self):
        return any(os.path.exists(os.path.join(self.repo, ".git", d)) for d in ("rebase-merge", "rebase-apply"))

    def blob(self, rev, rel):
        r = subprocess.run(["git", "-C", self.repo, "show", "%s:%s" % (rev, rel)],
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else None

    def pull(self):
        if self.dirty():
            self.commit(force=True)  # never stash: board writes go into a commit first
        if self.dirty() or self.rebasing():
            self.error = "working tree not clean; not pulling"
            print("sync: " + self.error, flush=True)
            return False
        if not self.store.has_origin():           # a local-only vault: nothing to fetch or push (said once by Store.git)
            self.store.note_once("origin", "no origin remote: commits stay local")
            return False
        before = self.store.git("rev-parse", "HEAD").strip()
        self.git("fetch", "-q", "origin")
        upstream = self.store.git("rev-parse", "@{u}").strip()
        if not upstream:
            return False
        if self.ahead():
            self.git("rebase", "-q", upstream)
            if self.rebasing():
                self.git("rebase", "--abort")
                if not self.replay(upstream):
                    self.error = "rebase conflicted and replay failed; will retry"
                    print("sync: " + self.error, flush=True)
                    return False
        else:
            self.git("merge", "-q", "--ff-only", upstream)
        after = self.store.git("rev-parse", "HEAD").strip()
        if after != before:
            self.store.rebuild()
            print("sync: index rebuilt at %s" % after[:8], flush=True)
        return True

    def replay(self, upstream):
        """Rebase conflicted: rebuild the board's unpushed commits on top of
        upstream, file by file, instead of committing conflict markers."""
        base = self.store.git("merge-base", "HEAD", upstream).strip()
        ours = self.store.git("rev-parse", "HEAD").strip()
        if not base or not ours:
            return False
        names = [n for n in self.store.git("diff", "--name-only", "-z", base, ours).split("\0") if n]
        subjects = [l for l in self.store.git("log", "--format=%s", "%s..%s" % (base, ours)).splitlines() if l]
        merged, notes = {}, []
        for rel in names:
            b, o, t = self.blob(base, rel), self.blob(ours, rel), self.blob(upstream, rel)
            if rel.startswith(".board/events/") and rel.endswith(".jsonl"):
                seen = set((b or "").splitlines()) | set((t or "").splitlines())
                new = [l for l in (o or "").splitlines() if l not in seen]
                text = t or ""
                merged[rel] = text + ("" if not text or text.endswith("\n") else "\n") + "".join(l + "\n" for l in new)
            elif rel == ".gitattributes":
                lines = (t or "").splitlines()
                merged[rel] = "\n".join(lines + [l for l in (o or "").splitlines() if l not in lines]) + "\n"
            elif o is None:
                notes.append("%s: board deleted it; kept upstream" % rel)
            elif t is None:
                if b is None:
                    merged[rel] = o  # a stub note the board created
                else:
                    notes.append("%s: gone upstream; dropped the board's edit" % rel)
            elif b is None:
                notes.append("%s: created on both sides; kept upstream" % rel)
            else:
                text = merge_note(b, o, t)
                if text is None:
                    notes.append("%s: couldn't merge the frontmatter or description; kept upstream" % rel)
                else:
                    merged[rel] = text
        self.git("reset", "-q", "--hard", upstream)
        for rel, text in merged.items():
            path = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        if merged:
            self.git("add", "-A", "--", *merged.keys())
        if self.conflicted():
            self.git("reset", "-q", "--hard", upstream)
            return False
        if self.store.git("diff", "--cached", "--name-only").strip():
            msg = subjects[0] if len(subjects) == 1 else "board: %d commits replayed (%s)" % (
                len(subjects), "; ".join(s.replace("board: ", "") for s in subjects[:4]))
            self.git("commit", "-q", "-m", msg + "\n\nReplayed onto upstream after a conflicting edit.")
        for n in notes:
            print("sync: replay: " + n, flush=True)
            self.dropped = (self.dropped + [(time.time(), n)])[-10:]
        print("sync: rebase conflicted; replayed %d file(s) onto %s" % (len(merged), upstream[:8]), flush=True)
        return True

    def push(self):
        if self.ahead():
            self.git("push", "-q", "origin", "HEAD")
            if self.ahead():
                self.error = "push failed; will retry after the next pull"
                print("sync: " + self.error, flush=True)
            else:
                self.error = ""
                print("sync: pushed", flush=True)

    def worker(self):
        while True:
            time.sleep(10)
            try:
                now = time.time()
                if self.pending and (now - self.last >= EXPORT_IDLE or now - self.first >= EXPORT_MAX):
                    self.commit()
                if now - self.last_verify >= VERIFY_SECONDS and not self.pending:
                    self.last_verify = now
                    with self.lock:
                        self.verify()
                # Pull only between batches: pending writes are committed first, never stashed.
                if not self.pending and (now - self.last_pull >= PULL_SECONDS or self.ahead()):
                    self.last_pull = now
                    with self.lock:
                        if self.pull():
                            self.push()
            except Exception as exc:  # keep syncing after transient failures
                self.error = str(exc)
                print("sync failed: %s" % exc, flush=True)

    def verify(self):
        """Drift check: the SQLite cache must equal a fresh scan of the notes
        (and the events log). If it doesn't, log what differed and rebuild."""
        fresh = {c["slug"]: c for c in self.store.scan()}
        cached = {c["slug"]: c for c in self.store.cards()}
        differ = sorted(k for k in set(fresh) | set(cached) if fresh.get(k) != cached.get(k))
        events_on_disk = len(self.store.load_events())
        events_cached = len(self.store.events(limit=10 ** 7))
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        if differ or events_on_disk != events_cached:
            self.drift = "%s: %d card(s) differed (%s), events %d vs %d; rebuilt" % (
                stamp, len(differ), ", ".join(differ[:5]), events_on_disk, events_cached)
            print("verify: " + self.drift, flush=True)
            self.store.rebuild()
        else:
            self.drift = "%s: ok (%d cards, %d events)" % (stamp, len(fresh), events_on_disk)

    def status(self):
        return {"pending": len(self.pending), "ahead": self.ahead(), "error": self.error, "verify": self.drift,
                "broken": [{"path": p, "reason": r} for p, r in self.store.broken],
                "export_idle": EXPORT_IDLE, "export_max": EXPORT_MAX}
