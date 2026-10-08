"""Hister (optional): a private search engine and page archive, reached at KANBAN_HISTER_URL
(for example http://hister.example:4433). Unset = these features are off.

Konbini uses it two ways: link rot shows a private copy of external links (links.HisterBackend), and card
pages and writing kits list "pages I've read". (The vault push into Hister is Kura's.)

Every call sends `Origin: hister://` (without it Hister answers 500/403).
With KANBAN_HISTER_TOKEN_FILE (the owner's Hister token, a file holding one line) every call also sends it as
`X-Access-Token`, and the hister CLI gets it as HISTER__APP__ACCESS_TOKEN in its own environment (never on its
command line). The file is read at each call, so a rotated token needs no restart; the value is never logged, shown
on a page or returned by the API. Unset: no token is sent, and the network path to Hister (private) is the gate.
API calls go to KANBAN_HISTER_URL (http://hister.example:4433); links shown in the browser use
KANBAN_HISTER_PUBLIC (Hister's own address, as your browser reaches it).

Privacy: everything from here is single-user. Search results, copies and
private_url stay on the board's authenticated pages."""
import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from vaultkit import websafe

CACHE_SECONDS = 600
# The code-import service (docs/contracts/hister.md) stores the owner's repositories, READMEs, issues and releases in
# Hister as documents with metadata.source "code". Only Shiori's Code area shows them: every query from here leaves them out,
# and a result that is one anyway (an old Hister, a query that wasn't understood) is dropped, so they are never "pages I've
# read" or a saved copy.
NOT_CODE = " -metadata.source:code"
STOP = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "from", "into", "my", "our", "via",
        "migration", "project", "setup", "stack", "notes", "tuning", "fix", "fixes", "new", "old"}


def ts_date(value):
    try:
        return datetime.datetime.fromtimestamp(int(value), datetime.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def is_code(doc):
    meta = doc.get("metadata") if isinstance(doc, dict) else None
    return isinstance(meta, dict) and meta.get("source") == "code"


def domain_of(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class Hister:
    def __init__(self, api, public, cli="hister", token_file=""):
        self.api = api.rstrip("/")
        self.public = (public or api).rstrip("/")
        self.cli = cli
        self.token_file = token_file
        self.token_problem = ""       # a token file that is set but missing or empty: shown as the error until it is fixed
        self.lock = threading.Lock()
        self.cache = {}
        self.error = ""
        self.last_ok = ""

    # -- transport ---------------------------------------------------------------

    def token(self):
        """The owner's Hister token from KANBAN_HISTER_TOKEN_FILE (read each time, so a rotation is picked up); "" when
        no file is set, or it is missing or empty (then nothing is sent, and the error names the file, not a value)."""
        if not self.token_file:
            return ""
        self.token_problem = ""
        try:
            with open(self.token_file, encoding="utf-8") as f:
                value = f.read().strip()
        except (OSError, UnicodeDecodeError):
            value = ""
        if not value:
            self.token_problem = self.error = "hister token file %s is missing or empty" % self.token_file
        return value

    def scrub(self, text, token):
        """`text` (an error from Hister or the CLI) without the token, in case something echoed it."""
        return text.replace(token, "***") if token else text

    def call(self, method, path, body=None, timeout=10):
        """(status, parsed JSON or text); status 0 when Hister can't be reached."""
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Origin": "hister://", "Accept": "application/json", "Content-Type": "application/json"}
        token = self.token()
        if token:
            headers["X-Access-Token"] = token
        req = urllib.request.Request(self.api + path, data=data, method=method, headers=headers)
        try:
            with websafe.token_opener().open(req, timeout=timeout) as r:      # no redirects: the token goes nowhere else
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.error = "hister unreachable: %s" % self.scrub(str(e), token)
            return 0, None
        self.last_ok = datetime.datetime.now().isoformat(timespec="seconds")
        if status < 500:
            self.error = self.token_problem
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
        status, data = self.call("GET", "/search?q=" + urllib.parse.quote(q + NOT_CODE), timeout=timeout)
        if status != 200 or not isinstance(data, dict):
            return [], 0
        docs, total = data.get("documents") or [], data.get("total") or 0
        kept = [d for d in docs if not is_code(d)]
        total, docs = max(0, total - (len(docs) - len(kept))) if isinstance(total, int) else total, kept
        with self.lock:
            if len(self.cache) > 500:
                self.cache.clear()
            self.cache[q] = (now, docs, total)
        return docs, total

    def find(self, url):
        """The document Hister holds for a URL (or its normalised form), or None."""
        from urlnorm import norm
        for u in dict.fromkeys((url, norm(url))):
            status, data = self.call("GET", "/search?q=" + urllib.parse.quote('url:"%s"' % u.replace('"', "%22") + NOT_CODE))
            if status == 200 and isinstance(data, dict):
                for d in data.get("documents") or []:
                    if d.get("url") in (url, u) and not is_code(d):
                        return d
        return None

    def preview_url(self, url):
        return "%s/preview?id=%s" % (self.public, urllib.parse.quote(url, safe=""))

    def search_url(self, q):
        return "%s/?q=%s" % (self.public, urllib.parse.quote(q + NOT_CODE))

    # -- writes ------------------------------------------------------------------

    def add(self, doc):
        """POST a whole document. True when Hister stored it."""
        status, data = self.call("POST", "/api/add", doc, timeout=30)
        if status not in (200, 201):
            self.error = "add %s: HTTP %s %s" % (doc.get("url", "")[:80], status, str(data or "")[:80])
            return False
        return True

    def delete(self, url):
        status, data = self.call("POST", "/api/delete", {"query": 'url:"%s"' % url.replace('"', "%22") + NOT_CODE}, timeout=30)
        return (data or {}).get("deleted", 0) if status == 200 and isinstance(data, dict) else 0

    def index(self, url, label="konbini"):
        """Fetch and store a page with the hister CLI (/api/add alone doesn't fetch).
        Callers check find() first: --force on an existing document would
        replace its metadata (the imported tags and archive link)."""
        env = dict(os.environ)
        env.pop("HISTER__APP__ACCESS_TOKEN", None)      # no token file, no token: nothing inherited either
        token = self.token()
        if token:
            env["HISTER__APP__ACCESS_TOKEN"] = token     # the CLI's own setting, in its environment only (not argv)
        try:
            r = subprocess.run([self.cli, "-u", self.api, "index", "--label", label, url],
                               capture_output=True, text=True, timeout=120, env=env)
        except (subprocess.SubprocessError, OSError) as e:
            self.error = "hister index failed: %s" % self.scrub(str(e), token)
            return False
        if r.returncode != 0:
            self.error = "hister index %s: %s" % (url[:80], self.scrub((r.stderr or r.stdout).strip()[:120], token))
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
