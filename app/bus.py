"""Agents working right now: the Agent Workshop bus's presence, read for the Now page (stage 3) and GET /api/now.

Off unless KANBAN_BUS_URL is set (nats://host:4222). Konbini then reads the bus as a read-only observer identity
(KANBAN_BUS_IDENTITY, default `konbini`, its NKey seed in KANBAN_BUS_NKEY_FILE): one DIRECT.GET on the KV_presence
stream for the latest value of every `$KV.presence.<agent>` key, its replies on `_INBOX.<identity>.>`. It publishes
nothing else and makes no stream or consumer.

A background thread reads every POLL seconds with bounded timeouts and keeps the last good snapshot. Pages and the API
only ever read that snapshot, so a bus that is slow, down or refusing never holds up a request: after STALE seconds
without a good read the strip says it can't reach the bus, and /api/now answers `live: []`.

A presence value is untrusted JSON. Only these fields are read, each checked: `state`, `since` (epoch seconds), `note`,
`card` (a board slug) and `card_from`. Only `working` and `waiting_owner` are live; anything else, and an old client's
`{status, at}`, is not. `card` is absent when the agent has none. Every other field is never copied, in particular
`session_url`: the owner's rule keeps live session links in Techo only, so it is never stored, logged, rendered or
returned here.

KANBAN_BUS_AGENTS_FILE (optional) names the workshop's agents.yaml: then only its identities with a session (role
`agent` or `lead`) are listed, re-read when the file changes. Without it, or while it can't be read, any valid name is
(the bus already lets only `<agent>` write `$KV.presence.<agent>`).
"""
import asyncio
import datetime
import json
import os
import re
import sys
import threading
import time

LIVE = ("working", "waiting_owner")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")              # a workshop identity
CARD_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")          # a board slug
CARD_FROM = ("focus", "default")
NOTE_MAX = 80
NOTE_DROP = re.compile(r"[^\w .,:;()'&+#-]")                  # no slash, quote or markup: never a path or a link
PREFIX = "$KV.presence."
STREAM = "KV_presence"
MAX_AGENTS = 256
SESSION_ROLES = ("agent", "lead")                            # agents.yaml roles that run sessions
POLL = 5            # seconds between reads
STALE = 20          # a snapshot older than this is no longer shown
TIMEOUT = 3         # seconds for the connection and for each reply


def note_line(text):
    """A note as one short, plain line (or "")."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[\x00-\x1f\x7f-\x9f  ]+", " ", text)
    text = re.sub(r"\s+", " ", NOTE_DROP.sub("", text)).strip()
    return text if len(text) <= NOTE_MAX else text[:NOTE_MAX - 1].rstrip() + "…"


def parse(subject, data):
    """One KV value as `{agent, state, since, note, card}` when that agent is live, else None."""
    if not isinstance(subject, str) or not subject.startswith(PREFIX):
        return None
    agent = subject[len(PREFIX):]
    if not NAME_RE.match(agent) or not data:
        return None
    try:
        v = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(v, dict) or v.get("state") not in LIVE:
        return None
    since = v.get("since")
    try:
        since = float(since) if not isinstance(since, bool) else None
    except (TypeError, ValueError):
        since = None
    if since is not None and not 1_500_000_000 < since < 4_000_000_000:
        since = None
    card = v.get("card")
    card = card if isinstance(card, str) and CARD_RE.match(card) and v.get("card_from") in CARD_FROM else None
    return {"agent": agent, "state": v["state"],
            "since": datetime.datetime.fromtimestamp(since, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if since is not None else None,
            "note": note_line(v.get("note")), "card": card}


def session_names(text):
    """The identities in an agents.yaml that run sessions (role agent or lead)."""
    import yaml
    data = yaml.safe_load(text) or {}
    ids = data.get("identities") if isinstance(data, dict) else None
    if not isinstance(ids, dict):
        raise ValueError("no identities mapping")
    return {n for n, v in ids.items() if isinstance(n, str) and NAME_RE.match(n) and isinstance(v, dict)
            and v.get("role") in SESSION_ROLES}


def is_marker(headers):
    """A KV delete, purge or TTL-expiry marker, not a value."""
    h = headers or {}
    return h.get("KV-Operation") in ("DEL", "PURGE") or bool(h.get("Nats-Marker-Reason"))


def entries(rows, allowed=None):
    """The live agents in (subject, data, headers) rows, waiting on the owner first, then by name; only the names in
    `allowed` when it is a set."""
    out = {}
    for subject, data, headers in rows[:MAX_AGENTS]:
        if is_marker(headers):
            continue
        item = parse(subject, data)
        if item and (allowed is None or item["agent"] in allowed):
            out[item["agent"]] = item
    return sorted(out.values(), key=lambda i: (i["state"] != "waiting_owner", i["agent"]))


class Presence:
    """The bus reader. `fetch` returns the latest (subject, data, headers) of every presence key, or raises; without
    one it reads the bus over NATS (nats-py and nkeys, loaded only when the feature is on)."""

    def __init__(self, url="", identity="konbini", nkey_file="", fetch=None, poll=POLL, stale=STALE, timeout=TIMEOUT,
                 agents_file=""):
        self.url = (url or "").strip()
        self.identity = (identity or "konbini").strip()
        if self.url and not NAME_RE.match(self.identity):
            raise ValueError("KANBAN_BUS_IDENTITY must be a workshop name (a-z, 0-9 and -), not %r" % self.identity)
        self.nkey_file = (nkey_file or "").strip()
        self.agents_file = (agents_file or "").strip()
        self.agents = (None, None)  # (the file's mtime, its session names)
        self.fetch = fetch
        self.poll, self.stale, self.timeout = poll, stale, timeout
        self.lock = threading.Lock()
        self.good = None            # (monotonic time, [entry]) of the last good read
        self.problem = ""           # the last failure's kind, for the log: never a value, a seed or a message
        self.thread = None

    @classmethod
    def from_env(cls, env=os.environ):
        return cls(env.get("KANBAN_BUS_URL", ""), env.get("KANBAN_BUS_IDENTITY", "") or "konbini",
                   env.get("KANBAN_BUS_NKEY_FILE", ""), agents_file=env.get("KANBAN_BUS_AGENTS_FILE", ""))

    def allowed(self):
        """The agent names to list (KANBAN_BUS_AGENTS_FILE), or None for any: also while the file can't be read."""
        if not self.agents_file:
            return None
        try:
            mtime = os.stat(self.agents_file).st_mtime_ns
            if mtime != self.agents[0]:
                with open(self.agents_file, encoding="utf-8") as f:
                    self.agents = (mtime, session_names(f.read()))
        except Exception as err:                     # noqa: BLE001 - a missing or bad file: no filter, said once
            if self.agents != ("bad", None):
                print("bus: can't read KANBAN_BUS_AGENTS_FILE (%s); listing every agent" % type(err).__name__,
                      file=sys.stderr, flush=True)
            self.agents = ("bad", None)
        return self.agents[1]

    @property
    def enabled(self):
        return bool(self.url or self.fetch)

    def start(self):
        """Start the reader thread (once; nothing when the feature is off)."""
        with self.lock:
            if not self.enabled or self.thread:
                return
            self.thread = threading.Thread(target=self.run, name="bus-presence", daemon=True)
        self.thread.start()

    def run(self):
        if self.fetch:
            while True:
                self.read_once()
                time.sleep(self.poll)
        try:
            asyncio.run(self.nats_loop())
        except Exception as err:                     # noqa: BLE001 - the client is missing or broke: the strip says so
            self.failed(err)

    def read_once(self):
        try:
            rows = self.fetch()
        except Exception as err:                     # noqa: BLE001 - a down bus never breaks a page
            self.failed(err)
            return
        self.store(rows)

    def store(self, rows):
        items = entries(list(rows or []), self.allowed())
        with self.lock:
            self.good = (time.monotonic(), items)
            back = bool(self.problem)
            self.problem = ""
        if back:
            print("bus: presence readable again", file=sys.stderr, flush=True)

    def failed(self, err):
        kind = type(err).__name__
        with self.lock:
            same = self.problem == kind
            self.problem = kind
        if not same:
            print("bus: can't read presence (%s); the Now page shows the bus as unavailable" % kind,
                  file=sys.stderr, flush=True)

    def snapshot(self):
        """("off" | "ok" | "down", [entry]): what the page and the API show. Never waits on the bus."""
        if not self.enabled:
            return "off", []
        with self.lock:
            good = self.good
        if good is None or time.monotonic() - good[0] > self.stale:
            return "down", []
        return "ok", [dict(i) for i in good[1]]

    # --- the NATS side ------------------------------------------------------------------------------------------------
    async def nats_loop(self):
        import nats                                  # only with KANBAN_BUS_URL; ImportError ends up in failed()
        nc = None

        async def quiet(*_):                         # nats-py's default callbacks print tracebacks
            return None

        while True:
            try:
                if nc is None or not nc.is_connected:
                    if nc is not None:
                        await self.close(nc)
                    opts = dict(servers=[self.url], name="konbini-" + self.identity, inbox_prefix="_INBOX." + self.identity,
                                connect_timeout=self.timeout, allow_reconnect=False, error_cb=quiet,
                                disconnected_cb=quiet, closed_cb=quiet,
                                # nats-py's first connect retries for ever unless this is above 0: two tries, then
                                # NoServersError, and this loop tries again next round
                                max_reconnect_attempts=1, reconnect_time_wait=0.5)
                    if self.nkey_file:
                        opts["nkeys_seed"] = self.nkey_file
                    nc = None
                    nc = await asyncio.wait_for(nats.connect(**opts), self.timeout * 2)
                rows = await asyncio.wait_for(self.direct_get(nc), self.timeout * 2)
                self.store(rows)
            except Exception as err:                 # noqa: BLE001 - down, refused, timed out: try again next round
                self.failed(err)
                if nc is not None:
                    await self.close(nc)
                nc = None
            await asyncio.sleep(self.poll)

    async def close(self, nc):
        try:
            await asyncio.wait_for(nc.close(), self.timeout)
        except Exception:                            # noqa: BLE001
            pass

    async def direct_get(self, nc):
        """The latest value of every presence key: one batched DIRECT.GET (multi_last), read until the end marker."""
        inbox = nc.new_inbox()
        sub = await nc.subscribe(inbox)
        rows = []
        try:
            req = {"multi_last": [PREFIX + ">"], "batch": MAX_AGENTS}
            await nc.publish("$JS.API.DIRECT.GET." + STREAM, json.dumps(req).encode(), reply=inbox)
            while len(rows) < MAX_AGENTS:
                msg = await sub.next_msg(timeout=self.timeout)
                h = dict(msg.headers or {})
                status = h.get("Status")
                if status in ("204", "404"):         # the end of the batch, or no keys at all
                    break
                if status:
                    raise RuntimeError("direct get answered %s" % status)
                rows.append((h.get("Nats-Subject", ""), msg.data, h))
                if h.get("Nats-Num-Pending") == "0":
                    break
        finally:
            try:
                await sub.unsubscribe()
            except Exception:                        # noqa: BLE001
                pass
        return rows


def mark_known(items, slugs):
    """The contract's live items: `card_known` says whether the slug is a card on this board."""
    return [dict(i, card_known=bool(i["card"]) and i["card"] in slugs) for i in items]
