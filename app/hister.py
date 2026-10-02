"""Hister (optional): a private search engine and page archive, reached at KANBAN_HISTER_URL
(for example http://hister.example:4433). Unset = these features are off.

Konbini uses it two ways: link rot shows a private copy of external links (links.HisterBackend), and card
pages and writing kits list "pages I've read". (The vault push into Hister is Kura's.)

Every call sends `Origin: hister://` (without it Hister answers 500/403).
There is no token: the network path to Hister (private) is the gate. API calls go
to KANBAN_HISTER_URL (http://hister.example:4433); links shown in the browser use
KANBAN_HISTER_PUBLIC (Hister's own address, as your browser reaches it).

Privacy: everything from here is single-user. Search results, copies and
private_url stay on the board's authenticated pages."""
import datetime
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE_SECONDS = 600
STOP = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "from", "into", "my", "our", "via",
        "migration", "project", "setup", "stack", "notes", "tuning", "fix", "fixes", "new", "old"}


def ts_date(value):
    try:
        return datetime.datetime.fromtimestamp(int(value), datetime.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def domain_of(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class Hister:
    def __init__(self, api, public, cli="hister"):
        self.api = api.rstrip("/")
        self.public = (public or api).rstrip("/")
        self.cli = cli
        self.lock = threading.Lock()
        self.cache = {}
        self.error = ""
        self.last_ok = ""

    # -- transport ---------------------------------------------------------------

    def call(self, method, path, body=None, timeout=10):
        """(status, parsed JSON or text); status 0 when Hister can't be reached."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.api + path, data=data, method=method, headers={
            "Origin": "hister://", "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.error = "hister unreachable: %s" % e
            return 0, None
        self.last_ok = datetime.datetime.now().isoformat(timespec="seconds")
        if status < 500:
            self.error = ""
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    # -- search ------------------------------------------------------------------

    def search(self, q, timeout=4):
        """Documents matching a Hister query (first page, up to 100), cached briefly."""
        now = time.time()
        with self.lock:
            hit = self.cache.get(q)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1], hit[2]
        status, data = self.call("GET", "/search?q=" + urllib.parse.quote(q), timeout=timeout)
        if status != 200 or not isinstance(data, dict):
            return [], 0
        docs, total = data.get("documents") or [], data.get("total") or 0
        with self.lock:
            if len(self.cache) > 500:
                self.cache.clear()
            self.cache[q] = (now, docs, total)
        return docs, total

    def find(self, url):
        """The document Hister holds for a URL (or its normalised form), or None."""
        from urlnorm import norm
        for u in dict.fromkeys((url, norm(url))):
            status, data = self.call("GET", "/search?q=" + urllib.parse.quote('url:"%s"' % u.replace('"', "%22")))
            if status == 200 and isinstance(data, dict):
                for d in data.get("documents") or []:
                    if d.get("url") in (url, u):
                        return d
        return None

    def preview_url(self, url):
        return "%s/preview?id=%s" % (self.public, urllib.parse.quote(url, safe=""))

    def search_url(self, q):
        return "%s/?q=%s" % (self.public, urllib.parse.quote(q))

    # -- writes ------------------------------------------------------------------

    def add(self, doc):
        """POST a whole document. True when Hister stored it."""
        status, data = self.call("POST", "/api/add", doc, timeout=30)
        if status not in (200, 201):
            self.error = "add %s: HTTP %s %s" % (doc.get("url", "")[:80], status, str(data or "")[:80])
            return False
        return True

    def delete(self, url):
        status, data = self.call("POST", "/api/delete", {"query": 'url:"%s"' % url.replace('"', "%22")}, timeout=30)
        return (data or {}).get("deleted", 0) if status == 200 and isinstance(data, dict) else 0

    def index(self, url, label="konbini"):
        """Fetch and store a page with the hister CLI (/api/add alone doesn't fetch).
        Callers check find() first: --force on an existing document would
        replace its metadata (the imported tags and archive link)."""
        try:
            r = subprocess.run([self.cli, "-u", self.api, "index", "--label", label, url],
                               capture_output=True, text=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as e:
            self.error = "hister index failed: %s" % e
            return False
        if r.returncode != 0:
            self.error = "hister index %s: %s" % (url[:80], (r.stderr or r.stdout).strip()[:120])
            return False
        return True

    # -- pages I've read -----------------------------------------------------------

    def reading(self, title, topics=(), limit=8, exclude=()):
        """Pages from Hister about a card. Title words must all be in a page's
        title (precise); then each topic, as a phrase if it has several words
        or as a title word if it has one (at most 2 pages per topic). Vault
        notes, tailnet pages and the card's own links are left out. Returns
        (pages, query): each page has the original URL (public), Hister's copy
        (private) and why it matched."""
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", title) if w.lower() not in STOP and len(w) > 2]
        queries = []
        if words:
            queries.append((" ".join("title:" + w for w in words), "", 5))  # terms AND by default; "+field:" isn't supported
            if len(words) > 1:
                queries.append(('"%s"' % " ".join(words), "", 5))
        for t in topics or ():
            t = t.replace("-", " ").strip().lower()
            if t and t not in words:
                queries.append((('"%s"' % t) if " " in t else "title:" + t, t, 2))
        from urlnorm import norm
        out, seen = [], {norm(u) for u in exclude if u}
        for q, why, cap in queries:
            docs, _ = self.search(q + " -label:vault")
            taken = 0
            for d in docs:
                u = d.get("url") or ""
                if not u or norm(u) in seen or (urllib.parse.urlsplit(u).hostname or "").endswith(".ts.net"):
                    continue
                seen.add(norm(u))
                meta = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
                out.append({"title": (d.get("title") or u).strip()[:140], "url": meta.get("original_url") or u,
                            "domain": domain_of(u), "added": ts_date(d.get("added")), "label": d.get("label") or "",
                            "copy": self.preview_url(u), "why": why})
                taken += 1
                if taken >= cap or len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        return out[:limit], (" ".join(words) or " ".join(topics or ()))

    def saved_between(self, start, end):
        """Pages added to Hister in [start, end): count plus the biggest groups
        (an imported folder label, else domain). Vault notes and Konbini's own
        link-rot saves (label konbini) don't count."""
        q = "added:>=%s added:<%s -label:vault -label:konbini" % (start.isoformat(), end.isoformat())
        docs, total = self.search(q)
        groups = {}
        for d in docs:
            key = d.get("label") or domain_of(d.get("url") or "")
            if key:
                groups[key] = groups.get(key, 0) + 1
        top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:4]
        return {"total": total, "top": top, "search": self.search_url("added:>=%s added:<%s" % (start.isoformat(), end.isoformat()))}

    def status(self):
        return {"api": self.api, "error": self.error, "last_ok": self.last_ok}
