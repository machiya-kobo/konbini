"""Link rot: an archived copy next to every external link (the Gwern pattern).

Konbini collects the external links of every card's note (Niwa checks the
published notes' links itself), checks each one on a slow schedule, saves a copy at the
Wayback Machine (only with KANBAN_ARCHIVE=wayback) and remembers the
result in the board's database. Card pages mark dead links and point them at their
archived copy, and the writing kit says which sources are still live. Nothing is written
into the notes.

Two kinds of copy, kept apart on purpose:
- archive_url: the public copy (Wayback Machine). Backends implement
  lookup(url) / save(url) -> (archive_url, when) or None.
- private_url: the private copy. A cold archive's snapshot when there is one
  (a urlmap.json), else Hister's copy; with KANBAN_HISTER_SAVE a live link
  Hister doesn't have yet is indexed into it.
Public pages read only archive_url; private_url is for the board's own pages."""
import datetime
import json
import os
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from store import VAULT

URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]`]+")
# Private hosts are never checked: loopback, LAN ranges, and any tailnet (*.ts.net); KANBAN_LINKS_SKIP_HOSTS adds more.
SKIP_HOSTS = ("web.archive.org", "archive.org", "localhost", "127.0.0.1", "ts.net", "192.168.", "10.", "100.") + tuple(
    h.strip() for h in os.environ.get("KANBAN_LINKS_SKIP_HOSTS", "").split(",") if h.strip())
# The link checker's User-Agent; a deploy may add a contact URL, e.g. "konbini-links/1 (+https://example.com)".
UA = os.environ.get("KANBAN_LINKS_USER_AGENT", "").strip() or "konbini-links/1"
CHECK_DAYS = 7          # re-check a link this often
BATCH_CHECK = 25        # per hourly run
BATCH_SAVE = 8          # archive saves per hourly run (Wayback rate limits)
BATCH_PRIVATE = 40      # private copies per hourly run (local, no rate limit)
COLD_REFRESH = 86400    # re-read the cold archive's urlmap.json daily
DEAD_CODES = (404, 410, 451)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_url(u):
    return u.rstrip(".,;:!?…")


PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".localhost", ".home.arpa", ".intranet", ".corp", ".private")


class PrivateHost(Exception):
    """The address isn't a public one: never fetched (a link in a note must not make the board call into the private
    network: a blind SSRF)."""


def is_external(url):
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if not host or "." not in host:  # short names on a private network (e.g. konbini) and localhost
        return False
    if host.endswith(PRIVATE_SUFFIXES):
        return False
    try:
        if not ipaddress.ip_address(host).is_global:        # an address as the host: only a public one
            return False
    except ValueError:
        pass
    return not any(host == h or host.endswith("." + h) or host.startswith(h) for h in SKIP_HOSTS)


def check_public(url):
    """PrivateHost unless every address `url`'s host resolves to is a public one (IPv4 and IPv6)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        raise PrivateHost("not an http(s) address")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, ValueError, OSError):
        raise PrivateHost("the name doesn't resolve")
    if not infos:
        raise PrivateHost("the name doesn't resolve")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise PrivateHost("%s is not a public address" % host)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None             # every hop is followed by hand, and checked


def safe_request(url, method="GET", headers=None, timeout=15, hops=5):
    """(status, final URL) of a request whose every hop (the first address and each redirect) goes to a public address only.
    HTTPError for a 4xx or 5xx, PrivateHost for a private hop. No proxy is used."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    for _ in range(hops + 1):
        check_public(url)
        try:
            with opener.open(urllib.request.Request(url, method=method, headers=headers or {}), timeout=timeout) as r:
                return r.status, url
        except urllib.error.HTTPError as e:
            where = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if not where:
                raise
            url = urllib.parse.urljoin(url, where)
    raise PrivateHost("too many redirects")


def extract(text):
    out, seen = [], set()
    for m in URL_RE.finditer(text):
        u = clean_url(m.group(0))
        if u not in seen and is_external(u):
            seen.add(u)
            out.append(u)
    return out


# -- backends ----------------------------------------------------------------

class WaybackBackend:
    name = "wayback"

    def lookup(self, url):
        # the availability API wants the URL without its scheme
        q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url.split("://", 1)[-1], safe="/")
        req = urllib.request.Request(q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            ts = snap.get("timestamp", "")
            when = "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8]) if len(ts) >= 8 else ""
            return snap["url"].replace("http://web.archive.org", "https://web.archive.org"), when
        return None

    def save(self, url):
        req = urllib.request.Request("https://web.archive.org/save/" + url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            loc = r.headers.get("Content-Location") or ""
            final = r.geturl()
        if loc.startswith("/web/"):
            return "https://web.archive.org" + loc, now_iso()[:10]
        if "/web/" in final:
            return final, now_iso()[:10]
        return None


class ColdArchive:
    """A cold archive's snapshots, read from a urlmap.json that something else keeps up to date (KANBAN_COLD_MAP, an
    address): {"urls": {norm(url): {"snapshot": address, "date": "YYYY-MM-DD", "raw": original url}}}, keyed by
    urlnorm.norm(url). Optional: unset, there is no cold archive."""
    name = "cold"

    def __init__(self, map_url):
        self.map_url = map_url
        self.urls, self.loaded, self.error = {}, 0.0, ""

    def refresh(self):
        if time.time() - self.loaded < COLD_REFRESH and self.urls:
            return
        try:
            with urllib.request.urlopen(urllib.request.Request(self.map_url, headers={"User-Agent": UA}), timeout=30) as r:
                self.urls = json.loads(r.read().decode("utf-8")).get("urls") or {}
            self.loaded, self.error = time.time(), ""
        except Exception as exc:  # keep the old map
            self.error = "urlmap: %s" % str(exc)[:100]
            self.loaded = time.time() - COLD_REFRESH + 600  # retry in 10 minutes

    def lookup(self, url):
        from urlnorm import norm
        self.refresh()
        hit = self.urls.get(norm(url))
        return (hit["snapshot"], hit.get("date") or "") if hit and hit.get("snapshot") else None


def setting_on(value):
    """A switch setting (KANBAN_HISTER_SAVE): `1`, `on` or `true` is on; anything else, or unset, is off."""
    return (value or "").strip().lower() in ("1", "true", "on")


def archive_mode(value):
    """KANBAN_ARCHIVE -> (mode, warning): only the exact `wayback` turns the Wayback lookup and save on. Empty or
    `none` (the default) is off; anything else is off too, with a warning for the start-up log."""
    value = (value or "").strip()
    if value in ("", "none"):
        return "none", ""
    if value == "wayback":
        return "wayback", ""
    return "none", "KANBAN_ARCHIVE=%r is not `wayback`: Wayback lookups and saves stay off" % value


class HisterBackend:
    """Hister's copy of a page (hister.Hister). save() indexes only URLs that
    Hister doesn't hold yet: re-indexing an existing document would replace
    its metadata (the imported tags and cold-archive link)."""
    name = "hister"

    def __init__(self, hister):
        self.h = hister

    def lookup(self, url):
        from hister import ts_date
        d = self.h.find(url)
        return (self.h.preview_url(d["url"]), ts_date(d.get("updated") or d.get("added"))) if d else None

    def final_url(self, url):
        """Where a URL redirects to: Hister stores the page under its final address."""
        try:
            return safe_request(url, "HEAD", {"User-Agent": UA})[1]
        except Exception:
            return url

    def save(self, url):
        found = self.lookup(url)
        if found:
            return found
        final = self.final_url(url)
        if final != url:
            found = self.lookup(final)
            if found:
                return found
        try:
            check_public(url)       # the hister command fetches it: not into the private network either
        except PrivateHost:
            return None
        if not self.h.index(url):
            return None
        for _ in range(4):  # Hister indexes in the background
            time.sleep(2)
            found = self.lookup(url) or (self.lookup(final) if final != url else None)
            if found:
                return found
        return None


class Links:
    def __init__(self, store, garden, backends=(), enabled=True, cold=None, hister=None, hister_save=False):
        self.store, self.garden = store, garden
        self.hister_save = hister_save   # KANBAN_HISTER_SAVE: index pages Hister lacks (off: only show Hister's copy)
        self.backends = list(backends)
        self.cold, self.hister = cold, hister  # private copies (single-user)
        self.enabled = enabled
        self.lock = threading.Lock()
        self.last_run = ""

    # -- collect ---------------------------------------------------------------

    def collect(self):
        """Register the external links of card notes (published notes are Niwa's)."""
        self.garden.index()
        cards = {c["path"] for c in self.store.cards()}
        refs = {}
        for n in self.garden.notes.values():
            if n.rel not in cards:
                continue
            for u in extract(n.text):
                refs.setdefault(u, set()).add(n.rel)
        added = 0
        for u, rels in refs.items():
            rec = self.store.link(u)
            notes = "\n".join(sorted(rels))
            if rec:
                if rec.get("notes") != notes:
                    self.store.link_set(u, notes=notes)
            else:
                self.store.link_set(u, first_seen=now_iso(), status="unknown", fails=0, notes=notes)
                added += 1
        return added

    # -- check -----------------------------------------------------------------

    def probe(self, url):
        """HTTP status of a link, or None when it can't be reached."""
        for method in ("HEAD", "GET"):
            try:
                return safe_request(url, method, {"User-Agent": UA, "Accept": "*/*"})[0]
            except PrivateHost:
                return None         # a private address (or a redirect into one) is never fetched
            except urllib.error.HTTPError as e:
                if method == "HEAD" and e.code in (405, 403, 501):
                    continue
                return e.code
            except Exception:
                if method == "HEAD":
                    continue
                return None
        return None

    def check(self, rec):
        code = self.probe(rec["url"])
        fields = {"last_checked": now_iso(), "http": code}
        if code is not None and code < 400:
            fields.update(status="live", fails=0)
        elif code in DEAD_CODES:
            fields.update(status="dead", fails=(rec.get("fails") or 0) + 1)
        else:
            fails = (rec.get("fails") or 0) + 1
            fields.update(fails=fails, status="dead" if fails >= 3 else (rec.get("status") if rec.get("status") == "live" else "unknown"))
        if fields.get("status") == "dead" and rec.get("status") != "dead":
            fields["died_at"] = now_iso()
        if fields.get("status") == "live":
            fields["died_at"] = None
        self.store.link_set(rec["url"], **fields)
        return fields["status"]

    # -- archive ---------------------------------------------------------------

    def archive(self, rec):
        for b in self.backends:
            try:
                found = b.lookup(rec["url"])
                if found and found[1] and (datetime.date.today() - datetime.date.fromisoformat(found[1][:10])).days <= 365:
                    self.store.link_set(rec["url"], archive_url=found[0], archived_at=found[1], backend=b.name)
                    return found[0]
                saved = b.save(rec["url"])
                if saved:
                    self.store.link_set(rec["url"], archive_url=saved[0], archived_at=saved[1], backend=b.name)
                    return saved[0]
                if found:  # older than a year but better than nothing
                    self.store.link_set(rec["url"], archive_url=found[0], archived_at=found[1], backend=b.name)
                    return found[0]
            except Exception as exc:  # one backend failing must not stop the others
                print("links: %s %s: %s" % (b.name, rec["url"][:80], str(exc)[:80]), flush=True)
        return None

    def private_copy(self, rec):
        """Fill private_url: the cold snapshot if there is one, else Hister's
        copy (a read-only lookup). With KANBAN_HISTER_SAVE a live link Hister lacks is also indexed when there's no
        snapshot or the snapshot is over a year old (the old snapshot stays the answer)."""
        url, fields = rec["url"], {"private_checked": now_iso()}
        cold = hist = None
        try:
            cold = self.cold.lookup(url) if self.cold else None
            if self.hister:
                hist = self.hister.lookup(url)
                stale = not cold or not cold[1] or (datetime.date.today() - datetime.date.fromisoformat(cold[1][:10])).days > 365
                if not hist and stale and rec.get("status") == "live" and self.hister_save:
                    hist = self.hister.save(url)
        except Exception as exc:
            print("links: private %s: %s" % (url[:80], str(exc)[:80]), flush=True)
        best, name = (cold, "cold") if cold else ((hist, "hister") if hist else (None, None))
        if best:
            fields.update(private_url=best[0], private_at=best[1], private_backend=name)
        self.store.link_set(url, **fields)
        return best[0] if best else None

    # -- the hourly worker -------------------------------------------------------

    def run_once(self):
        added = self.collect()
        due = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=CHECK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        checked = 0
        for rec in self.store.links("last_checked IS NULL OR last_checked < ?", (due,), BATCH_CHECK):
            self.check(rec)
            checked += 1
            time.sleep(1)
        saved = 0
        if self.enabled and self.backends:
            for rec in self.store.links("archive_url IS NULL AND status != 'unknown'", (), BATCH_SAVE):
                if self.archive(rec):
                    saved += 1
                time.sleep(3)
        if self.cold or self.hister:
            week = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=CHECK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for rec in self.store.links("private_url IS NULL AND status != 'unknown' AND "
                                        "(private_checked IS NULL OR private_checked < ?)", (week,), BATCH_PRIVATE):
                if self.private_copy(rec):
                    saved += 1
        self.last_run = now_iso()
        return added, checked, saved

    def worker(self, first_delay=60, every=3600):
        time.sleep(first_delay)
        while True:
            try:
                added, checked, saved = self.run_once()
                print("links: +%d new, %d checked, %d archived" % (added, checked, saved), flush=True)
            except Exception as exc:
                print("links: run failed: %s" % exc, flush=True)
            time.sleep(every)

    # -- for pages -------------------------------------------------------------

    def for_note(self, rel):
        return [r for r in self.store.links() if rel in (r.get("notes") or "").split("\n")]

    def own_urls(self, rel):
        """A note's external links, plus the addresses Hister stored them under
        after a redirect (taken from private_url), to leave out of "pages I've read"."""
        out = set()
        for r in self.for_note(rel):
            out.add(r["url"])
            p = r.get("private_url") or ""
            if r.get("private_backend") == "hister" and "/preview?id=" in p:
                out.add(urllib.parse.unquote(p.split("/preview?id=", 1)[1]))
        return out

    def dead_for_note(self, rel):
        return [r for r in self.for_note(rel) if r.get("status") == "dead"]

    def annotate(self, html, private=False):
        """Point dead links at their archived copy and mark them. private=True
        (the board's own pages) prefers the private copy; everything else
        only ever gets the public Wayback copy."""
        def swap(m):
            url = m.group(1)
            rec = self.store.link(url)
            if not rec or rec.get("status") != "dead":
                return m.group(0)
            if private and rec.get("private_url"):
                return '<a class="dead" title="dead link, private copy from %s" href="%s"' % (rec.get("private_at") or "?", rec["private_url"])
            if rec.get("archive_url"):
                return '<a class="dead" title="dead link, archived copy from %s" href="%s"' % (rec.get("archived_at") or "?", rec["archive_url"])
            return '<a class="dead" title="dead link, no archived copy" href="%s"' % url
        return re.sub(r'<a href="(https?://[^"]+)"', swap, html)

    def died_between(self, start, end):
        out = []
        for r in self.store.links("died_at IS NOT NULL", ()):
            try:
                d = datetime.date.fromisoformat((r.get("died_at") or "")[:10])
            except ValueError:
                continue
            if start <= d < end:
                out.append((d, r))
        return out

    def stats(self):
        rows = self.store.links()
        return {"total": len(rows), "live": sum(1 for r in rows if r["status"] == "live"),
                "dead": sum(1 for r in rows if r["status"] == "dead"),
                "archived": sum(1 for r in rows if r.get("archive_url")),
                "private": sum(1 for r in rows if r.get("private_url")), "last_run": self.last_run,
                "cold": (self.cold.error or "%d snapshots" % len(self.cold.urls)) if self.cold else "off",
                "hister": (self.hister.h.error or "ok") if self.hister else "off"}
