#!/usr/bin/env python3
"""konbini: project board built from vault frontmatter.

One listener, KANBAN_BIND:KANBAN_TAILNET_PORT (default 0.0.0.0:8081). KANBAN_AUTH picks who gets in:
- `tailscale` (the default): behind `tailscale serve` (HTTPS + identity headers), only requests whose
  Tailscale-User-Login is in KANBAN_TAILNET_USERS; serve strips client-supplied Tailscale-* headers, and
  requests from tagged nodes or without the header are refused. A header allow-list on a public bind can be
  spoofed, so a native install behind `tailscale serve` binds 127.0.0.1.
- `open`: no identity check at all, for localhost or a trusted LAN only; start-up
  prints a warning. It answers only when Host is an IP literal, localhost, KANBAN_BOARD_URL's host or a name in
  KANBAN_ALLOWED_HOSTS (DNS rebinding: another site's name pointed at this machine gets 403). The identity header is
  ignored (nothing vouches for it here) and writes are logged as `local`. The same-origin rule for form posts and the X-Agent handling stay as they are.

With MACHIYA_IDENTITY_FILE (Machiya's identity file, vaultkit.identity) the gate is the file instead: each request's
principal is resolved once (a token, a Tailscale login or tagged node, a trusted proxy's header with KANBAN_AUTH=header,
a session), and needs the konbini grant `read` to get in, `write` for any change, `areas` for new area/* lanes and new
tags (the owner's power that `agent == "web"` stood for). No proof or a bad one is 401, a missing grant 403. X-Agent
is a label then, and every event's actor is the principal's name.

Reads: the board, card pages, GET /api/cards. Writes edit the
note's frontmatter in the board's clone, log an event to .board/events,
and the writer thread commits them as the configured author (KANBAN_GIT_AUTHOR_NAME) and pushes in batches
(writer.py). The SQLite index is only a cache: `app.py rebuild` recreates
it from the clone. Writes from the web UI need a same-origin Referer or
Origin; API callers identify themselves with X-Agent and send no Origin or Referer (an API write with another
site's Origin or Referer, or with neither X-Agent nor a same-origin header, is refused: CSRF).
"""
import ipaddress
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

import datetime

# Native installs (machiya docs/install/bsd.md): settings may come from an env file, --env-file PATH or
# KANBAN_ENV_FILE (the real environment wins). Loaded before anything reads a setting: several modules below read
# theirs on import. A missing or bad file stops start-up, naming the file and line (never the line's text).
from vaultkit import envfile
try:
    ENV_FILE = envfile.load_for("kanban")
except (OSError, envfile.EnvFileError) as exc:
    sys.exit("konbini: env file: %s" % exc)

import deps  # noqa: E402
import goals
from vaultkit import shell
from vaultkit import identity
import vaultkit
import digest
import review
from blog import Blog
from kit import Kits
from hister import Hister
import links as links_mod
from links import ColdArchive, HisterBackend, Links, WaybackBackend
import modern
import common
from garden import Garden
from store import Store
from timeline import Timeline, today
from writer import WriteError, Writer

TAILNET_PORT = int(os.environ.get("KANBAN_TAILNET_PORT", "8081"))
TAILNET_USERS = set(filter(None, os.environ.get("KANBAN_TAILNET_USERS", "").split(",")))
def auth_mode(value, identity_file=""):
    """KANBAN_AUTH: "tailscale" (the default: Tailscale-User-Login must be in KANBAN_TAILNET_USERS, or in the identity
    file), "open" (no identity check, for localhost or a trusted LAN), or with an identity file "header" (a trusted
    proxy's login header, KANBAN_AUTH_HEADER). Anything else refuses to start rather than guess (as Niwa, Kura)."""
    value = (value or "tailscale").strip().lower()
    allowed = ("tailscale", "open", "header") if identity_file else ("tailscale", "open")
    if value not in allowed:
        raise SystemExit("konbini: KANBAN_AUTH must be %s, not %r" % (" or ".join(allowed), value))
    return value


AUTH = auth_mode(os.environ.get("KANBAN_AUTH"), os.environ.get("MACHIYA_IDENTITY_FILE", "").strip())
# The address the listener binds. A native install behind `tailscale serve` binds 127.0.0.1: on a public bind the
# Tailscale-User-Login header could be sent by anyone who reaches the port.
BIND = os.environ.get("KANBAN_BIND", "0.0.0.0").strip() or "0.0.0.0"
OPEN_ACTOR = "local"            # open mode: who every event names
# Machiya's identity file (MACHIYA_IDENTITY_FILE, vaultkit.identity): who is calling and what they may do here (the
# konbini grants read, write, areas). None without one: the KANBAN_TAILNET_USERS gate and `agent == "web"`, as before.
try:
    IDENTITY = identity.load_for("konbini", os.environ, bind=BIND,
                                 secure=not os.environ.get("KANBAN_BOARD_URL", "").strip().startswith("http://"))
except identity.IdentityError as err:
    raise SystemExit("konbini: identity: %s" % err)


def host_name(value):
    """A Host header's (or a setting's) name, lowercased, without the port and trailing dot; "" when it is not a
    plain host[:port] or [v6][:port]."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        if end < 0 or not re.fullmatch(r"(:\d*)?", value[end + 1:]):
            return ""
        return value[1:end]
    name, _, port = value.partition(":")
    if port and not port.isdigit():
        return ""
    return name.rstrip(".")


def host_allowed(host_header, allowed):
    """KANBAN_AUTH=open's guard against DNS rebinding: a page on another site whose name is pointed at this machine
    arrives with that site's name in Host (and Origin, so same_origin() can't tell), and could read and write the
    board. Only an IP literal, localhost, KANBAN_BOARD_URL's host or a KANBAN_ALLOWED_HOSTS name is served."""
    host = host_name(host_header)
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host in allowed


def allowed_hosts(board_url, extra):
    """The names KANBAN_AUTH=open answers to besides IP literals, normalised like a Host header."""
    names = {"localhost", host_name(urlsplit(board_url or "").netloc)}
    names |= {host_name(h) for h in (extra or "").split(",")}
    return names - {""}
REPO = os.environ.get("KANBAN_REPO", "/repo")
# Machiya stack mode: the stack keeps one vault copy (a mirror). The board still writes,
# so it keeps its own clone but borrows the mirror's objects (git alternates), and may check out only what it reads.
# Empty = standalone, the clone as it is. The mirror must be mounted at the same absolute path here and on the host.
REPO_REFERENCE = os.environ.get("KANBAN_REPO_REFERENCE", "").strip()
REPO_SPARSE = [p.strip().strip("/") for p in os.environ.get("KANBAN_REPO_SPARSE", "").split(",") if p.strip()]
DB = os.environ.get("KANBAN_DB", "/data/kanban.sqlite3")
STREAM_SECONDS = 600
MAX_BODY = 1 << 20              # writes are small: a card's fields, a comment, an order of slugs
REQUEST_TIMEOUT = 30           # seconds a client may stall mid-request (or not read the answer) before its thread is freed
DRAIN_BODY = 16 << 20           # an oversized body is read and dropped up to this, so the client sees the 413
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
from version import VERSION     # Konbini's release version: /api/status and Settings -> About



store = Store(DB, REPO)
writer = Writer(store)
timeline = Timeline(store)
garden = Garden(store, timeline)
# Links to this board and its sister rooms: empty = that link or feature is off (a deploy sets them).
modern.BOARD_URL = os.environ.get("KANBAN_BOARD_URL", "").rstrip("/")
# Niwa, the garden, is its own service (machiya-kobo/niwa): /garden/* here redirects there.
modern.GARDEN_URL = os.environ.get("KANBAN_NIWA_URL", "").rstrip("/")
modern.KURA_URL = os.environ.get("KANBAN_KURA_URL", "").rstrip("/")
# The Obsidian vault's name for "Edit in Obsidian" links (obsidian://open?vault=<name>); empty = no such links.
modern.OBSIDIAN_VAULT = os.environ.get("KANBAN_OBSIDIAN_VAULT", "").strip()
modern.set_sisters()
ALLOWED_HOSTS = allowed_hosts(modern.BOARD_URL, os.environ.get("KANBAN_ALLOWED_HOSTS", ""))
blog = Blog(os.environ.get("KANBAN_BLOG", "/blog"), os.environ.get("KANBAN_BLOG_URL", ""),
            os.environ.get("KANBAN_BLOG_PERMALINK"))   # optional: a Jekyll blog
ARCHIVE, _warn = links_mod.archive_mode(os.environ.get("KANBAN_ARCHIVE"))
if _warn:
    print("startup: WARNING: " + _warn, flush=True)
backends = [WaybackBackend()] if ARCHIVE == "wayback" else []
# Hister (optional): private copies of links, vault search, pages I've read. Single-user and private.
hister = Hister(os.environ["KANBAN_HISTER_URL"], os.environ.get("KANBAN_HISTER_PUBLIC", "")) \
    if os.environ.get("KANBAN_HISTER_URL") else None
cold = ColdArchive(os.environ["KANBAN_COLD_MAP"]) if os.environ.get("KANBAN_COLD_MAP") else None
links = Links(store, garden, backends, enabled=ARCHIVE != "none", cold=cold,
              hister=HisterBackend(hister) if hister else None,
              hister_save=links_mod.setting_on(os.environ.get("KANBAN_HISTER_SAVE")))
kits = Kits(store, garden, timeline, blog, modern.BOARD_URL, links, hister, garden_url=modern.GARDEN_URL)
# The vault push into Hister and the note reader are Kura's (machiya-kobo/kura).


def reading_for(card):
    """Pages I've read about a card, from Hister (private), or ([], "")."""
    if not hister:
        return [], ""
    own = list(links.own_urls(card["path"])) + [card.get("repo") or ""]  # the note's own links
    return hister.reading(card["title"], card.get("topics") or [], exclude=own)


def V(ctx):
    """The board's pages."""
    return modern

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml"}


def dep_graph(cards):
    """Dependencies resolved with the vault index (vaultkit's wikilink rules), per request."""
    garden.index()
    return deps.build(cards, garden.resolve)


def cards_with_deps():
    cards = store.cards()
    graph = dep_graph(cards)
    return deps.decorate(cards, graph), graph


def cards_by_path():
    return {c["path"]: c for c in store.cards()}


def anchor_date(value):
    try:
        return datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return today()


def local_target(referer, keep_query=True):
    """The Referer's path (and query) when it stays on this site, else "". A path must start with one "/" not
    followed by another "/" or a "\\" (browsers read //host and /\\host as another site), and nothing in it may be a
    control character."""
    try:
        ref = urlsplit(referer or "")
    except ValueError:          # e.g. an unclosed [ in the host
        return ""
    target = ref.path + ("?" + ref.query if keep_query and ref.query else "")
    if not target.startswith("/") or target[1:2] in ("/", "\\") or any(ord(c) < 32 or ord(c) == 127 for c in target):
        return ""
    return target


def cookies(header):
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def make_handler(listener):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # no keep-alive, no chunked encoding
        server_version = "konbini/1"
        timeout = REQUEST_TIMEOUT      # a client that stops sending lets its thread go

        def log_message(self, fmt, *args):
            if urlsplit(self.path).path == "/healthz":      # the container health check polls it; keep it out of the log
                return
            sys.stderr.write("%s %s %s\n" % (listener, self.log_name(), fmt % args))

        def log_name(self):
            """Who is asking, for the log: the principal and how it was proven, or the login as before."""
            if getattr(self, "headers", None) is None:      # a request line too broken to have headers
                return "-"
            if IDENTITY is not None:
                who = self.who()
                return "%s(%s)" % (who.principal.name, who.principal.via) if who else "-"
            return OPEN_ACTOR if AUTH == "open" else self.headers.get("Tailscale-User-Login", "-")

        def who(self):
            """The identity file's answer for this request (vaultkit.identity Result), worked out once."""
            if getattr(self, "_who", None) is None:
                self._who = IDENTITY.resolve(self.headers, self.client_address[0] if self.client_address else "")
            return self._who

        def can(self, action):
            """The principal holds the konbini grant `action` (read, write, areas). Without an identity file everyone
            the gate admits may read and write; the owner's powers are then `agent == "web"` (see areas())."""
            if IDENTITY is None:
                return action != "areas" and self.allowed()
            who = self.who()
            return bool(who) and who.principal.can("konbini", action)

        def areas(self):
            """For writer's tag checks: whether this request may add area/* lanes and new tags (the areas grant), or
            None without an identity file (the writer then asks `agent == "web"`, as before)."""
            return self.can("areas") if IDENTITY is not None else None

        def allowed(self):
            if AUTH == "open" and not host_allowed(self.headers.get("Host"), ALLOWED_HOSTS):
                return False            # DNS rebinding, with or without an identity file
            if IDENTITY is not None:
                return self.can("read")
            if AUTH == "open":
                return True
            return self.headers.get("Tailscale-User-Login", "") in TAILNET_USERS

        def refuse(self):
            api = urlsplit(self.path).path.startswith("/api/")
            if AUTH == "open" and not host_allowed(self.headers.get("Host"), ALLOWED_HOSTS):
                status, text = 403, ("forbidden: KANBAN_AUTH=open serves localhost, IP addresses, KANBAN_BOARD_URL's "
                                     "host and KANBAN_ALLOWED_HOSTS, not %r" % self.headers.get("Host", ""))
            elif IDENTITY is not None:
                who = self.who()            # 401: no proof or a bad one; 403: nobody in the file, or no read grant
                status, text = (403, "not allowed in konbini") if who else (who.status, who.error)
            else:
                status, text = 403, "forbidden"
            if IDENTITY is not None and api:
                self.send_json(status, {"error": text}, headers=[("Cache-Control", "no-store")])
            elif IDENTITY is not None:
                self.send(status, text + "\n", "text/plain", headers=[("Cache-Control", "no-store")])
            else:
                self.send(status, text + "\n", "text/plain")

        def session_cookies(self):
            """Set-Cookie values for this response: a renewed session, or a bad one cleared (vaultkit.identity)."""
            return self._who.cookies if getattr(self, "_who", None) is not None else ()

        def to_niwa(self, path):
            """/garden/<rest> (the garden's old home here) -> Niwa."""
            url = urlsplit(self.path)
            rest = path[len("/garden"):] or "/"
            return modern.GARDEN_URL + rest + ("?" + url.query if url.query else "")

        def ctx(self):
            p = shell.prefs(self.headers.get("Cookie"))
            c = common.Ctx(p.theme, p.text, p.extra)
            c.status = footer_status()
            c.alert = board_alert()
            c.alert_links = [(os.path.splitext(os.path.basename(r))[0], modern.obsidian_url(r[:-3]))
                             for r in store.phone_conflicts[:5]] if modern.OBSIDIAN_VAULT else []
            return c

        def send(self, status, body, ctype="text/html", headers=()):
            if isinstance(body, str):
                data = body.encode("utf-8")
                ctype += "; charset=utf-8"
            else:
                data = body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in headers:
                self.send_header(k, v)
            for c in self.session_cookies():
                self.send_header("Set-Cookie", c)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def stream(self):
            """Server-sent events: one `rev` message whenever the board changes.

            HTTP/1.0 with no Content-Length, so the response simply streams
            until either side closes; tailscale serve flushes event streams
            immediately. Clients reconnect after STREAM_SECONDS."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            for c in self.session_cookies():
                self.send_header("Set-Cookie", c)
            self.end_headers()
            last, started, beat = None, time.time(), time.time()
            try:
                self.wfile.write(b"retry: 5000\n\n")
                while time.time() - started < STREAM_SECONDS:
                    rev = store.meta("rev")
                    if rev != last:
                        self.wfile.write(("data: %s\n\n" % rev).encode())
                        self.wfile.flush()
                        last = rev
                    elif time.time() - beat > 20:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        beat = time.time()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def send_json(self, status, obj, headers=()):
            self.send(status, json.dumps(obj, indent=1), "application/json", headers)

        def do_HEAD(self):
            self.do_GET()

        # -- writes ----------------------------------------------------

        def actor(self):
            # With an identity file: the principal's name ("local" in open mode). Without: open mode is always
            # "local" (nothing vouches for the header there), else the Tailscale login.
            if IDENTITY is not None:
                return self.who().principal.name
            return OPEN_ACTOR if AUTH == "open" else self.headers.get("Tailscale-User-Login", "")

        def agent(self):
            # a label for the history ("which session did this"); with an identity file never a permission
            return (self.headers.get("X-Agent") or "web")[:80]

        def body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise WriteError(400, "invalid Content-Length")
            if length < 0:
                raise WriteError(400, "invalid Content-Length")
            if length > MAX_BODY:
                left = min(length, DRAIN_BODY)      # unread data at close would reset the connection before the 413
                while left > 0:
                    chunk = self.rfile.read(min(left, 65536))
                    if not chunk:
                        break
                    left -= len(chunk)
                raise WriteError(413, "request body too large (%d bytes at most)" % MAX_BODY)
            raw = self.rfile.read(length) if length else b""
            if "json" in (self.headers.get("Content-Type") or ""):
                try:
                    data = json.loads(raw or b"{}")
                except ValueError:
                    raise WriteError(400, "invalid JSON")
                if not isinstance(data, dict):
                    raise WriteError(400, "the JSON body must be an object")
                return data
            form = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
            return {k: v[-1] for k, v in form.items()}

        def same_origin(self):
            host = self.headers.get("Host", "")
            ref = self.headers.get("Origin") or self.headers.get("Referer") or ""
            return bool(host) and urlsplit(ref).netloc == host

        def back(self, fallback="/"):
            target = local_target(self.headers.get("Referer")) or fallback
            self.send(302, "", "text/plain", headers=[("Location", target or "/")])

        def do_write(self):
            if not self.allowed():
                self.refuse()
                return
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == "/api/garden/suggest" or path == "/garden" or path.startswith("/garden/"):
                # The garden's writes and suggestions are Niwa's.
                target = modern.GARDEN_URL + "/api/suggest" if path == "/api/garden/suggest" else self.to_niwa(path)
                self.send(308, "", "text/plain", headers=[("Location", target)])
                return
            api = path.startswith("/api/")
            try:
                data = self.body()
                if not api and not self.same_origin():
                    raise WriteError(403, "cross-site form post refused")
                if api and not self.same_origin():
                    # Like machiya-mcp: a browser always names the page it posts from, so an Origin (or Referer) that
                    # isn't the board's own is another site's page riding the owner's login (CSRF). Agents and
                    # scripts send neither, and name themselves with X-Agent; a write that does neither is refused.
                    if self.headers.get("Origin") or self.headers.get("Referer"):
                        raise WriteError(403, "cross-site API write refused")
                    if not (self.headers.get("X-Agent") or "").strip():
                        raise WriteError(403, "an API write names its caller with X-Agent")
                if not self.can("write"):
                    raise WriteError(403, "not allowed: changing the board needs the konbini write grant")
                actor, agent, areas = self.actor(), self.agent(), self.areas()
                if api and agent == "web" and not self.same_origin():
                    agent = "api"
                if self.command == "PATCH" and path.startswith("/api/cards/"):
                    card = writer.update(path[len("/api/cards/"):], data, actor, agent,
                                         self.headers.get("If-Match"), areas=areas)
                    self.send_json(200, card)
                elif self.command == "POST" and path == "/api/cards":
                    self.send_json(201, writer.create(data, actor, agent, areas=areas))
                elif self.command == "POST" and re.match(r"^/api/cards/[^/]+/events$", path):
                    slug = path.split("/")[3]
                    if not store.card(slug):
                        raise WriteError(404, "not found")
                    text = str(data.get("body") or "").strip()
                    if not text:
                        raise WriteError(422, "body is required")
                    ev = writer.event(slug, str(data.get("type") or "comment")[:20], actor, agent, body=text[:2000])
                    writer.touch(slug, slug + " (note)")
                    self.send_json(201, ev)
                elif self.command in ("POST", "DELETE") and re.match(r"^/api/cards/[^/]+/claim$", path):
                    slug = path.split("/")[3]
                    if not store.card(slug):
                        raise WriteError(404, "not found")
                    try:
                        minutes = 0 if self.command == "DELETE" else int(data.get("minutes") or 15)
                    except (TypeError, ValueError):
                        raise WriteError(422, "minutes must be a whole number")
                    store.claim(slug, actor, agent, min(minutes, 240))
                    self.send_json(200, {"card": slug, "claimed_by": agent if minutes else None, "minutes": minutes})
                elif self.command == "POST" and path == "/api/order":
                    writer.order(list(data.get("slugs") or []), data.get("board"), actor, agent, areas=areas)
                    self.send_json(200, {"ok": True})
                # HTML forms (no JavaScript needed)
                elif self.command == "POST" and path == "/move":
                    writer.update(data.get("slug", ""), {"board": data.get("board")}, actor, agent, areas=areas)
                    self.back()
                elif self.command == "POST" and re.match(r"^/p/[^/]+/tags$", path):
                    slug = path.split("/")[2]
                    add = [t.strip().lstrip("#") for t in str(data.get("add") or "").replace(",", " ").split() if t.strip()]
                    remove = [t for t in [str(data.get("remove") or "").strip()] if t]
                    try:
                        writer.update(slug, {"tags_add": add, "tags_remove": remove,
                                             "confirm_new_tags": data.get("confirm") in ("1", "true", True)},
                                      actor, agent, areas=areas)
                    except WriteError as err:
                        if err.extra.get("code") == "unknown_tag":
                            self.send(302, "", "text/plain", headers=[("Location", "/p/%s?tagmsg=%s&pending=%s" % (
                                slug, quote("new tag: tick 'new tag' to create " + ", ".join(err.extra.get("tags") or add)), quote(" ".join(add))))])
                            return
                        raise
                    self.send(302, "", "text/plain", headers=[("Location", "/p/" + slug)])
                elif self.command == "POST" and path.startswith("/p/"):
                    slug = path[3:]
                    if data.get("comment", "").strip():
                        writer.event(slug, "comment", actor, agent, body=data["comment"].strip()[:2000])
                        writer.touch(slug, slug + " (note)")
                    fields = {k: data[k] for k in ("board", "status", "next", "blocked_by", "waiting", "priority", "post", "post_url", "dependsOn", "stream", "goal", "due")
                              if k in data}
                    if fields:
                        writer.update(slug, fields, actor, agent, areas=areas)
                    self.back("/p/" + slug)
                elif self.command == "POST" and path == "/share":
                    url = str(data.get("url") or "").strip()
                    text = str(data.get("text") or "").strip()
                    title = str(data.get("title") or "").strip() or url or text[:80]
                    summary = " ".join(x for x in (text, url) if x)[:300]
                    card = writer.create({"title": title[:120], "area": data.get("area") or "projects", "board": "backlog",
                                          "summary": summary}, actor, agent, areas=areas)
                    self.send(302, "", "text/plain", headers=[("Location", "/p/" + card["slug"])])
                elif self.command == "POST" and path == "/new":
                    fields = {k: data.get(k) for k in ("title", "area", "board", "summary")}
                    fields["confirm_new_tags"] = data.get("confirm_new_tags") in ("1", "true", True)   # the first-lane box
                    card = writer.create(fields, actor, agent, areas=areas)
                    self.send(302, "", "text/plain", headers=[("Location", "/p/" + card["slug"])])
                else:
                    raise WriteError(405, "no such write endpoint")
            except WriteError as e:
                close = [("Connection", "close")] if e.status == 413 else []
                if api:
                    self.send_json(e.status, dict(error=e.message, **e.extra), close)
                else:
                    ctx = self.ctx()
                    self.send(e.status, V(ctx).message(ctx, "Not saved", e.message), headers=close)

        do_POST = do_PATCH = do_DELETE = do_write

        def do_GET(self):
            if urlsplit(self.path).path == "/healthz":      # liveness only: no data, no identity check, any KANBAN_AUTH
                self.send(200, "ok\n", "text/plain", headers=[("Cache-Control", "no-store")])
                return
            if not self.allowed():
                self.refuse()
                return
            url = urlsplit(self.path)
            path, query = unquote(url.path), parse_qs(url.query)
            ctx = self.ctx()
            app_name = "kanban"
            if path == "/manifest.webmanifest":
                self.send(200, json.dumps(modern.manifest(app_name, ctx.theme), indent=1), "application/manifest+json",
                          headers=[("Cache-Control", "no-cache")])
                return
            if path == "/sw.js":
                self.send(200, modern.service_worker(app_name), "text/javascript", headers=[("Cache-Control", "no-cache")])
                return
            if path == "/offline":
                self.send(200, V(ctx).offline(ctx, app_name))
                return
            if path.startswith("/static/icons/"):
                name = path.rsplit("/", 1)[1]
                if name.startswith("konbini"):      # the shell names icons after the room; the files are kanban-*
                    name = "kanban" + name[len("konbini"):]
                if name in modern.ICONS:
                    ctype = "image/svg+xml" if name.endswith(".svg") else "image/png"
                    with open(os.path.join(modern.ICON_DIR, name), "rb") as f:
                        self.send(200, f.read(), ctype, headers=[("Cache-Control", "public, max-age=604800")])
                else:
                    self.send(404, "not found\n", "text/plain")
                return
            if (path == "/garden" or path.startswith("/garden/")) and modern.GARDEN_URL:
                self.send(302, "", "text/plain", headers=[("Location", self.to_niwa(path))])
                return
            if path == "/now":
                self.send(200, V(ctx).now(ctx, cards_with_deps()[0], store.claims(), store.meta("rev")))
                return
            if path == "/search":
                ctx.q = (query.get("q") or [""])[0][:200]
                self.send(200, V(ctx).search_page(ctx, cards_with_deps()[0], ctx.q, store.claims()))
                return
            if path == "/goals":
                cards = cards_with_deps()[0]
                self.send(200, V(ctx).goals_page(ctx, cards, goals.build(cards), goals.due_soon(cards)))
                return
            if path == "/timeline":
                cards = cards_with_deps()[0]
                group = "stream" if (query.get("by") or [""])[0] == "stream" else "area"
                try:
                    months = min(max(int((query.get("months") or ["7"])[0]), 1), 24)
                except ValueError:
                    months = 7
                try:
                    start = datetime.date.fromisoformat((query.get("from") or [""])[0] + "-01")
                except ValueError:
                    first = datetime.date.today().replace(day=1)
                    start = (first - datetime.timedelta(days=4 * 30)).replace(day=1)   # four months back, three ahead
                end = start
                for _ in range(months):
                    end = (end + datetime.timedelta(days=32)).replace(day=1)
                self.send(200, V(ctx).timeline_page(ctx, cards, timeline.range(start, end, cards, group), start, end, group))
                return
            if path in ("/plan", "/streams"):          # Plan opens on Streams
                self.send(200, V(ctx).streams_page(ctx, cards_with_deps()[0]))
                return
            if path.startswith("/streams/"):
                html = V(ctx).stream_page(ctx, unquote(path[len("/streams/"):]), cards_with_deps()[0], store.claims(),
                                          store.meta("rev"))
                self.send(200 if html else 404, html or V(ctx).message(ctx, "Not found", "No stream " + path[9:]))
                return
            if path == "/deps":
                cards, graph = cards_with_deps()
                self.send(200, V(ctx).deps_page(ctx, cards, graph, deps.mermaid(cards, graph)))
                return
            if path == "/api/review":
                data = review.build(cards_with_deps()[0], lambda slug: store.events(card=slug, limit=200),
                                    store.last_activity())
                self.send_json(200, review.as_json(data))
                return
            if path == "/review":
                cards = cards_with_deps()[0]
                data = review.build(cards, lambda slug: store.events(card=slug, limit=200), store.last_activity())
                self.send(200, V(ctx).review(ctx, cards, data, store.claims(), store.meta("rev")))
                return
            if path == "/":
                html = V(ctx).board(ctx, cards_with_deps()[0], (query.get("lane") or [None])[0],
                                    store.meta("imported"), store.claims(), store.meta("rev"),
                                    query=query, activity=store.last_activity(), areas=known_areas())
                self.send(200, html)
            elif path == "/archived":
                self.send(200, V(ctx).archived(ctx, store.cards(), store.last_activity()))
            elif path == "/share":
                lanes = sorted({c["area"] for c in store.cards() if c["board"]} | {"projects"})
                self.send(200, V(ctx).share(ctx, store.cards(), (query.get("title") or [""])[0], (query.get("url") or [""])[0],
                                           (query.get("text") or [""])[0], lanes))
            elif path == "/posts":
                self.send(200, V(ctx).posts(ctx, kits.posts(), store.cards(), (query.get("show") or ["ready"])[0]))
            elif re.match(r"^/p/[^/]+/kit(\.md)?$", path):
                slug = path.split("/")[2]
                card = store.card(slug)
                if not card:
                    self.send(404, V(ctx).message(ctx, "Not found", "No card " + slug))
                else:
                    k = kits.build(card)
                    md = kits.markdown(k)
                    if path.endswith(".md"):
                        self.send(200, md, "text/markdown")
                    else:
                        self.send(200, V(ctx).kit_page(ctx, card, k, kits.html(md), store.cards()))
            elif path.startswith("/p/"):
                card = store.card(path[3:])
                if card:
                    cards, graph = cards_with_deps()
                    card = next((c for c in cards if c["slug"] == card["slug"]), card)
                    # The note itself is read in Kura (the card page links there).
                    reading = ""
                    if hister:  # private
                        docs, q = reading_for(card)
                        reading = modern.reading_section(docs, q, hister.search_url(q) if q else "")
                    self.send(200, V(ctx).detail(ctx, card, cards, store.events(card=card["slug"], limit=60),
                                                store.claims().get(card["slug"]),
                                                (query.get("tagmsg") or [""])[0], (query.get("pending") or [""])[0],
                                                reading, graph.get(card["slug"])))
                else:
                    self.send(404, V(ctx).message(ctx, "Not found", "No card " + path[3:]))
            elif path == "/calendar":
                month = (query.get("month") or [""])[0]
                anchor = anchor_date(month + "-01" if len(month) == 7 else month)
                self.send(200, V(ctx).calendar(ctx, timeline.month(anchor), store.cards()))
            elif path in ("/roundup", "/roundup.md", "/api/roundup"):
                period = (query.get("period") or ["week"])[0]
                r = timeline.roundup(period, anchor_date((query.get("date") or [""])[0]))
                if path == "/roundup.md":
                    self.send(200, timeline.markdown(r), "text/plain")
                elif path == "/api/roundup":
                    self.send_json(200, {
                        "period": r["kind"], "start": r["start"].isoformat(), "end": r["end"].isoformat(),
                        "label": r["label"], "markdown": timeline.markdown(r),
                        "items": [i.as_dict() for i in timeline.items(r["start"], r["end"])]})
                else:
                    self.send(200, V(ctx).roundup(ctx, r, store.cards()))
            elif path == "/theme":
                # the no-JavaScript fallback; /settings is the real control (machiya.js sets the cookie)
                theme = (query.get("set") or ["system"])[0]
                theme = "system" if theme == "auto" or theme not in ("night", "day", "system") else theme
                # 302 back to the page the toggle was on, if it is on this site.
                self.send(302, "", "text/plain", headers=[
                    ("Location", local_target(self.headers.get("Referer"), keep_query=False) or "/"), ("Set-Cookie", "theme=%s; path=/; max-age=31536000" % theme)])
            elif path in ("/static/machiya.css", "/static/machiya.js", "/static/machiya-sw.js"):
                name = path.rsplit("/", 1)[1]      # the shared UI, vendored with vaultkit (app/vaultkit/ui/)
                # shell.ui_url versions them (?v=<content hash>), so a versioned URL caches for good
                cache = "public, max-age=31536000, immutable" if query.get("v") else "max-age=300"
                with open(os.path.join(APP_DIR, "vaultkit", "ui", name), "rb") as f:
                    self.send(200, f.read(), "text/css" if name.endswith(".css") else "text/javascript",
                              headers=[("Cache-Control", cache)])
            elif path == "/settings":
                self.send(200, V(ctx).settings(ctx, store.cards(), VERSION, "v" + vaultkit.__version__,
                                               footer_status()["text"]))
            elif path in ("/static/board.css", "/static/board.js", "/static/Sortable.min.js", "/static/mermaid.min.js"):
                name = path.rsplit("/", 1)[1]
                ctype = "text/css" if name.endswith(".css") else "text/javascript"
                # Versioned URLs (?v=<hash>, see modern.static_url) never change, so they cache for a year.
                cache = "public, max-age=31536000, immutable" if query.get("v") else "max-age=300"
                with open(os.path.join(STATIC, name), "rb") as f:
                    self.send(200, f.read(), ctype, headers=[("Cache-Control", cache)])
            elif path == "/api/cards":
                cards = store.cards()
                for key in ("board", "area", "machine", "topic"):
                    want = (query.get(key) or [None])[0]
                    if want:
                        field = {"machine": "machines", "topic": "topics"}.get(key, key)
                        cards = [c for c in cards if (want in c[field] if isinstance(c[field], list) else c[field] == want)]
                tag = (query.get("tag") or [None])[0]
                if tag:
                    cards = [c for c in cards if tag in c["tags"]]
                self.send_json(200, {"cards": cards, "imported": store.meta("imported"), "head": store.meta("head")})
            elif re.match(r"^/api/cards/[^/]+/kit$", path):
                card = store.card(path.split("/")[3])
                if card:
                    k = kits.build(card)
                    k["markdown"] = kits.markdown(k)
                    self.send_json(200, k)
                else:
                    self.send_json(404, {"error": "not found"})
            elif re.match(r"^/api/cards/[^/]+/events$", path):
                self.send_json(200, {"events": store.events(card=path.split("/")[3], limit=200)})
            elif path.startswith("/api/cards/"):
                card = store.card(path[len("/api/cards/"):])
                if card:
                    card = dict(card, claim=store.claims().get(card["slug"]))
                self.send_json(200 if card else 404, card or {"error": "not found"})
            elif path == "/api/events":
                q = lambda k: (query.get(k) or [None])[0]
                self.send_json(200, {"events": store.events(since=q("since"), until=q("until"),
                                                            limit=int(q("limit") or 200))})
            elif path == "/api/links":
                status = (query.get("status") or [""])[0]
                rows = store.links("status = ?", (status,)) if status else store.links()
                self.send_json(200, {"links": rows, "stats": links.stats()})
            elif path == "/api/rev":
                self.send_json(200, {"rev": store.meta("rev")})
            elif path == "/api/stream":
                self.stream()
            elif path == "/api/digest":
                # The board half of the stream: Niwa renders the stream and adds the garden half.
                try:
                    days = max(1, min(90, int((query.get("days") or ["30"])[0])))
                except ValueError:
                    days = 30
                start, end = digest.window(days)
                now, entries = digest.board_part(store, timeline, start, end, {})
                self.send(200, json.dumps({"start": start + datetime.timedelta(days=1), "end": end, "days": days,
                                           "now": now, "entries": entries, "head": store.meta("head")},
                                          indent=1, default=str, ensure_ascii=False), "application/json")
            elif path in ("/api/health", "/api/status"):      # /api/status: the probe path every room answers
                self.send_json(200, {"ok": True, "version": VERSION, "imported": store.meta("imported"), "head": store.meta("head"),
                                     "cards": len(store.cards()), "sync": writer.status(),
                                     "hister": hister.status() if hister else "off",
                                     "livesync": {"status": livesync_status(), "problems": livesync_problems(),
                                                  "phone_conflicts": store.phone_conflicts},
                                     "auth": AUTH, "legacy_names": store.legacy})
            else:
                self.send(404, V(ctx).message(ctx, "Not found", path))

    return Handler


LIVESYNC_STATUS = os.environ.get("KANBAN_LIVESYNC_STATUS", "")
_livesync = {"at": 0.0, "data": None}


def livesync_status():
    """The Obsidian LiveSync bridge's status.json (optional; KANBAN_LIVESYNC_STATUS, mounted read-only),
    re-read at most every 10 s; None when there's no bridge (or no file yet)."""
    if not LIVESYNC_STATUS:
        return None
    now = time.time()
    if now - _livesync["at"] > 10:
        _livesync["at"] = now
        try:
            with open(LIVESYNC_STATUS, encoding="utf-8") as f:
                _livesync["data"] = json.load(f)
        except (OSError, ValueError):
            _livesync["data"] = None
    return _livesync["data"]


def livesync_problems():
    s = livesync_status()
    if not s:
        return []
    out = []
    if s.get("daemon") != "running":
        out.append("livesync daemon %s" % (s.get("daemon") or "unknown"))
    if time.time() - (s.get("last_cycle_ts") or 0) > 300:
        out.append("livesync bridge stalled (last cycle %s)" % (s.get("last_cycle") or "never"))
    git_ts = s.get("git_ok_ts") or 0  # missing/0: an older bridge, or its first minute
    if s.get("daemon") == "running" and git_ts and time.time() - git_ts > 1800:
        out.append("LiveSync bridge can't sync with its git remote since %s: phone edits are piling up"
                   % (s.get("git_ok_at") or "?"))
    if s.get("held_deletes"):
        out.append("livesync holding %d phone deletes (release them in the bridge to apply)"
                   % len(s["held_deletes"]))
    if s.get("unresolved"):
        out.append("livesync: %d unresolved conflict%s (%s)" % (
            len(s["unresolved"]), "" if len(s["unresolved"]) == 1 else "s", ", ".join(s["unresolved"][:3])))
    return out


def footer_status():
    """The shell footer's line: the vault commit the board has and how long ago it was imported."""
    head, imported = store.meta("head")[:7], store.meta("imported")
    try:
        mins = int((datetime.datetime.now() - datetime.datetime.fromisoformat(imported)).total_seconds() // 60)
    except ValueError:
        return {"text": "not imported yet", "state": "stale"}
    ago = "just now" if mins < 1 else ("%d min ago" % mins if mins < 120 else "%d h ago" % (mins // 60))
    return {"text": "synced %s %s · %d cards" % (head, ago, len(store.cards())),
            "state": "ok" if mins < 30 else "stale"}


def known_areas():
    """The vault's area/* names (every note's tags), sorted: the New-card form's choices."""
    return sorted(t[5:] for t in store.known_tags() if t.startswith("area/") and len(t) > 5)


def board_alert():
    """One line for the board header when a note is broken, sync is stuck, the phone
    bridge needs a look, or phone conflict copies are waiting to be merged."""
    parts = ["%s: %s" % (rel, why) for rel, why in store.broken[:3]]
    if len(store.broken) > 3:
        parts.append("%d more" % (len(store.broken) - 3))
    if writer.error:
        parts.append("sync: " + writer.error)
    parts += livesync_problems()
    n = len(store.phone_conflicts)
    if n:
        parts.append("%d phone conflict cop%s to merge: %s" % (n, "y" if n == 1 else "ies", ", ".join(
            os.path.splitext(os.path.basename(r))[0] for r in store.phone_conflicts[:3]) + (", …" if n > 3 else "")))
    return "; ".join(parts)


def share_objects():
    """Borrow the Machiya vault mirror's objects (vaultkit.git.borrow: alternates + repack, idempotent) and set the
    sparse cone. Everything the board reads or writes is under the notes folder and .board/ (plus the root .gitattributes,
    which cone mode always includes); git log reads history, which is in the objects either way. A missing mirror
    is logged and the board carries on standalone."""
    if not REPO_REFERENCE and not REPO_SPARSE:
        return
    from vaultkit.git import Git, borrow
    t = time.time()
    try:
        if REPO_REFERENCE:
            had = borrow(REPO, REPO_REFERENCE, REPO_SPARSE)
            print("startup: objects %s %s (%.0fs)" % ("borrowed from" if had else "now borrowed from",
                                                      REPO_REFERENCE, time.time() - t), flush=True)
        else:
            git = Git(REPO)
            on = git.run("config", "--get", "--default", "false", "core.sparseCheckout").strip() == "true"
            if not on or sorted(git.run("sparse-checkout", "list").split()) != sorted(REPO_SPARSE):
                git.run("sparse-checkout", "set", "--cone", *REPO_SPARSE, timeout=1800)
        if REPO_SPARSE:
            print("startup: sparse checkout %s" % ", ".join(REPO_SPARSE), flush=True)
    except Exception as exc:  # the board works without the mirror; say so and go on
        print("startup: can't share objects with %s: %s" % (REPO_REFERENCE or "(none)", exc), flush=True)


def auth_banner():
    """Start-up lines about where the settings came from and who can get in (KANBAN_AUTH, KANBAN_BIND)."""
    where = "%s:%d" % (BIND, TAILNET_PORT)
    lines = ["startup: settings from %s" % ENV_FILE] if ENV_FILE else []
    if IDENTITY is not None:
        config, _ = IDENTITY.current()
        lines.append("startup: identity file %s (%d principal%s), KANBAN_AUTH=%s on %s; KANBAN_TAILNET_USERS is not "
                     "used" % (IDENTITY.path, len(config.principals), "" if len(config.principals) == 1 else "s",
                               AUTH, where))
        if AUTH == "open":
            lines.append("startup: WARNING: KANBAN_AUTH=open: a request without a token is the owner. Use it only on "
                         "localhost or a trusted LAN; it answers to IP addresses and %s"
                         % ", ".join(sorted(ALLOWED_HOSTS)))
        return lines
    if AUTH == "open":
        return lines + ["startup: WARNING: KANBAN_AUTH=open: no identity check. Anyone who can reach %s can read and "
                        "change the board. Use it only on localhost or a trusted LAN." % where,
                        "startup: KANBAN_AUTH=open answers to IP addresses and %s (KANBAN_ALLOWED_HOSTS adds names)"
                        % ", ".join(sorted(ALLOWED_HOSTS))]
    lines.append("startup: KANBAN_AUTH=tailscale on %s: only Tailscale-User-Login in KANBAN_TAILNET_USERS (%d user%s)"
                 % (where, len(TAILNET_USERS), "" if len(TAILNET_USERS) == 1 else "s"))
    if not TAILNET_USERS:
        lines.append("startup: WARNING: KANBAN_TAILNET_USERS is empty, so every request is refused")
    return lines


def serve(port, listener):
    ThreadingHTTPServer((BIND, port), make_handler(listener)).serve_forever()


if __name__ == "__main__":
    if "rebuild" in sys.argv[1:]:
        print("rebuilt: %d cards" % store.rebuild())
        sys.exit(0)
    for line in auth_banner():
        print(line, flush=True)
    share_objects()
    print("startup: %d cards indexed" % store.rebuild(), flush=True)
    threading.Thread(target=writer.worker, daemon=True).start()
    threading.Thread(target=links.worker, daemon=True).start()
    threading.Thread(target=kits.warm, daemon=True).start()
    serve(TAILNET_PORT, "tailnet")
