"""Read-only view of a Jekyll blog (optional), a checkout mounted at
KANBAN_BLOG with its public address in KANBAN_BLOG_URL; without the mount the writing kits skip it. Posts are
_posts/**/YYYY-MM-DD-slug.{md,html} with front matter (layout, title, description, category, tags as a
space-separated string); a post's address is KANBAN_BLOG_URL plus KANBAN_BLOG_PERMALINK (a pattern with {year}
and {slug}, default "/{year}/{slug}/"). Optional tag/<tag>.md pages count as known tags. The board never writes
here; the writing kit only reads tags, categories and earlier posts."""
import os
import re
import time
from collections import Counter

from store import _str, note_front

POST_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.(md|markdown|html)$")
DEFAULT_PERMALINK = "/{year}/{slug}/"
KV_RE = re.compile(r"^([A-Za-z_]+):\s*(.*?)\s*$")
FRONT_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def front(text):
    """Front matter as a dict; falls back to key: value lines when the YAML
    is loose (unquoted colons in old titles)."""
    fm = note_front(text)
    if fm is not None:
        return fm
    out = {}
    m = FRONT_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            k = KV_RE.match(line)
            if k:
                out[k.group(1)] = k.group(2).strip("\"'")
    return out


def normalize_url(u):
    return re.sub(r"^https?://(www\.)?", "", u or "").rstrip("/").lower()


class Post:
    __slots__ = ("path", "date", "year", "slug", "title", "description", "category", "tags", "url", "text")


class Blog:
    def __init__(self, root, site_url, permalink=None):
        self.root = root or ""
        self.site = (site_url or "").rstrip("/")
        self.permalink = (permalink or "").strip() or DEFAULT_PERMALINK
        try:
            self.permalink.format(year="2026", slug="x")
        except (KeyError, IndexError, ValueError):
            self.permalink = DEFAULT_PERMALINK
        self._cache = (0.0, [])

    def available(self):
        return bool(self.root) and os.path.isdir(os.path.join(self.root, "_posts"))

    def posts(self):
        if not self.available():
            return []
        now = time.time()
        if now - self._cache[0] < 300:
            return self._cache[1]
        out = []
        for dirpath, _dirs, files in os.walk(os.path.join(self.root, "_posts")):
            for name in files:
                m = POST_RE.match(name)
                if not m:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                fm = front(text)
                p = Post()
                p.path = os.path.relpath(full, self.root)
                p.date = "%s-%s-%s" % m.group(1, 2, 3)
                p.year, p.slug = m.group(1), m.group(4)
                p.title = _str(fm.get("title")) or p.slug.replace("-", " ")
                p.description = _str(fm.get("description"))
                cat = fm.get("category") or fm.get("categories") or ""
                if isinstance(cat, list):
                    cat = cat[0] if cat else ""
                p.category = _str(cat).lower()
                tags = fm.get("tags") or []
                if isinstance(tags, str):
                    tags = tags.replace(",", " ").split()
                p.tags = [str(t).lower() for t in tags]
                p.url = self.site + self.permalink.format(year=p.year, slug=p.slug)
                p.text = FRONT_RE.sub("", text, count=1)
                out.append(p)
        out.sort(key=lambda p: p.date, reverse=True)
        self._cache = (now, out)
        return out

    def tags(self):
        """Canonical tags: every tag in use plus the generated tag/ pages."""
        counts = Counter(t for p in self.posts() for t in p.tags)
        tagdir = os.path.join(self.root, "tag")
        if os.path.isdir(tagdir):
            for name in os.listdir(tagdir):
                if name.endswith(".md"):
                    counts.setdefault(name[:-3].lower(), 0)
        return counts

    def match_tags(self, topics):
        """(tags the blog already uses, topics it doesn't)."""
        known = self.tags()
        matched, new = [], []
        for t in topics:
            t = t.lower()
            for cand in (t, t.replace("-", ""), t.replace("_", "-"), t.rstrip("s")):
                if cand in known:
                    if cand not in matched:
                        matched.append(cand)
                    break
            else:
                new.append(t)
        return matched, new

    def category_for(self, tags, ignore=()):
        counts = Counter(p.category for p in self.posts()
                         if p.category and p.category not in ignore and set(p.tags) & set(tags))
        return counts.most_common(1)[0][0] if counts else ""

    def by_tags(self, tags, limit=6, exclude=()):
        want = set(tags)
        skip = {normalize_url(u) for u in exclude}
        scored = [(len(want & set(p.tags)), p) for p in self.posts()
                  if want & set(p.tags) and normalize_url(p.url) not in skip]
        scored.sort(key=lambda t: t[1].date, reverse=True)
        scored.sort(key=lambda t: -t[0])
        return [p for _, p in scored[:limit]]

    def mentions(self, card, note_links=()):
        """Posts that look like they're about this card: linked from the
        note, or mentioning its slug or title."""
        needles = {card["slug"].lower()}
        title = (card.get("title") or "").lower()
        if len(title) >= 5:
            needles.add(title)
        links = {normalize_url(u) for u in note_links}
        out = []
        for p in self.posts():
            hay = (p.title + "\n" + p.text).lower()
            if normalize_url(p.url) in links or any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(n), hay) for n in needles):
                out.append(p)
        return out
