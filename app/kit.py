"""Writing kits: the facts of a project, gathered for a blog post.

Nothing here writes prose. A kit collects what the note, the board's
events, the vault's git history, the machines' change logs and the blog
already know, and lays it out as an outline for the user to fill in."""
import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from urllib.parse import quote, urlsplit

from store import VAULT, _str, commit_filter
from timeline import LINK_RE, clean, local_date, log_rows, parse_date

FRONT_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
SYNC_RE = re.compile(r"<!--\s*project-sync:start\s*-->.*?<!--\s*project-sync:end\s*-->", re.S)
HEAD_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"```([\w+.-]*)[^\n]*\n(.*?)```", re.S)
CHECK_RE = re.compile(r"^\s*[-*] \[([ xX])\]\s+(.*)$")
EMBED_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
MDIMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
MDLINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)")
BARE_URL_RE = re.compile(r"(?<![(\[<`\"'/])https?://[^\s)\]>`\"']+")
FIX_RE = re.compile(r"\b(fix|fixed|fixes|bug|bugs|broke|broken|fail|failed|failure|crash|wedg\w*|regress\w*|"
                    r"workaround|issue|problem|gotcha|hang|hung|timeout|error|stutter\w*)\b", re.I)
PROBLEM_HEAD_RE = re.compile(r"gotcha|troubleshoot|problem|issue|lesson|pitfall|caveat|known", re.I)
DECISION_HEAD_RE = re.compile(r"decision|design|approach|choices", re.I)
STOPWORDS = {"with", "from", "into", "the", "and", "for", "project", "server", "stack", "board", "library",
             "file", "share", "setup", "system", "migration", "tuning", "port", "ports", "fix", "notes"}
UNIT_RE = re.compile(r"\d[\d,.]*\s*(%|fps|ms|s\b|sec|min|h\b|hours?|days?|weeks?|kb|mb|gb|tb|k\b|px|x\b|albums?|"
                     r"tracks?|files?|lines?|commits?|frames?|bytes?|mhz|ghz|kbps|w\b|v\b|°|dbfs|db\b|cuts?|"
                     r"answers?|cards?|notes?|hosts?|packages?|records?|images?|posts?|items?)", re.I)
ARROW_RE = re.compile(r"\d[\d,.]*\s*(->|→|to)\s*\d")
SKIP_COMMIT_RE = commit_filter("KANBAN_SKIP_COMMITS")
LOCAL_REPOS = os.environ.get("KANBAN_REPOS", "/repos")  # read-only checkouts, one directory per repo name
SYNC_COMMIT_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}): (.+)$", re.M)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
POST_STATES = ("none", "idea", "outlined", "drafting", "published", "skipped")
SHORT = {"backlog": "Backlog", "ready": "Ready", "wip": "WIP", "blocked": "Blocked", "done": "Done", "archived": "Archived"}
# The blog taxonomy a kit maps a card onto is the blog's own, so it lives in the vault repo, not here: an optional
# .board/kit.json {"tag_synonyms": {"shell": "terminal"}, "area_category": {"ops": "hosting"}, "default_category": "tech",
# "ignore_tags": ["challenge"], "ignore_categories": ["imported"]}. Missing or unreadable = empty (the blog's own tags
# and categories still drive the kit).
KIT_FILE = os.path.join(".board", "kit.json")


def unwiki(text):
    return LINK_RE.sub(lambda m: (m.group(2) or m.group(1)).split("/")[-1], text)


def yaml_str(text):
    text = str(text or "")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.,'()+/-]*", text) and not text.endswith(" "):
        return text
    return json.dumps(text, ensure_ascii=False)


def cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def sections(body):
    """[(level, title, text)] in document order; the text before the first
    heading is (0, "", text)."""
    out, level, title, buf, fence = [], 0, "", [], False
    for line in body.splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else HEAD_RE.match(line)
        if m:
            out.append((level, title, "\n".join(buf).strip()))
            level, title, buf = len(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(line)
    out.append((level, title, "\n".join(buf).strip()))
    return [s for s in out if s[1] or s[2]]


def section_text(secs, pattern, min_level=2):
    rx = re.compile(pattern, re.I)
    for level, title, text in secs:
        if level >= min_level and rx.search(title):
            return text
    return ""


def paragraphs(text, limit=3):
    """Prose paragraphs: no tables, lists, comments or code; wikilinks unwrapped."""
    out, fence = [], False
    for para in re.split(r"\n\s*\n", text):
        lines = []
        for l in para.splitlines():
            if l.startswith("```"):
                fence = not fence
                continue
            if fence or not l.strip() or l.lstrip().startswith(("|", "<!--", "- ", "* ", "#", ">", "!")):
                continue
            lines.append(l.strip())
        if lines:
            out.append(unwiki(" ".join(lines)))
            if len(out) >= limit:
                break
    return out


def bullets(text, limit=8):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")) and not CHECK_RE.match(line):
            out.append(unwiki(s[2:].strip()))
            if len(out) >= limit:
                break
    return out


def repo_api(url):
    """Commits endpoint for a forgejo/gitea or github repo URL, or None."""
    p = urlsplit(url)
    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1].removesuffix(".git")
    if p.netloc == "github.com":
        return "https://api.github.com/repos/%s/%s/commits?per_page=50" % (owner, name)
    if "forgejo" in p.netloc or "gitea" in p.netloc:
        return "https://%s/api/v1/repos/%s/%s/commits?limit=50" % (p.netloc, owner, name)
    return None


class Kits:
    def __init__(self, store, garden, timeline, blog, board_url, links=None, hister=None, garden_url=""):
        self.store, self.garden, self.timeline, self.blog = store, garden, timeline, blog
        self.garden_url = (garden_url or board_url + "/garden").rstrip("/")   # Niwa (machiya-kobo/niwa)
        self.links = links
        self.hister = hister  # pages I've read (private; the markdown lists original URLs only)
        self.board_url = board_url.rstrip("/")
        self._remote = {}
        self._lock = threading.Lock()

    def taxonomy(self):
        """The vault repo's .board/kit.json as {tag_synonyms, area_category, default_category, ignore_tags,
        ignore_categories}; every key empty when the file is missing or unreadable (said once)."""
        empty = {"tag_synonyms": {}, "area_category": {}, "default_category": "", "ignore_tags": [], "ignore_categories": []}
        path = os.path.join(self.store.repo, KIT_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            out = dict(empty)
            for key in ("tag_synonyms", "area_category"):
                val = cfg.get(key) or {}
                if not isinstance(val, dict):
                    raise ValueError("%s is an object" % key)
                out[key] = {str(k): str(v) for k, v in val.items()}
            for key in ("ignore_tags", "ignore_categories"):
                val = cfg.get(key) or []
                if not isinstance(val, list):
                    raise ValueError("%s is a list" % key)
                out[key] = [str(v) for v in val]
            default = cfg.get("default_category") or ""
            if not isinstance(default, str):
                raise ValueError("default_category is a string")
            out["default_category"] = default
            return out
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.store.note_once("kit.json", "%s is not usable (%s): the kit uses its defaults" % (KIT_FILE, exc))
        return empty

    # -- repo commits: best effort, cached -----------------------

    def local_commits(self, url):
        """Commits from a read-only checkout mounted at LOCAL_REPOS/<name>, or None."""
        name = url.rstrip("/").split("/")[-1].removesuffix(".git")
        path = os.path.join(LOCAL_REPOS, name)
        if not name or not os.path.isdir(os.path.join(path, ".git")):
            return None
        try:
            out = subprocess.run(["git", "-C", path, "log", "-n", "80", "--format=%as\x1f%s"],
                                 capture_output=True, text=True, timeout=20, check=True).stdout
        except (subprocess.SubprocessError, OSError):
            return None
        commits = []
        for line in out.splitlines():
            try:
                when, subject = line.split("\x1f", 1)
            except ValueError:
                continue
            if not SKIP_COMMIT_RE.match(subject):
                commits.append({"date": when, "subject": subject[:160]})
        return commits

    def repo_commits(self, url, pages=1):
        """Recent commits: a mounted checkout first, else the forge's API
        (`pages` of 50, deeper for shared repos where the project is a fraction)."""
        local = self.local_commits(url)
        if local is not None:
            return local
        endpoint = repo_api(url)
        if not endpoint:
            return None
        endpoint = "%s&pages=%d" % (endpoint, pages)
        with self._lock:
            hit = self._remote.get(endpoint)
        if hit and time.time() - hit[0] < (8 * 3600 if hit[1] is not None else 120):
            return hit[1]  # a failed fetch is retried after two minutes, a good one kept eight hours
        out = []
        base = endpoint.split("&pages=")[0]
        for page in range(1, pages + 1):
            try:
                req = urllib.request.Request("%s&page=%d" % (base, page),
                                             headers={"Accept": "application/json", "User-Agent": "konbini-kit/1"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
            except Exception:  # network, rate limit, odd JSON: keep the pages that worked
                if not out:
                    out = None
                break
            for c in data:
                commit = c.get("commit") or {}
                msg = (commit.get("message") or "").strip().splitlines()
                when = ((commit.get("author") or {}).get("date") or (commit.get("committer") or {}).get("date") or "")[:10]
                if msg and not SKIP_COMMIT_RE.match(msg[0]):
                    out.append({"date": when, "subject": msg[0][:160]})
            if len(data) < 50:
                break
        with self._lock:
            self._remote[endpoint] = (time.time(), out)
        return out

    # -- the kit --------------------------------------------------------------

    def note_of(self, card):
        self.garden.index()
        return self.garden.notes.get(card["path"])

    def dates(self, card, fm, log, events):
        started = parse_date(fm.get("started")) or parse_date(fm.get("created"))
        if not started and log:
            started = log[0]["date_obj"]
        finished, approx = None, False
        for ev in events:
            if ev.get("type") == "move" and (ev.get("changes") or {}).get("board", [None, None])[1] == "done":
                finished = local_date(ev.get("ts", "")) or finished
        if not finished and card.get("board") in ("done", "archived"):
            finished = parse_date(fm.get("completedDate"))
        if not finished and card.get("board") in ("done", "archived"):
            last = max((r["date_obj"] for r in log if r["date_obj"]), default=None)
            finished = last or parse_date(fm.get("last_activity")) or parse_date(fm.get("updated"))
            approx = True
        return started, finished, approx

    def build(self, card, remote=True):
        note = self.note_of(card)
        fm = note.fm if note else {}
        text = note.text if note else ""
        raw = FRONT_RE.sub("", text, count=1)
        sync = SYNC_RE.search(raw)
        sync_commits = [{"date": m.group(1), "subject": m.group(2).strip()[:160]}
                        for m in SYNC_COMMIT_RE.finditer(sync.group(0))] if sync else []
        body = SYNC_RE.sub("", raw)
        secs = sections(body)
        slug, rel = card["slug"], card["path"]

        log = []
        for d, cells in log_rows(text):
            if not d:
                continue
            cells = cells + [""] * (5 - len(cells))
            log.append({"date": d.isoformat(), "date_obj": d, "category": cells[0].lower(),
                        "change": clean(cells[1], 300),
                        "details": [clean(x, 400) for x in re.split(r"<br\s*/?>", cells[2]) if x.strip()],
                        "status": cells[3], "tags": cells[4]})
        log.sort(key=lambda r: r["date"])

        events = list(reversed(self.store.events(card=slug, limit=2000)))
        moves, notes, blocked = [], [], []
        for ev in events:
            d = local_date(ev.get("ts", ""))
            ds = d.isoformat() if d else ev.get("ts", "")[:10]
            who = ev.get("agent") if ev.get("agent") not in (None, "web", "api") else (ev.get("actor") or "")
            ch = ev.get("changes") or {}
            if ev.get("type") == "move" and "board" in ch:
                moves.append({"date": ds, "from": ch["board"][0] or "", "to": ch["board"][1] or "", "who": who})
                if ch["board"][1] == "blocked":
                    reason = (ch.get("blocked_by") or [None, ""])[1] or card.get("blocked_by") or ""
                    blocked.append({"date": ds, "text": "moved to Blocked" + (": " + reason if reason else "")})
            elif ev.get("type") == "edit" and ch.get("blocked_by") and ch["blocked_by"][1]:
                blocked.append({"date": ds, "text": "blocked by: " + ch["blocked_by"][1]})
            elif ev.get("type") == "comment":
                notes.append({"date": ds, "who": who, "text": (ev.get("body") or "")[:400]})

        started, finished, approx = self.dates(card, fm, log, events)
        days = (finished - started).days if started and finished else None

        overview = paragraphs(section_text(secs, r"^overview$") or (secs[0][2] if secs and secs[0][0] == 0 else ""))
        if not overview:
            for level, title, txt in secs:
                if level >= 2 and title.lower() not in ("log", "status", "related notes") and paragraphs(txt, 1):
                    overview = paragraphs(txt)
                    break
        checks = []
        for level, title, txt in secs:
            for line in txt.splitlines():
                m = CHECK_RE.match(line)
                if m:
                    checks.append({"done": m.group(1).lower() == "x", "text": unwiki(m.group(2).strip()), "section": title})
        code = []
        for m in FENCE_RE.finditer(body):
            lines = [l for l in m.group(2).strip().splitlines() if l.strip()]
            if lines:
                code.append({"lang": m.group(1), "lines": lines[:4], "more": max(0, len(lines) - 4)})
            if len(code) >= 8:
                break
        images, seen = [], set()
        for m in EMBED_RE.finditer(body):
            name = m.group(1).strip()
            if name.lower().endswith(IMAGE_EXT) and name not in seen:
                seen.add(name)
                path = self.garden.assets.get(name.split("/")[-1])
                images.append({"name": name, "url": (self.garden_url + "/a/" + quote(path)) if path else ""})
        for m in MDIMG_RE.finditer(body):
            src = m.group(2)
            if src not in seen:
                seen.add(src)
                images.append({"name": m.group(1) or src.split("/")[-1], "url": src if src.startswith("http") else ""})
        links, seen = [], set()
        for m in MDLINK_RE.finditer(body):
            if m.group(2) not in seen:
                seen.add(m.group(2))
                links.append({"label": unwiki(m.group(1)), "url": m.group(2)})
        for m in BARE_URL_RE.finditer(body):
            u = m.group(0).rstrip(".,;:")
            if u not in seen:
                seen.add(u)
                links.append({"label": u, "url": u})
        links = [l for l in links if not l["url"].lower().endswith(IMAGE_EXT)][:25]
        if self.links:
            for l in links:
                rec = self.store.link(l["url"])
                if rec:
                    l["status"] = rec.get("status") or "unknown"
                    l["archive"] = rec.get("archive_url") or ""

        related = []
        if note:
            seen = set()
            for r in sorted(note.links) + sorted(self.garden.backlinks.get(rel, ())):   # sets: sorted, or the order (and the cut) varies per process
                n = self.garden.notes.get(r)
                if n and r not in seen and r != rel:
                    seen.add(r)
                    related.append({"title": n.title, "rel": r, "published": n.published,
                                    "url": self.garden_url + "/n/" + quote(n.slug)})
        related = related[:14]

        machines = {m.lower() for m in card.get("machines") or []}
        repo_name = card["repo"].rstrip("/").split("/")[-1].lower() if card.get("repo") else ""
        shared_repo = repo_name in machines  # e.g. a stack repo named after its machine
        needles = {slug.lower(), (card.get("title") or "").lower()}
        if repo_name and not shared_repo:
            needles.add(repo_name)
        needles = {n for n in needles if len(n) >= 3 and n not in machines}
        words = {w for w in re.findall(r"[a-z0-9]+", (card.get("title") or "").lower()) if len(w) >= 4 and w not in STOPWORDS}
        systems = []
        for r, fm2, text2 in self.timeline.notes():
            if not r.startswith("Systems/"):
                continue
            host = _str(fm2.get("title")) or r[8:-3]
            for d, cells in log_rows(text2):
                if not d:
                    continue
                row = " ".join(cells).lower()
                if any(n in row for n in needles):
                    systems.append({"date": d.isoformat(), "host": host, "change": clean(cells[1] if len(cells) > 1 else ""),
                                    "details": clean(cells[2] if len(cells) > 2 else "", 300)})
        systems.sort(key=lambda s: s["date"])

        vault_commits = []
        for line in self.store.git("log", "--format=%as\x1f%s", "--", os.path.join(VAULT, rel)).splitlines():
            try:
                when, subject = line.split("\x1f", 1)
            except ValueError:
                continue
            if not SKIP_COMMIT_RE.match(subject):
                vault_commits.append({"date": when, "subject": subject[:160]})
        vault_commits = vault_commits[:40]
        repos = [u for u in (card.get("repo"), _str(fm.get("mirror"))) if u and u.startswith("http")]
        repo_commits, repo_note = [], ""
        if repos and remote:
            got = self.repo_commits(repos[0], pages=4 if shared_repo else 1)
            if got is None:
                repo_note = "commits unavailable (no API for this remote, or it didn't answer)"
            else:
                repo_commits = got
        elif repos:
            repo_note = "not fetched"
        if shared_repo and repo_commits:
            repo_commits = [c for c in repo_commits
                            if any(n in c["subject"].lower() for n in needles | words)]
        if not repo_commits and sync_commits:
            repo_commits, repo_note = sync_commits, "from the note's Status block"

        milestones = [{"date": r["date"], "kind": r["category"],
                       "text": r["change"] + ((": " + "; ".join(r["details"])) if r["details"] else "")}
                      for r in log]
        milestones += [{"date": m["date"], "kind": "board",
                        "text": "%s \u2192 %s" % (SHORT.get(m["from"], m["from"] or "new"), SHORT.get(m["to"], m["to"]))}
                       for m in moves]
        if len(milestones) < 3:  # thin note: the commit log is the story
            milestones += [{"date": c["date"], "kind": "commit", "text": "commit: " + c["subject"]}
                           for c in reversed(repo_commits[:15])]
        milestones.sort(key=lambda m: m["date"])
        problems = [{"date": r["date"], "text": r["change"] + ((": " + "; ".join(r["details"])) if r["details"] else "")}
                    for r in log if r["category"] == "troubleshooting" or FIX_RE.search(r["change"] + " " + " ".join(r["details"]))]
        problems += [{"date": b["date"], "text": b["text"]} for b in blocked]
        problems += [{"date": c["date"], "text": "commit: " + c["subject"]} for c in repo_commits if FIX_RE.search(c["subject"])][:10]
        decisions = []
        for level, title, txt in secs:
            if level >= 2 and DECISION_HEAD_RE.search(title):
                decisions += bullets(txt, 10)
        for level, title, txt in secs:
            if level >= 2 and PROBLEM_HEAD_RE.search(title):
                problems += [{"date": "", "text": b, "section": title} for b in bullets(txt, 8)]
        numbers, seen = [], set()
        for r in log:
            for frag in [r["change"]] + r["details"]:
                for piece in re.split(r";\s+|\.\s+(?=[A-Z])", frag):
                    piece = piece.strip()
                    if (UNIT_RE.search(piece) or ARROW_RE.search(piece)) and piece not in seen:
                        seen.add(piece)
                        numbers.append({"date": r["date"], "text": piece})
        for level, title, txt in secs:
            if level >= 2 and not PROBLEM_HEAD_RE.search(title) and title.lower() != "log":
                for b in bullets(txt, 40):
                    for piece in re.split(r";\s+", b):
                        piece = piece.strip()
                        if (UNIT_RE.search(piece) or ARROW_RE.search(piece)) and piece not in seen and len(piece) < 220:
                            seen.add(piece)
                            numbers.append({"date": "", "text": piece})
        numbers = numbers[:20]
        open_checks = [c for c in checks if not c["done"]][:10]
        followups = []
        for c in self.store.cards():
            if c["slug"] == slug or c.get("board") in ("done", "archived", None):
                continue
            n = self.garden.notes.get(c["path"])
            if n and rel in n.links:
                followups.append({"title": c["title"], "slug": c["slug"], "board": c["board"]})

        topics = list(card.get("topics") or [])
        blog_ok = self.blog.available()
        tax = self.taxonomy()
        synonyms, area_category, default_category = tax["tag_synonyms"], tax["area_category"], tax["default_category"]
        matched, new_tags = self.blog.match_tags(topics + [synonyms[t] for t in topics if t in synonyms]) if blog_ok else ([], topics)
        new_tags = [t for t in new_tags if t in topics]
        mentions = self.blog.mentions(card, [l["url"] for l in links]) if blog_ok else []
        existing = [{"title": p.title, "date": p.date, "url": p.url} for p in mentions]
        for p in mentions:  # an earlier post about the same thing knows the right tags
            matched += [t for t in p.tags if t not in matched and t not in tax["ignore_tags"]][:4]
        category = (self.blog.category_for(matched, tax["ignore_categories"]) if matched else "") or area_category.get(card.get("area", ""), default_category)
        earlier = [{"title": p.title, "date": p.date, "url": p.url, "tags": p.tags}
                   for p in self.blog.by_tags(matched, 6, exclude={e["url"] for e in existing})] if matched else []
        today = datetime.date.today()
        post_slug = re.sub(r"[^A-Za-z0-9]+", "-", card["title"]).strip("-")
        front = "\n".join(["---", "layout: post", "title: %s" % yaml_str(card["title"]),
                           "description: %s" % yaml_str(card.get("summary") or ""),
                           *(["category: %s" % category] if category else []), "tags: %s" % " ".join(matched), "---"])
        filename = "_posts/%d/%s-%s.md" % (today.year, today.isoformat(), post_slug)

        return {
            "slug": slug, "title": card["title"], "summary": card.get("summary") or "", "path": rel,
            "board": card.get("board"), "area": card.get("area"), "topics": topics, "machines": card.get("machines") or [],
            "repos": repos, "started": started.isoformat() if started else "",
            "finished": finished.isoformat() if finished else "", "finished_approx": approx, "days": days,
            "card_url": self.board_url + "/p/" + quote(slug),
            "note_url": self.garden_url + "/n/" + quote(rel[:-3] if rel.endswith(".md") else rel),
            "published": bool(card.get("publish")), "post": card.get("post") or "none", "post_url": card.get("post_url") or "",
            "overview": overview, "code": code, "milestones": milestones, "problems": problems[:20], "numbers": numbers,
            "decisions": decisions,
            "open_checks": open_checks, "next": card.get("next") or "", "followups": followups,
            "log": [{k: v for k, v in r.items() if k != "date_obj"} for r in log], "moves": moves, "notes": notes,
            "systems": systems, "vault_commits": vault_commits, "repo_commits": repo_commits, "repo_note": repo_note,
            "images": images, "links": links, "related": related,
            "reading": self.hister.reading(card["title"], card.get("topics") or [],
                                           exclude=[l["url"] for l in links] + list(self.links.own_urls(rel) if self.links else ())
                                           )[0] if self.hister and remote else [],
            "blog": {"available": blog_ok, "front": front, "filename": filename, "category": category,
                     "tags": matched, "new_tags": new_tags, "earlier": earlier, "existing": existing},
            "size": {"milestones": len(milestones), "images": len(images), "days": days,
                     "facts": len(numbers) + len(problems)},
        }

    # -- markdown ---------------------------------------------------------------

    def markdown(self, k):
        L = ["# Writing kit: %s" % k["title"], ""]
        if k["summary"]:
            L += [k["summary"], ""]
        when = "%s \u2192 %s%s" % (k["started"] or "?", k["finished"] or "(not finished)", " (approx.)" if k["finished_approx"] else "")
        if k["days"] is not None:
            when += ", %d days" % k["days"]
        L.append("- **When:** " + when)
        for r in k["repos"]:
            L.append("- **Repo:** " + r)
        if k["machines"]:
            L.append("- **Machines:** " + ", ".join(k["machines"]))
        if k["topics"]:
            L.append("- **Topics:** " + ", ".join(k["topics"]))
        L.append("- **Card:** %s \u00b7 **Note:** `%s`" % (k["card_url"], k["path"]))
        L.append("- **Garden:** %s (%s)" % (k["note_url"], "published" if k["published"] else "private preview"))
        L.append("- **Post:** %s%s" % (k["post"], (" " + k["post_url"]) if k["post_url"] else ""))
        s = k["size"]
        L.append("- **Kit size:** %d milestones, %d images, %d numbers, %d problems" % (
            s["milestones"], len(k["images"]), len(k["numbers"]), len(k["problems"])))
        L += ["", "## Front matter", ""]
        b = k["blog"]
        if b["available"]:
            L += ["```yaml", b["front"], "```", "", "File: `%s`" % b["filename"]]
            if b["new_tags"]:
                L.append("Topics the blog has no tag for yet: " + ", ".join(b["new_tags"]) + " (add them or pick canonical ones).")
            if b["existing"]:
                L += ["", "**Already written?** These posts mention this project:"]
                L += ["- [%s](%s) (%s)" % (e["title"], e["url"], e["date"]) for e in b["existing"]]
        else:
            L += ["```yaml", b["front"], "```", "", "_The blog repo isn't mounted, so tags and category are guesses._"]
        L += ["", "## Suggested outline", "", "### 1. Why", ""]
        L += k["overview"] or ["_No overview paragraph in the note._"]
        L += ["", "### 2. What was built", ""]
        L += ["- Repo: " + r for r in k["repos"]]
        if k["machines"]:
            L.append("- Runs on: " + ", ".join(k["machines"]))
        for c in k["code"]:
            L += ["", "```" + c["lang"]] + c["lines"] + (["\u2026 (+%d lines)" % c["more"]] if c["more"] else []) + ["```"]
        if k.get("decisions"):
            L += ["", "Decisions:"] + ["- " + d for d in k["decisions"]]
        if not k["repos"] and not k["machines"] and not k["code"] and not k.get("decisions"):
            L.append("_No repo, machine or code block recorded in the note._")
        L += ["", "### 3. How it went", ""]
        L += ["- %s \u2014 %s" % (m["date"], m["text"]) for m in k["milestones"]] or ["_No dated milestones. Add Log rows or board moves._"]
        L += ["", "### 4. Problems and fixes", ""]
        L += ["- %s%s" % ((p["date"] + " \u2014 ") if p["date"] else "", p["text"]) for p in k["problems"]] or ["_Nothing flagged as a fix, gotcha or block._"]
        L += ["", "### 5. Results and numbers", ""]
        L += ["- %s%s" % ((n["date"] + " \u2014 ") if n["date"] else "", n["text"]) for n in k["numbers"]] or ["_No figures found in the Log or the note's bullets._"]
        L += ["", "### 6. What's next", ""]
        L += ["- [ ] " + c["text"] for c in k["open_checks"]]
        if k["next"]:
            L.append("- next: " + k["next"])
        L += ["- follow-up card: %s (%s)" % (f["title"], SHORT.get(f["board"], f["board"])) for f in k["followups"]]
        if not k["open_checks"] and not k["next"] and not k["followups"]:
            L.append("_Nothing open._")
        L += ["", "## Material", "", "### Log (%d rows)" % len(k["log"]), ""]
        if k["log"]:
            L += ["| Date | Category | Change | Details |", "|---|---|---|---|"]
            L += ["| %s | %s | %s | %s |" % (r["date"], cell(r["category"]), cell(r["change"]), cell("; ".join(r["details"]))) for r in k["log"]]
        L += ["", "### Board events (%d)" % (len(k["moves"]) + len(k["notes"])), ""]
        L += ["- %s \u2014 %s \u2192 %s%s" % (m["date"], SHORT.get(m["from"], m["from"] or "new"), SHORT.get(m["to"], m["to"]),
                                             (" (%s)" % m["who"]) if m["who"] else "") for m in k["moves"]]
        L += ["- %s \u2014 %s%s" % (n["date"], n["text"], (" (%s)" % n["who"]) if n["who"] else "") for n in k["notes"]]
        L += ["", "### Machine changes mentioning the project (%d)" % len(k["systems"]), ""]
        L += ["- %s \u2014 %s: %s%s" % (s["date"], s["host"], s["change"], (" \u2014 " + s["details"]) if s["details"] else "") for s in k["systems"]]
        L += ["", "### Vault commits touching the note (%d)" % len(k["vault_commits"]), ""]
        L += ["- %s \u2014 %s" % (c["date"], c["subject"]) for c in k["vault_commits"]]
        if k["repos"]:
            L += ["", "### Repo commits (%d)%s" % (len(k["repo_commits"]), (": " + k["repo_note"]) if k["repo_note"] else ""), ""]
            L += ["- %s \u2014 %s" % (c["date"], c["subject"]) for c in k["repo_commits"]]
        L += ["", "### Images (%d)" % len(k["images"]), ""]
        L += ["- %s%s" % (i["name"], (" \u2014 " + i["url"]) if i["url"] else "") for i in k["images"]]
        L += ["", "### Links (%d)" % len(k["links"]), ""]
        for l in k["links"]:
            line = ("- [%s](%s)" % (l["label"], l["url"])) if l["label"] != l["url"] else "- " + l["url"]
            if l.get("status") == "dead":
                line += " \u2014 dead" + ((", archived: " + l["archive"]) if l.get("archive") else ", no archived copy")
            elif l.get("archive"):
                line += " \u2014 archived: " + l["archive"]
            L.append(line)
        if k.get("reading"):
            L += ["", "### Pages I've read (%d, from Hister)" % len(k["reading"]), ""]
            L += ["- [%s](%s) (%s%s%s)" % (r["title"].replace("]", ")"), r["url"], r["domain"],
                                         ", saved " + r["added"] if r["added"] else "", "; " + r["why"] if r["why"] else "")
                  for r in k["reading"]]
        L += ["", "### Related notes (%d)" % len(k["related"]), ""]
        L += ["- %s%s" % (r["title"], " (in the garden: %s)" % r["url"] if r["published"] else "") for r in k["related"]]
        if b["earlier"]:
            L += ["", "### Earlier posts on these topics", ""]
            L += ["- [%s](%s) (%s; %s)" % (e["title"], e["url"], e["date"], " ".join(e["tags"])) for e in b["earlier"]]
        return "\n".join(L).rstrip() + "\n"

    def warm(self, first_delay=30, every=6 * 3600):
        """Keep repo commit lists warm so kit pages never wait on the forge."""
        time.sleep(first_delay)
        while True:
            try:
                n = 0
                for c in self.store.cards():
                    repo = c.get("repo")
                    if repo and repo.startswith("http") and c.get("board") in ("wip", "blocked", "ready", "done", "archived"):
                        machines = {m.lower() for m in c.get("machines") or []}
                        shared = repo.rstrip("/").split("/")[-1].lower() in machines
                        self.repo_commits(repo, pages=4 if shared else 1)
                        n += 1
                        time.sleep(1)
                print("kits: warmed %d repos" % n, flush=True)
            except Exception as exc:
                print("kits: warm failed: %s" % exc, flush=True)
            time.sleep(every)

    def html(self, md):
        import markdown
        return markdown.markdown(md, extensions=["tables", "fenced_code"], output_format="html")

    # -- the /posts view ---------------------------------------------------------

    def posts(self):
        """Cards for the /posts page: ready to write (Done or archived, no
        published post), in progress (a post status on an unfinished card),
        and published."""
        ready, progress, published, skipped = [], [], [], []
        for c in self.store.cards():
            status = c.get("post") or "none"
            if status == "published":
                published.append({"card": c, "url": c.get("post_url") or ""})
                continue
            if status == "skipped":
                skipped.append({"card": c})
                continue
            finished_col = c.get("board") in ("done", "archived")
            if finished_col or status != "none":
                k = self.build(c, remote=False)
                entry = {"card": c, "finished": k["finished"], "approx": k["finished_approx"], "size": k["size"],
                         "existing": k["blog"]["existing"], "status": status}
                (ready if finished_col else progress).append(entry)
        ready.sort(key=lambda e: e["finished"] or "", reverse=True)
        published.sort(key=lambda e: e["card"]["title"].lower())
        skipped.sort(key=lambda e: e["card"]["title"].lower())
        return {"ready": ready, "progress": progress, "published": published, "skipped": skipped}
