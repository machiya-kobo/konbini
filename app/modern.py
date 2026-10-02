"""The board's HTML5 pages: an HTML5 document, board.css through <link>, board.js as a module, a web app
manifest and a service worker so the board installs on a phone (Safari: Share > Add to Home Screen).
"""
import datetime
import hashlib
import json
import os
from urllib.parse import quote

from store import COLUMN_TITLES, slugify, sort_key
import goals as goalsmod
from vaultkit import shell
from common import (COLUMN_COLOR, KIND_MARK, PRIORITY_COLOR, SHOWN, collapse_history, e, event_line, facets, filter_cards,
                    lane_of, qget, stale_days)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ICON_DIR = os.path.join(STATIC_DIR, "icons")
ICONS = set(n for n in os.listdir(ICON_DIR) if n.endswith((".png", ".svg"))) if os.path.isdir(ICON_DIR) else set()
BOARD_URL = ""        # app.py sets KANBAN_BOARD_URL
GARDEN_URL = ""       # Niwa (machiya-kobo/niwa); app.py sets it from KANBAN_NIWA_URL; empty = no garden links
KURA_URL = ""         # Kura (machiya-kobo/kura); app.py sets it from KANBAN_KURA_URL; empty = no "View in Kura"
OBSIDIAN_VAULT = ""   # app.py sets it from KANBAN_OBSIDIAN_VAULT; empty = no "Edit in Obsidian"


def obsidian_url(note):
    """obsidian://open?vault=<KANBAN_OBSIDIAN_VAULT>&file=<note> ("" when no vault name is set)."""
    return ("obsidian://open?vault=%s&file=%s" % (quote(OBSIDIAN_VAULT, safe=""), quote(note, safe=""))) if OBSIDIAN_VAULT else ""
SHORT = {"backlog": "Backlog", "ready": "Ready", "wip": "WIP", "blocked": "Blocked", "done": "Done", "archived": "Archived"}


def _hash(name):
    try:
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:10]
    except OSError:
        return "0"


STATIC_V = {n: _hash(n) for n in ("board.css", "board.js", "Sortable.min.js")}
# The service worker's version (its cache names): the board's own static files plus vaultkit's shared UI
# (shell.UI_VERSION), so an installed Konbini picks up a new machiya.css/js too.
VERSION = hashlib.sha1("".join(sorted(STATIC_V.values()) + sorted(shell.UI_VERSION.values())).encode()).hexdigest()[:10]


def static_url(name):
    return "/static/%s?v=%s" % (name, STATIC_V.get(name, "0"))


# -- PWA: manifest, service worker ------------------------------------------

APPS = {
    "kanban": dict(name="Konbini", start="/now", desc="Konbini: the project board, built from the vault, open all hours"),
}


def shell_urls(app):
    """What the service worker precaches."""
    return [shell.ui_url("machiya.css"), shell.ui_url("machiya.js"), static_url("board.css"), static_url("board.js"),
            static_url("Sortable.min.js"),
            "/static/icons/%s.svg" % app, "/static/icons/%s-192.png" % app, "/offline"]


def manifest(app, theme):
    a = APPS[app]
    dark = theme != "day"
    return {k: v for k, v in {
        "name": a["name"], "short_name": a["name"], "description": a["desc"],
        "id": "/", "start_url": a["start"], "scope": "/", "display": "standalone",
        "background_color": "#1a1b26" if dark else "#e1e2e7",
        "theme_color": "#16161e" if dark else "#d0d5e3",
        "share_target": {"action": "/share", "method": "POST", "enctype": "application/x-www-form-urlencoded",
                         "params": {"title": "title", "text": "text", "url": "url"}} if app == "kanban" else None,
        "icons": [
            {"src": "/static/icons/%s-192.png" % app, "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/%s-512.png" % app, "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/%s-maskable-512.png" % app, "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }.items() if v is not None}


def service_worker(app):
    """/sw.js: the shared worker core (vaultkit v0.7, machiya-sw.js). Pages, card pages (/p/...) included, are
    network-first for 2.5 s and kept (the 120 most recent) for offline use; card pages aren't notes (Kura keeps
    those). The APIs are never touched, and search, settings and the capture form are never stored."""
    return shell.service_worker(VERSION, shell_urls(app), bypass=["^/api/"],
                                network=["^/search$", "^/settings$", "^/share$", "^/theme$"], pages=120)


# -- shell -------------------------------------------------------------------

_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>'
ICON = {
    "board": _SVG % '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="13" rx="1"/>',
    "now": _SVG % '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
    "calendar": _SVG % '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "roundup": _SVG % '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "garden": _SVG % '<path d="M12 22v-8M12 14c0-4 3-7 8-7-1 5-4 7-8 7zM12 14c0-4-3-7-8-7 1 5 4 7 8 7z"/>',
    "stream": _SVG % '<path d="M2 8c3-3 5 3 8 0s5 3 8 0 3-3 4 0M2 16c3-3 5 3 8 0s5 3 8 0 3-3 4 0"/>',
    "tags": _SVG % '<path d="M3 12V4h8l9 9-8 8-9-9z"/><circle cx="7" cy="8" r="1.5"/>',
    "queue": _SVG % '<path d="M3 13l2-8h14l2 8v6H3zM3 13h5l2 3h4l2-3h5"/>',
    "posts": _SVG % '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "review": _SVG % '<path d="M9 5h11M9 12h11M9 19h11M4 5l1 1 2-2M4 12l1 1 2-2M4 19l1 1 2-2"/>',
    "chain": _SVG % '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
}
# The rooms (Niwa, Kura, Shiori, ...) are in the shell's Rooms switcher (MACHIYA_ROOMS); the phone gets four tabs
# plus Rooms, which ends in Settings. Posts and Calendar are in the desktop nav and linked from Now.
# Plan holds Streams, Goals and Timeline behind one entry with a sub-nav; the old URLs stay.
KANBAN_NAV = [("/", "board", "Board"), ("/now", "now", "Now"), ("/review", "review", "Review"), ("/plan", "plan", "Plan"),
              ("/posts", "posts", "Posts"),
              ("/calendar", "calendar", "Calendar"), ("/roundup?period=week", "roundup", "Roundup")]
KANBAN_TABS = [("/", "board", "Board"), ("/now", "now", "Now"), ("/review", "review", "Review"),
               ("/roundup?period=week", "roundup", "Roundup")]


def set_sisters():
    """Kept for app.py's call: the sister rooms now come from MACHIYA_ROOMS (vaultkit.shell)."""
POST_STATES = ("none", "idea", "outlined", "drafting", "published", "skipped")


def tabbar(tabs, current):
    return '<nav class="tabbar" aria-label="Sections">%s</nav>' % "".join(
        '<a href="%s"%s>%s<span>%s</span></a>' % (e(href), ' class="here" aria-current="page"' if key == current else "",
                                                  ICON.get(key, ""), e(label))
        for href, key, label in tabs)


def page(ctx, app, title, body, tabs=(), current="", foot=()):
    """Every page: the Machiya shell (vaultkit.shell, room konbini: its icon, magenta) around the body, with the
    footer's status line; foot = extra [(href, label)] footer links for the page."""
    status = getattr(ctx, "status", None)
    head = ('<meta name="obsidian-vault" content="%s">\n' % e(OBSIDIAN_VAULT)) if OBSIDIAN_VAULT else ""
    return shell.page(ctx, "konbini", title, body + shell.footer("konbini", status, list(foot)), tabs, current,
                      head=head, stylesheets=[static_url("board.css")], scripts=[static_url("board.js")], icons=ICON)


def header(ctx, brand, brand_href, links, current, subtitle="", tools="", stats="", cls=""):
    """The shell's header (the room's icon, wordmark, nav, the Rooms switcher, the settings gear) with the board's stats row."""
    # the room's one search field (vaultkit v0.6): Konbini searches its cards (/search), then hands off to Shiori
    tools = shell.search_box(getattr(ctx, "q", ""), action="/search", placeholder="Search Cards") + tools
    top = shell.header("konbini", links, current, shell.rooms(), subtitle, tools)
    if cls:
        top = top.replace('<header class="top">', '<header class="top %s">' % e(cls), 1)
    return top.replace("</div></header>", "</div>%s</header>" % stats, 1) if stats else top


def counts_of(cards):
    counts = {}
    for c in cards:
        if c["board"]:
            counts[c["board"]] = counts.get(c["board"], 0) + 1
    return counts


def board_header(ctx, counts, subtitle="", current="board"):
    stats = '<div class="stats">%s</div>' % "".join(
        '<span class="stat col-%s">%s <b>%d</b></span>' % (col, e(SHORT[col]), counts.get(col, 0)) for col in SHOWN)
    if ctx.alert:
        links = "".join(' <a class="nlink" href="%s">open %s</a>' % (e(h), e(l)) for l, h in getattr(ctx, "alert_links", []))
        stats += '<p class="alert" role="alert">Needs a look: %s%s</p>' % (e(ctx.alert), links)
    return header(ctx, "konbini", "/", KANBAN_NAV, current, subtitle, "", stats)


def ago(value):
    try:
        d = datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return ""
    n = (datetime.date.today() - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 14:
        return "%dd ago" % n
    if n < 60:
        return "%dw ago" % (n // 7)
    if n < 365:
        return "%dmo ago" % (n // 30)
    return "%dy ago" % (n // 365)


# -- cards -------------------------------------------------------------------

def chips(card, show_area=False):
    out = []
    if card.get("priority"):
        out.append('<span class="chip p%d">P%d</span>' % (card["priority"], card["priority"]))
    if card.get("effort"):
        out.append('<span class="chip effort">effort %s</span>' % e(card["effort"].upper()))
    if show_area and card.get("area"):
        out.append('<span class="chip area">%s</span>' % e(card["area"]))
    if card.get("publish"):
        out.append('<span class="chip garden">garden</span>')
    return out


def claim_badge(claim):
    if not claim:
        return ""
    import time
    mins = max(1, int((claim["expires"] - time.time()) / 60))
    who = claim["agent"] if claim["agent"] not in ("web", "api") else claim["actor"]
    return '<span class="claim">%s %dm</span>' % (e(who), mins)


def move_form(card):
    opts = "".join('<option value="%s"%s>%s</option>' % (c, " selected" if c == card["board"] else "", e(SHORT[c]))
                   for c in SHOWN)
    return ('<form class="moveform" method="post" action="/move"><input type="hidden" name="slug" value="%s">'
            '<select name="board" onchange="this.form.submit()">%s</select>'
            '<noscript><button type="submit">Move</button></noscript></form>' % (e(card["slug"]), opts))


def card_html(ctx, card, claim=None, show_area=False, show_updated=False, why=()):
    note = card["path"][:-3] if card["path"].endswith(".md") else card["path"]
    lines = ['<a class="title" href="/p/%s">%s</a>' % (quote(card["slug"]), e(card["title"]))]
    text = card.get("summary") or ""
    if text:
        if len(text) > 180:
            text = text[:177].rstrip() + "..."
        lines.append('<p class="summary">%s</p>' % e(text))
    waits = card.get("_waiting_on") or []
    if card.get("board") == "blocked" and card.get("blocked_by"):
        lines.append('<p class="blocked">blocked: %s</p>' % e(card["blocked_by"]))
    elif waits:
        lines.append('<p class="blocked">waiting on: %s</p>' % e(", ".join(waits)))
    elif card.get("next"):
        nxt = card["next"] if len(card["next"]) <= 140 else card["next"][:137].rstrip() + "..."
        lines.append('<p class="next" title="click to edit">next: %s</p>' % e(nxt))
    meta = chips(card, show_area)
    if card.get("stream"):
        meta.insert(0, '<a class="chip stream" href="/streams/%s">%s</a>' % (quote(card["stream"], safe=""), e(card["stream"])))
    if card.get("goal"):
        meta.insert(1 if card.get("stream") else 0,
                    '<a class="chip goal" href="/goals#g-%s">%s</a>' % (slugify(card["goal"]), e(card["goal"])))
    state = goalsmod.due_state(card)
    if state:
        d = goalsmod.due_date(card)
        meta.append('<span class="chip due due-%s" title="due %s">%s %s</span>'
                    % (state, d.isoformat(), "overdue" if state == "overdue" else "due", e(d.strftime("%b %-d"))))
    if waits:
        meta.append('<span class="chip dep" title="waiting on %s">%s%d</span>' % (e(", ".join(waits)), ICON["chain"], len(waits)))
    if claim:
        meta.append(claim_badge(claim))
    if card.get("checks_total"):
        meta.append('<span class="checks">%d/%d</span>' % (card["checks_done"], card["checks_total"]))
    meta += ['<span class="topic">%s</span>' % e(t) for t in card.get("topics", [])[:3]]
    if card.get("_stale"):
        meta.append('<span class="chip stale" title="no board change or event for %d days">stale %dd</span>' % (card["_stale"], card["_stale"]))
    if show_updated and card.get("updated"):
        meta.append('<span class="when">%s</span>' % e(ago(card["updated"])))
    meta += ['<span class="chip why">%s</span>' % e(w) for w in why]
    if meta:
        lines.append('<div class="meta">%s</div>' % "".join(meta))
    return ('<article class="card is-card col-%s" id="c-%s" data-slug="%s" data-board="%s" data-title="%s" data-next="%s" '
            'data-note="%s" data-publish="%s">%s'
            '<button class="more" type="button" aria-label="Actions for %s">&#8943;</button>%s</article>'
            % (e(card["board"] or ""), e(card["slug"]), e(card["slug"]), e(card["board"] or ""), e(card["title"]),
               e(card.get("next") or ""), e(note), "1" if card.get("publish") else "0", "\n".join(lines),
               e(card["title"]), move_form(card)))


def lane_html(ctx, lane, cards, claims=None):
    by_col = {c: sorted((x for x in cards if x["board"] == c), key=sort_key) for c in SHOWN}
    by_col["done"].sort(key=lambda x: x.get("updated") or "", reverse=True)
    done_limit = setting(ctx, "doneCards")
    cols = []
    for col in SHOWN:
        items = by_col[col]
        shown = items[:int(done_limit)] if col == "done" and done_limit != "all" else items
        body = "\n".join(card_html(ctx, c, (claims or {}).get(c["slug"])) for c in shown) or '<div class="colempty"></div>'
        if len(shown) < len(items):
            body += ('<p class="colmore" data-more="%d">+%d more <a href="/settings">(Done Cards)</a></p>'
                     % (len(items) - len(shown), len(items) - len(shown)))
        cols.append('<div class="col col-%s" data-board="%s" data-col="%s"><h3 class="colhead col-%s">%s <span class="colcount">%d</span></h3>\n%s</div>'
                    % (col, col, e(SHORT[col]), col, e(SHORT[col]), len(items), body))
    n = sum(1 for c in cards if c["board"] in SHOWN)
    return ('<section class="lane" data-lane="%s"><h2 class="lanehead"><span class="lanename">%s</span>'
            '<span class="lanecount">%d</span></h2><div class="cols">%s</div></section>\n'
            % (e(lane), e(lane), n, "".join(cols)))


def new_form(areas):
    """The vault's area/* names as a select; a vault with none yet gets a text box for its first one (a new area/* tag
    is a maintainer's to create, so the form confirms it)."""
    if areas:
        field = '<select name="area">%s</select>' % "".join('<option value="%s">%s</option>' % (e(a), e(a)) for a in areas)
    else:
        field = ('<input type="text" name="area" maxlength="40" placeholder="first lane, e.g. tools" required> '
                 '<input type="hidden" name="confirm_new_tags" value="1">')
    return ('<form class="newform" method="post" action="/new"><label>New card '
            '<input type="text" name="title" maxlength="120" placeholder="title" required></label> '
            '<label>area %s</label> '
            '<button type="submit">Add to backlog</button></form>' % field)


def filter_bar(query, cards, claims):
    f = facets(cards, claims)

    def sel(name, opts, label=None):
        return '<select name="%s" aria-label="%s"><option value="">%s</option>%s</select>' % (
            name, label or name, label or name, "".join(
                '<option value="%s"%s>%s</option>' % (e(v), " selected" if qget(query, name) == v else "", e(v)) for v in opts))
    group = qget(query, "group")
    active = [(k, qget(query, k)) for k in ("area", "topic", "machine", "agent", "effort", "stream", "q") if qget(query, k)]
    chips = ""
    if active:
        def without(k):
            keep = [(a, b) for a, b in active if a != k] + ([("group", group)] if group else [])
            return "/?" + "&".join("%s=%s" % (a, quote(b)) for a, b in keep) if keep else "/"
        chips = '<p class="activefilters">%s <a class="clear" href="%s">clear all</a></p>' % ("".join(
            '<a class="fchip" href="%s">%s: %s &times;</a>' % (without(k), e(k), e(v)) for k, v in active), "/?group=family" if group else "/")
    # text search is the header's search field now (/search); a ?q= on the board still filters and shows as a chip
    return ('<form class="filterbar" method="get" action="/">%s'
            '%s%s%s%s%s%s<select name="group" aria-label="group by"><option value="">by area</option>'
            '<option value="family"%s>by family</option><option value="stream"%s>by stream</option></select>'
            '<button type="submit" class="quiet">Filter</button></form>%s'
            % (('<input type="hidden" name="q" value="%s">' % e(qget(query, "q"))) if qget(query, "q") else "", sel("area", f["area"]), sel("topic", f["topic"]), sel("machine", f["machine"]),
               sel("agent", ["any"] + f["agent"], "claimed"), sel("effort", f["effort"]),
               sel("stream", f["stream"]) if f["stream"] else "",
               " selected" if group == "family" else "", " selected" if group == "stream" else "", chips))


def board(ctx, cards, lane_filter=None, imported="", claims=None, rev="", query=None, activity=None, areas=()):
    query = dict(query or {})
    if "group" not in query and setting(ctx, "group") == "family":   # the Group By setting; ?group= wins
        query["group"] = ["family"]
    group = qget(query, "group")
    carded = [dict(c) for c in filter_cards([c for c in cards if c["board"]], query, claims)]
    for c in carded:
        c["area"] = lane_of(c, group)
        c["_stale"] = stale_days(c, activity)
    unsorted = sorted((c for c in cards if not c["board"]), key=lambda c: c["title"].lower())
    counts = counts_of(carded)
    lanes = sorted({c["area"] for c in carded if c["board"] in SHOWN})
    shown = [lane_filter] if lane_filter in lanes else lanes
    coltabs = '<div class="coltabs" role="tablist" aria-label="Columns">%s</div>' % "".join(
        '<button type="button" role="tab" data-col="%s" class="col-%s">%s<span class="n">%d</span></button>'
        % (col, col, e(SHORT[col]), counts.get(col, 0)) for col in SHOWN)
    parts = ['<button type="button" class="filterbtn quiet">Filters</button>', filter_bar(query, cards, claims),
             new_form(areas), coltabs]
    parts += [lane_html(ctx, lane, [c for c in carded if c["area"] == lane], claims) for lane in shown]
    if not shown:
        parts.append('<p class="none"><b>No Matching Cards</b> <a href="/">Clear the filters</a> to see the whole board.</p>')
    if unsorted and not lane_filter:
        parts.append('<p class="unsorted"><b>Unsorted</b> (type/project, no status:): %s</p>' % ", ".join(
            '<a href="/p/%s">%s</a>' % (quote(c["slug"]), e(c["title"])) for c in unsorted))
    archived_n = sum(1 for c in cards if c["board"] == "archived")
    parts.append('<p class="keys">Imported %s &middot; keys: j/k select, 1-5 move, / search, n new</p>' % e(imported))
    main = '<main id="board" class="board" data-rev="%s">\n%s\n</main>' % (e(rev), "\n".join(parts))
    return page(ctx, "kanban", "konbini", board_header(ctx, counts) + main, KANBAN_TABS, "board",
                foot=[("/archived", "Archived (%d)" % archived_n), ("/share", "Capture a Link"), ("/api/cards", "API")])


def now(ctx, cards, claims=None, rev=""):
    counts = counts_of(cards)
    claims = claims or {}
    sections = []
    for col, name, key in (("wip", "Working on", None), ("blocked", "Blocked", None)):
        items = sorted((c for c in cards if c["board"] == col), key=sort_key)
        sections.append((name, col, items))
    ready = sorted((c for c in cards if c["board"] == "ready"), key=lambda c: (c.get("priority") or 9, sort_key(c)))[:5]
    sections.append(("Up next", "ready", ready))
    parts = []
    for name, col, items in sections:
        body = "\n".join(card_html(ctx, c, claims.get(c["slug"]), show_area=True, show_updated=True) for c in items) \
            or '<p class="none"><b>Nothing Here</b></p>'
        parts.append('<section class="nowsec"><h2 class="colhead col-%s">%s <span class="colcount">%d</span></h2>'
                     '<div class="nowlist">%s</div></section>' % (col, e(name), len(items), body))
    parts.append('<p class="nowmore"><a href="/review">Weekly review</a> &middot; <a href="/plan">Plan</a> (<a href="/streams">streams</a>, '
                 '<a href="/goals">goals</a>, <a href="/timeline">timeline</a>) &middot; '
                 '<a href="/posts">Posts</a> &middot; '
                 '<a href="/calendar">Calendar</a> &middot; <a href="/roundup?period=week">Roundup</a></p>')
    main = '<main id="board" class="now" data-rev="%s">%s</main>' % (e(rev), "\n".join(parts))
    return page(ctx, "kanban", "now - konbini", board_header(ctx, counts, "", "now") + main, KANBAN_TABS, "now")


def deps_page(ctx, cards, graph, chart):
    """Every dependency: a Mermaid graph (dependency -> the card that waits for it) and the same as a list."""
    rows = []
    for c in sorted(cards, key=lambda c: c["title"].lower()):
        g = graph.get(c["slug"]) or {}
        if not g.get("waits_for") or c.get("board") == "archived":
            continue
        rows.append('<li><a class="ntl" href="/p/%s">%s</a> <span class="chip col-%s colchip">%s</span> waits for %s</li>'
                    % (quote(c["slug"]), e(c["title"]), e(c.get("board") or "none"), e(SHORT.get(c.get("board"), "Unsorted")),
                       dep_links(g["waits_for"])))
    body = ('<main class="posts deps"><p class="none">Set a card&rsquo;s dependencies on its page (Depends on). A card waits '
            'while any dependency isn&rsquo;t done, and counts as blocked.</p>%s%s</main>'
            % (('<pre><code class="language-mermaid">%s</code></pre>' % e(chart)) if chart else "",
               ('<ul class="garden-list plain deplist">%s</ul>' % "".join(rows)) if rows
               else '<p class="none"><b>No Dependencies</b> No card has a <code>dependsOn</code> yet.</p>'))
    return page(ctx, "kanban", "dependencies - konbini", board_header(ctx, counts_of(cards), "Dependencies", "") + body,
                KANBAN_TABS, "board")


def review(ctx, cards, data, claims=None, rev=""):
    """The weekly review (review.py): one section per question, each card once, the other reasons as chips."""
    claims = claims or {}
    jump = "".join('<a href="#r-%s">%s <b>%d</b></a>' % (key, e(title), len(rows))
                   for key, title, _, rows in data["sections"])
    limits = "".join('<span class="lim%s" title="%d in WIP, limit %d">%s %d/%d</span>'
                     % (" over" if n > lim else "", n, lim, e(area), n, lim) for area, n, lim in data["areas"])
    parts = ['<nav class="revjump" aria-label="Sections">%s<a href="/deps">Dependencies</a></nav>' % jump]
    if limits:
        parts.append('<p class="limits">WIP by area %s</p>' % limits)
    for key, title, hint, rows in data["sections"]:
        body = "\n".join(card_html(ctx, c, claims.get(c["slug"]), show_area=True, show_updated=True, why=why)
                         for c, why in rows) or '<p class="none"><b>All Clear</b></p>'
        parts.append('<section class="nowsec revsec" id="r-%s"><h2 class="colhead">%s <span class="colcount">%d</span></h2>'
                     '<p class="hint">%s</p><div class="nowlist">%s</div></section>' % (key, e(title), len(rows), e(hint), body))
    main = '<main id="board" class="now review" data-rev="%s">%s</main>' % (e(rev), "\n".join(parts))
    return page(ctx, "kanban", "review - konbini", board_header(ctx, counts_of(cards), "Weekly review", "review") + main,
                KANBAN_TABS, "review")


def stream_rollup(cards):
    """A stream's progress from its cards (archived left out): done/total, checklist items, cards per column,
    how many are blocked (the column, a waiting: reason or an unfinished dependency)."""
    live = [c for c in cards if c.get("board") and c["board"] != "archived"]
    cols = {col: sum(1 for c in live if c["board"] == col) for col in SHOWN}
    return {"total": len(live), "done": cols.get("done", 0), "cols": cols,
            "checks": (sum(c.get("checks_done") or 0 for c in live), sum(c.get("checks_total") or 0 for c in live)),
            "blocked": sum(1 for c in live if c["board"] == "blocked" or c.get("waiting") or c.get("_waiting_on"))}


def rollup_html(name, r, link=True):
    pct = round(100 * r["done"] / r["total"]) if r["total"] else 0
    title = ('<a href="/streams/%s">%s</a>' % (quote(name, safe=""), e(name))) if link else e(name)
    text = ["%d of %d done" % (r["done"], r["total"])]
    if r["checks"][1]:
        text.append("checklists %d/%d" % r["checks"])
    stats = ['<span class="stat col-%s">%s <b>%d</b></span>' % (col, e(SHORT[col]), r["cols"][col])
             for col in ("wip", "ready", "backlog") if r["cols"].get(col)]
    if r["blocked"]:
        stats.append('<span class="stat col-blocked">Blocked <b>%d</b></span>' % r["blocked"])
    parts = ["<span>%s</span>" % " &middot; ".join(text)] + stats     # the stats carry their own coloured dots
    return ('<div class="rollup"><h2 class="rollname">%s</h2><div class="bar" role="progressbar" aria-valuenow="%d" '
            'aria-valuemin="0" aria-valuemax="100" aria-label="%s done"><span style="width:%d%%"></span></div>'
            '<p class="rollmeta">%s</p></div>' % (title, pct, e(name), pct, "".join(parts)))


PLAN_TABS = [("/streams", "streams", "Streams"), ("/goals", "goals", "Goals"), ("/timeline", "timeline", "Timeline")]


def plan_nav(current):
    """The Plan sub-nav: Streams · Goals · Timeline."""
    return '<nav class="subnav" aria-label="Plan">%s</nav>' % "".join(
        ('<b class="here" aria-current="page">%s</b>' % e(label)) if key == current else '<a href="%s">%s</a>' % (href, e(label))
        for href, key, label in PLAN_TABS)


def streams_page(ctx, cards):
    """/streams: every workstream (cards' stream: field) with its progress, busiest first."""
    by = {}
    for c in cards:
        if c.get("board") and c.get("stream"):
            by.setdefault(c["stream"], []).append(c)
    rows = sorted(((name, stream_rollup(cs)) for name, cs in by.items()),
                  key=lambda t: (-(t[1]["total"] - t[1]["done"]), t[0].lower()))
    loose = sum(1 for c in cards if c.get("board") and c["board"] != "archived" and not c.get("stream"))
    body = "".join(rollup_html(n, r) for n, r in rows) or \
        '<p class="none"><b>No Streams Yet</b> Give a card a stream on its page, and cards with the same stream group here.</p>'
    body += ('<p class="none">%d card%s without a stream &middot; <a href="/?group=stream">the board by stream</a></p>'
             % (loose, "" if loose == 1 else "s")) if loose else ""
    return page(ctx, "kanban", "streams - konbini", board_header(ctx, counts_of(cards), "Streams", "plan") +
                '<main class="streams">%s%s</main>' % (plan_nav("streams"), body), KANBAN_TABS, "")


def stream_page(ctx, name, cards, claims=None, rev=""):
    """/streams/<name>: one stream's progress and its cards as a board (columns), like one lane of the board."""
    mine = [c for c in cards if c.get("board") and (c.get("stream") or "").lower() == name.lower()]
    if not mine:
        return None
    name = mine[0]["stream"]
    archived = sum(1 for c in mine if c["board"] == "archived")
    body = (rollup_html(name, stream_rollup(mine), link=False) + lane_html(ctx, name, mine, claims)
            + ('<p class="none">%d archived</p>' % archived if archived else "")
            + '<p class="nowmore"><a href="/streams">All streams</a> &middot; <a href="/?stream=%s">on the board</a></p>'
            % quote(name, safe=""))
    return page(ctx, "kanban", name + " - konbini", board_header(ctx, counts_of(cards), name, "plan") +
                # data-rev: board.js reloads a #board page whose revision differs from the server's
                '<main id="board" class="board stream" data-rev="%s">%s%s</main>' % (e(rev), plan_nav("streams"), body), KANBAN_TABS, "board")


def ago_or_in(value):
    try:
        d = datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    n = (d - datetime.date.today()).days
    return "today" if n == 0 else ("in %dd" % n if n > 0 else "%dd ago" % -n)


def goals_page(ctx, cards, goals, soon):
    """/goals: each goal (a card's goal: field) with its target (the latest due of its cards) and progress."""
    parts = []
    for g in goals:
        pct = round(100 * g["done"] / g["total"]) if g["total"] else 0
        target = ('<span class="chip due due-%s">target %s &middot; %s</span>'
                  % ("overdue" if g["state"] == "overdue" else "soon" if g["state"] == "soon" else "later",
                     g["target"].strftime("%b %-d, %Y"), e(ago_or_in(g["target"].isoformat())))) if g["target"] \
            else '<span class="chip">no due dates</span>'
        rows = "".join('<li><a class="ntl" href="/p/%s">%s</a> <span class="chip col-%s colchip">%s</span>%s</li>'
                       % (quote(c["slug"]), e(c["title"]), e(c["board"]), e(SHORT.get(c["board"], "")),
                          (' <span class="when">due %s</span>' % e(c["due"])) if c.get("due") else "") for c in g["cards"])
        parts.append('<section class="goal" id="g-%s"><h2 class="rollname">%s %s</h2><div class="bar" role="progressbar" '
                     'aria-valuenow="%d" aria-valuemin="0" aria-valuemax="100"><span style="width:%d%%"></span></div>'
                     '<p class="rollmeta"><span>%d of %d done</span></p><ul class="garden-list plain">%s</ul></section>'
                     % (slugify(g["name"]), e(g["name"]), target, pct, pct, g["done"], g["total"], rows))
    if not parts:
        parts.append('<p class="none"><b>No Goals Yet</b> Give cards a goal (and due dates) on their pages; '
                     'cards with the same goal add up here.</p>')
    if soon:
        parts.append('<section class="goal"><h2 class="sechead">Due Soon or Overdue</h2><ul class="garden-list plain">%s</ul></section>'
                     % "".join('<li><a class="ntl" href="/p/%s">%s</a> <span class="chip due due-%s">%s %s</span></li>'
                               % (quote(c["slug"]), e(c["title"]), goalsmod.due_state(c), e(c["due"]), e(ago_or_in(c["due"])))
                               for c in soon))
    return page(ctx, "kanban", "goals - konbini", board_header(ctx, counts_of(cards), "Goals", "plan") +
                '<main class="streams goals">%s%s</main>' % (plan_nav("goals"), "".join(parts)), KANBAN_TABS, "")


def timeline_page(ctx, cards, data, start, end, group):
    """/timeline: started -> done bars per card, Log-row milestones as dots, due dates as diamonds, a today line,
    grouped by area or stream."""
    span = (end - start).days or 1
    today = datetime.date.today()
    pos = lambda d: (d - start).days / span * 100
    months, m = [], start.replace(day=1)
    while m < end:
        if m >= start:
            months.append('<span class="tick" style="left:%.2f%%">%s</span>' % (pos(m), e(m.strftime("%b" if m.month != 1 else "%b %Y"))))
        m = (m + datetime.timedelta(days=32)).replace(day=1)
    ticks = '<div class="grow tlhead"><span></span><div class="tlticks">%s</div><span></span></div>' % "".join(months)
    todayline = ('<span class="gtoday" style="left:%.2f%%"></span>' % pos(today)) if start <= today < end else ""
    sections = []
    for name, rows in data["groups"]:
        bars = []
        for r in rows:
            c = r["card"]
            inner = ""
            if r["start"]:
                a = max(r["start"], start)
                b = min(r["end"] or today, end - datetime.timedelta(days=1))
                b = max(a, b)
                inner += ('<div class="gbar col-%s%s" style="left:%.2f%%;width:%.2f%%" title="%s &rarr; %s"></div>'
                          % (c["board"], "" if r["end"] else " open", pos(a), max((b - a).days + 1, 1) / span * 100,
                             r["start"].isoformat(), r["end"].isoformat() if r["end"] else "ongoing"))
            inner += "".join('<span class="gmile" style="left:%.2f%%" title="%s: %s"></span>' % (pos(d), d.isoformat(), e(t))
                             for d, t in r["milestones"])
            if r["due"] and start <= r["due"] < end:
                inner += '<span class="gdue due-%s" style="left:%.2f%%" title="due %s"></span>' % (
                    goalsmod.due_state(c) or "done", pos(r["due"]), r["due"].isoformat())
            dates = "%s &rarr; %s" % (r["start"].strftime("%b %-d") if r["start"] else "&middot;",
                                      r["end"].strftime("%b %-d") if r["end"] else ("now" if r["start"] else "&middot;"))
            bars.append('<div class="grow"><a class="gname" href="/p/%s">%s</a><div class="gtrack">%s%s</div>'
                        '<span class="gdates">%s <span class="col-badge col-%s">%s</span></span></div>'
                        % (quote(c["slug"]), e(c["title"]), todayline, inner, dates, c["board"], e(SHORT.get(c["board"], ""))))
        sections.append('<section class="tlgroup"><h2 class="sechead">%s <span class="colcount">%d</span></h2>'
                        '<div class="gantt">%s</div></section>' % (e(name), len(rows), "".join(bars)))
    shift = lambda n: (start.replace(day=1) + datetime.timedelta(days=31 * n)).replace(day=1)
    months_n = max(1, round(span / 30.4))
    nav = ('<p class="tlnav"><a href="/timeline?from=%s&amp;months=%d&amp;by=%s">&larr; earlier</a> &middot; '
           '<a href="/timeline?by=%s">now</a> &middot; <a href="/timeline?from=%s&amp;months=%d&amp;by=%s">later &rarr;</a>'
           ' &middot; by <a href="/timeline?from=%s&amp;months=%d&amp;by=area"%s>area</a> / '
           '<a href="/timeline?from=%s&amp;months=%d&amp;by=stream"%s>stream</a> &middot; '
           '<span class="gmile inline"></span> Log milestone &middot; <span class="gdue inline"></span> due</p>'
           % (shift(-3).strftime("%Y-%m"), months_n, group, group, shift(3).strftime("%Y-%m"), months_n, group,
              start.strftime("%Y-%m"), months_n, ' class="here"' if group == "area" else "",
              start.strftime("%Y-%m"), months_n, ' class="here"' if group == "stream" else ""))
    body = nav + ticks + ("".join(sections) or '<p class="none"><b>Nothing in This Range</b> No card was worked on or is due '
                                                 'in these months.</p>')
    title = "%s &ndash; %s" % (start.strftime("%b %Y"), (end - datetime.timedelta(days=1)).strftime("%b %Y"))
    return page(ctx, "kanban", "timeline - konbini", board_header(ctx, counts_of(cards), "Timeline", "plan") +
                '<main class="timeline">%s<h1 class="tltitle">%s</h1>%s</main>' % (plan_nav("timeline"), title, body), KANBAN_TABS, "")


def search_page(ctx, cards, q, claims=None):
    """/search: the room search (vaultkit v0.6). Konbini searches its cards (title, summary, next, waiting, tags,
    family, stream, goal), title matches first, then by column, archived last; then hands off to Shiori."""
    order = {c: i for i, c in enumerate(list(SHOWN) + ["archived"])}
    hits = []
    if q.strip():
        from common import filter_cards
        hits = filter_cards([c for c in cards if c.get("board")], {"q": [q.strip()]}, claims)
        hits.sort(key=lambda c: (q.strip().lower() not in c["title"].lower(), order.get(c["board"], 9), sort_key(c)))
    if not q.strip():
        body = '<p class="none"><b>Search Cards</b> Type in the search field above (or press /).</p>'
    elif not hits:
        body = '<p class="none"><b>No Matching Cards</b> Nothing on the board mentions &ldquo;%s&rdquo;.</p>' % e(q)
    else:
        body = ('<p class="none">%d card%s</p><div class="nowlist">%s</div>'
                % (len(hits), "" if len(hits) == 1 else "s",
                   "\n".join(card_html(ctx, c, (claims or {}).get(c["slug"]), show_area=True, show_updated=True) for c in hits)))
    body += shell.handoff(q.strip())
    return page(ctx, "kanban", ("%s - search - konbini" % q) if q else "search - konbini",
                board_header(ctx, counts_of(cards), "Search", "") + '<main class="now search">%s</main>' % body, KANBAN_TABS, "")


BOARD_SETTINGS = [("group", "Group By", [("area", "Area"), ("family", "Family")], "area"),
                  ("doneCards", "Done Cards", [("5", "5"), ("10", "10"), ("all", "All")], "all")]


def setting(ctx, key):
    """A Board setting from its cookie (machiya.js writes it from /settings), else its default."""
    for k, _, choices, default in BOARD_SETTINGS:
        if k == key:
            value = (getattr(ctx, "extra", None) or {}).get(key, default)
            return value if value in dict(choices) else default
    return None


def account_section(name):
    """Settings -> Account, for a principal signed in with the built-in sign-in (a session): who, and a sign-out
    button (a same-origin form post to /signout, vaultkit.signin)."""
    if not name:
        return None
    return ("Account", [shell.row("Signed In As", e(name)),
                        '<form class="item" method="post" action="/signout"><span>This Browser</span>'
                        '<button type="submit">Sign Out</button></form>'],
            "Signing out ends the session in this browser only.")


def signin_needed(ctx, target):
    """The 401 page for a browser without a session when the built-in sign-in is on: a link to /signin?next=<target>.
    No board data: the caller hasn't been let in (ctx is the bare appearance cookies)."""
    href = "/signin?next=" + quote(target, safe="")
    body = ('%s<main class="signin"><h1>Sign In</h1>'
            '<form class="group" method="get" action="/signin"><input type="hidden" name="next" value="%s">'
            '<p class="item">Konbini needs you to <a href="%s">sign in</a> first.</p>'
            '<button type="submit">Sign In</button></form>'
            '<p class="footnote">A session from another Machiya room counts here too when the rooms share a cookie '
            'domain.</p></main>') % (shell.header("konbini", [], "", shell.rooms(), settings=False), e(target), e(href))
    return shell.page(ctx, "konbini", "Sign In - konbini", body, manifest=False)


def settings(ctx, cards, version, vaultkit, status_text, account=""):
    """/settings: Appearance, Board, Apps, Account (a signed-in session only), About (docs/ui.md; per device, in
    Shiori's style)."""
    board = ("Board", [shell.select(label, key, choices, setting(ctx, key), cookie=True)
                       for key, label, choices, _ in BOARD_SETTINGS] + [shell.offline_row()],
             "Group By picks the board's swimlanes: Area (a card's area tag) or Family (its family field). "
             "Done Cards is how many finished cards each lane shows, newest first; All shows every one. "
             "Offline Copies are the pages this device keeps to show when the board can't be reached; "
             "Clear Offline Copies removes them.")
    body = shell.settings_page([shell.appearance_section(ctx), board, shell.apps_section("konbini", shell.rooms(), {}),
                                account_section(account), shell.about_section("konbini", version, status_text, vaultkit)], "konbini")
    return page(ctx, "kanban", "settings - konbini", board_header(ctx, counts_of(cards), "Settings", "") + body,
                KANBAN_TABS, "")


# -- card page -----------------------------------------------------------------

def reading_section(reading, query, search_url=""):
    """Pages I've read, from Hister (private: the authenticated pages only)."""
    if not reading:
        return ""
    rows = "".join(
        '<li><a href="%s">%s</a> <span class="when">%s%s</span> <a class="nlink" href="%s" title="Hister\'s copy">copy</a>%s</li>'
        % (e(r["url"]), e(r["title"]), e(r["domain"]), (" &middot; saved " + e(r["added"])) if r["added"] else "", e(r["copy"]),
           (' <span class="topic">%s</span>' % e(r["why"])) if r["why"] else "")
        for r in reading)
    more = (' <a class="nlink" href="%s">search Hister for &ldquo;%s&rdquo;</a>' % (e(search_url), e(query))) if search_url else ""
    return ('<section class="readsec"><h3 class="sechead">Pages I&rsquo;ve read</h3>'
            '<ul class="garden-list plain readlist">%s</ul><p class="none">From Hister, private.%s</p></section>' % (rows, more))


def dep_links(items):
    return " ".join('<a class="deplink" href="/p/%s">%s</a> <span class="chip col-%s colchip">%s</span>'
                    % (quote(d["slug"]), e(d["title"]), e(d.get("board") or "none"),
                       e(SHORT.get(d.get("board"), "Unsorted"))) for d in items)


def detail(ctx, card, cards, events=(), claim=None, tagmsg="", pending="", reading="", dep=None):
    note = card["path"][:-3] if card["path"].endswith(".md") else card["path"]
    obsidian = obsidian_url(note)
    col = card["board"] or ""
    badges = ['<span class="chip col-%s colchip">%s</span>' % (col or "none", e(COLUMN_TITLES.get(col, "Unsorted")))]
    badges += chips(card, show_area=True)
    if claim:
        badges.append(claim_badge(claim))
    moves = ('<form class="moves" method="post" action="/move"><input type="hidden" name="slug" value="%s">%s</form>'
             % (e(card["slug"]), "".join(
                 '<button type="submit" name="board" value="%s" class="mv col-%s"%s>%s</button>'
                 % (c, c, " disabled" if c == col else "", e(SHORT[c])) for c in SHOWN)))
    rows = [
        ("Summary", e(card.get("summary"))),
        ("Next", e(card.get("next"))),
        ("Stream", ('<a href="/streams/%s">%s</a>' % (quote(card["stream"], safe=""), e(card["stream"])))
         if card.get("stream") else ""),
        ("Goal", ('<a href="/goals#g-%s">%s</a>' % (slugify(card["goal"]), e(card["goal"]))) if card.get("goal") else ""),
        ("Due", ('%s <span class="chip due due-%s">%s</span>' % (e(card["due"]), goalsmod.due_state(card) or "done",
                                                                 e(ago_or_in(card["due"]))))
         if card.get("due") else ""),
        ("Blocked by", e(card.get("blocked_by"))),
        ("Waits for", (dep_links((dep or {}).get("waits_for", []))
                       + "".join(' <span class="chip why" title="no card or note by this name">%s?</span>' % e(u)
                                 for u in (dep or {}).get("unresolved", [])))
         + (' <a class="nlink" href="/deps">graph</a>' if (dep or {}).get("waits_for") else "")),
        ("Unblocks", dep_links((dep or {}).get("unblocks", []))),
        ("Checklist", "%d/%d" % (card["checks_done"], card["checks_total"]) if card["checks_total"] else ""),
        ("Topics", " ".join('<span class="topic">%s</span>' % e(t) for t in card.get("topics") or [])),
        ("Machines", e(" ".join(card.get("machines") or []))),
        ("Family", e(card.get("family"))),
        ("Repo", '<a href="%s">%s</a>' % (e(card["repo"]), e(card["repo"])) if card.get("repo") else ""),
        ("Updated", '%s <span class="when">%s</span>' % (e(card.get("updated")), e(ago(card.get("updated"))))
         if card.get("updated") else ""),
        ("Garden", ('<a href="%s/n/%s">%s</a>' % (e(GARDEN_URL), quote(note), "published" if card.get("publish") else "not published (preview, publish)"))
         if GARDEN_URL else ""),
        ("Post", post_cell(card)),
        ("Writing kit", '<a href="/p/%s/kit">outline and facts</a> &middot; <a href="/p/%s/kit.md">markdown</a>'
         % (quote(card["slug"]), quote(card["slug"]))),
        # The note is read in Kura and edited in Obsidian; the board shows the project.
        ("Note", '%s%s%s' % (
            e(card["path"]), (' &middot; <a href="%s/n/%s">View in Kura</a>' % (e(KURA_URL), quote(note))) if KURA_URL else "",
            (' &middot; <a href="%s">Edit in Obsidian</a>' % e(obsidian)) if obsidian else "")),
    ]
    table = "".join('<tr><th>%s</th><td>%s</td></tr>' % (k, v) for k, v in rows if v)
    body = (
        '<main class="detail"><h1 class="ntitle">%s</h1><p class="badges">%s</p>%s'
        '<table class="detail">%s</table>%s%s%s%s'
        '<p class="foot"><a href="/">&larr; board</a> &middot; <a href="/api/cards/%s">json</a></p></main>'
        % (e(card["title"]), "".join(badges), moves, table,
           edit_form(ctx, card) + "".join('<datalist id="%ss">%s</datalist>' % (key, "".join(
               '<option value="%s">' % e(v) for v in sorted({c[key] for c in cards if c.get(key)}, key=str.lower)))
               for key in ("stream", "goal")),
           tags_form(card, tagmsg, pending), reading,
           history(ctx, events), quote(card["slug"])))
    return page(ctx, "kanban", card["title"] + " - konbini", board_header(ctx, counts_of(cards), card["title"], "") + body,
                KANBAN_TABS, "board")


def edit_form(ctx, card):
    pri = "".join('<option value="%s"%s>%s</option>' % (v, " selected" if str(card.get("priority") or "") == v else "", l)
                  for v, l in (("", "-"), ("1", "P1"), ("2", "P2"), ("3", "P3")))
    return (
        '<form class="editform" method="post" action="/p/%s">'
        '<label>Priority <select name="priority">%s</select></label>'
        '<label>Next <input type="text" name="next" value="%s"></label>'
        '<label>Blocked by <input type="text" name="blocked_by" value="%s"></label>'
        '<label>Depends on <input type="text" name="dependsOn" value="%s" placeholder="card titles, comma-separated"></label>'
        '<label>Stream <input type="text" name="stream" value="%s" placeholder="the workstream, e.g. Release 1.0" list="streams"></label>'
        '<label>Goal <input type="text" name="goal" value="%s" placeholder="the goal it counts toward" list="goals"></label>'
        '<label>Due <input type="date" name="due" value="%s"></label>'
        '<label>Add note <input type="text" name="comment" value="" placeholder="a line for the history"></label>'
        '<label>Post <select name="post">%s</select></label>'
        '<label>Post URL <input type="text" name="post_url" value="%s" placeholder="https://example.com/blog/..."></label>'
        '<div class="row"><button type="submit">Save</button></div></form>'
    ) % (quote(card["slug"]), pri, e(card.get("next")), e(card.get("blocked_by")), e(", ".join(card.get("dependsOn") or [])),
         e(card.get("stream")), e(card.get("goal")), e(card.get("due")), post_options(card), e(card.get("post_url")))


def tags_form(card, tagmsg="", pending=""):
    chips = "".join(
        '<form class="tagchip" method="post" action="/p/%s/tags"><input type="hidden" name="remove" value="%s">'
        '<span class="topic">%s</span><button type="submit" class="x" aria-label="remove %s">&times;</button></form>'
        % (quote(card["slug"]), e(t), e(t), e(t)) for t in card.get("tags") or [] if t.startswith(("topic/", "machine/", "effort/")))
    return ('<section class="tagsec"><h3 class="sechead">Tags</h3><div class="tagrow">%s'
            '<form class="tagadd" method="post" action="/p/%s/tags"><input type="text" name="add" placeholder="topic/x" value="%s">'
            '<label class="check"><input type="checkbox" name="confirm" value="1"%s> new tag</label>'
            '<button type="submit" class="quiet">Add</button></form></div>%s</section>'
            % (chips, quote(card["slug"]), e(pending), " checked" if pending else "",
               ('<p class="tagmsg">%s</p>' % e(tagmsg)) if tagmsg else ""))


def history(ctx, events):
    if not events:
        return ""
    items = []
    for kind, *rest in collapse_history(events):
        if kind == "event":
            items.append("<li>%s</li>" % event_line(rest[0]))
        else:
            who, group = rest
            span = "%s to %s" % (e(group[-1].get("ts", "")[11:16]), e(group[0].get("ts", "")[11:16]))
            items.append('<li><details><summary>%s &middot; %s &middot; %d notes (%s)</summary><ul>%s</ul></details></li>'
                         % (e(group[0].get("ts", "")[:10]), e(who), len(group), span,
                            "".join("<li>%s</li>" % event_line(ev) for ev in group)))
    return '<section class="history"><h3>History</h3><ul class="history">%s</ul></section>' % "".join(items)


def archived(ctx, cards, activity=None):
    items = sorted((c for c in cards if c["board"] == "archived"), key=lambda c: c.get("updated") or "", reverse=True)
    rows = "".join('<li><a class="ntl" href="/p/%s">%s</a> <span class="when">%s</span><p class="summary">%s</p>'
                   '<div class="meta"><span class="chip area">%s</span><a class="btn quiet" href="/p/%s/kit">kit</a></div></li>'
                   % (quote(c["slug"]), e(c["title"]), e(ago(c.get("updated"))), e(c.get("summary") or ""), e(c.get("area") or ""), quote(c["slug"]))
                   for c in items) or '<li class="none"><b>Nothing Archived</b></li>'
    body = ('<main class="posts"><p class="none">Archived cards keep their notes and kits; move one back from its card page to revive it.</p>'
            '<section><h2 class="sechead">Archived <span class="colcount">%d</span></h2><ul class="postlist plainlist">%s</ul></section></main>'
            % (len(items), rows))
    return page(ctx, "kanban", "archived - konbini", board_header(ctx, counts_of(cards), "Archived", "") + body, KANBAN_TABS, "board")


def share(ctx, cards, title="", url="", text="", lanes=()):
    opts = "".join('<option value="%s"%s>%s</option>' % (e(l), " selected" if l == "projects" else "", e(l)) for l in lanes)
    body = ('<main class="detail share"><h1 class="ntitle">Capture</h1>'
            '<p class="none">Saves a link as a backlog idea card with a stub note. Share to Konbini from Chrome or Android, '
            'or open <code>/share?url=…&amp;title=…</code> from an iOS Shortcut.</p>'
            '<form class="editform" method="post" action="/share">'
            '<label>Title <input type="text" name="title" value="%s" required></label>'
            '<label>URL <input type="text" name="url" value="%s"></label>'
            '<label>Note <input type="text" name="text" value="%s"></label>'
            '<label>Area <select name="area">%s</select></label>'
            '<div class="row"><button type="submit">Add to backlog</button></div></form></main>'
            % (e(title), e(url), e(text), opts))
    return page(ctx, "kanban", "capture - konbini", board_header(ctx, counts_of(cards), "Capture", "") + body, KANBAN_TABS, "board")


def message(ctx, title, text):
    return page(ctx, "kanban", title, '<main class="msg"><h2>%s</h2><p>%s</p></main>' % (e(title), e(text)))


def offline(ctx, app):
    return page(ctx, app, "Offline", '<main class="msg"><h2>Offline</h2><p>This page needs the network. '
                'If you are on the phone, check that you can reach the server. Pages you have opened before '
                'still work: <a href="%s">Konbini</a>.</p></main>' % APPS[app]["start"], KANBAN_TABS, "")


# -- calendar and roundups -------------------------------------------------------

def calendar(ctx, month, cards):
    start = month["start"]
    head = "".join('<th>%s</th>' % d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    rows, day = [], start - datetime.timedelta(days=start.weekday())
    while day < month["end"] or day.weekday() != 0:
        cells = []
        for _ in range(7):
            inside = start <= day < month["end"]
            seen, items = {}, []
            for i in month["days"].get(day, []):
                key = (i.kind, i.title)  # machine changes fold per host, milestones per project
                if key in seen:
                    seen[key][1] += 1
                else:
                    seen[key] = [i, 1]
                    items.append(seen[key])
            lines = []
            for i, n in items[:6]:
                if i.kind == "systems":
                    label = "%s: %s" % (i.title, ("%d changes" % n) if n > 1 else i.text[:40])
                    inner = '<a href="/roundup?period=day&amp;date=%s">%s</a>' % (day.isoformat(), e(label[:48]))
                    lines.append('<div class="ev ev-systems">%s</div>' % inner)
                    continue
                label = i.title
                inner = ('<a href="/p/%s">%s</a>' % (quote(i.slug), e(label[:48]))) if i.slug else e(label[:48])
                lines.append('<div class="ev ev-%s">%s%s</div>' % (
                    i.kind, inner, (' <span class="evn">&times;%d</span>' % n) if n > 1 else ""))
            if len(items) > 6:
                lines.append('<div class="evmore">+%d more</div>' % (len(items) - 6))
            num = ('<a class="daynum" href="/roundup?period=day&amp;date=%s">%d</a>' % (day.isoformat(), day.day)
                   if inside else '<span class="daynum">%d</span>' % day.day)
            cells.append('<td class="day%s%s">%s%s</td>' % ("" if inside else " out",
                                                            " today" if day == datetime.date.today() else "",
                                                            num, "".join(lines)))
            day += datetime.timedelta(days=1)
        rows.append("<tr>%s</tr>" % "".join(cells))
        if day >= month["end"] and day.weekday() == 0:
            break
    legend = "".join('<span class="lg ev-%s">%s</span>' % (k, n) for n, k in
                     (("started", "started"), ("done", "done"), ("milestone", "milestone"),
                      ("system change", "systems"), ("new card", "idea")))
    # Projects this month as a timeline: one bar per project across the month's days.
    today = datetime.date.today()
    days_in = (month["end"] - start).days
    bars = []
    for s, en, c in month["spans"]:
        a = max(s, start)
        b = min(en or min(today, month["end"] - datetime.timedelta(days=1)), month["end"] - datetime.timedelta(days=1))
        if b < a:
            b = a
        left = (a - start).days / days_in * 100
        width = max(((b - a).days + 1) / days_in * 100, 1.5)
        marks = ""
        if start <= s < month["end"]:
            marks += '<span class="gmark gstart" title="started %s"></span>' % s.isoformat()
        if en and start <= en < month["end"]:
            marks += '<span class="gmark gend" title="finished %s"></span>' % en.isoformat()
        bars.append(
            '<div class="grow"><a class="gname" href="/p/%s">%s</a>'
            '<div class="gtrack">%s<div class="gbar col-%s%s" style="left:%.1f%%;width:%.1f%%" title="%s &rarr; %s">%s</div></div>'
            '<span class="gdates">%s &rarr; %s <span class="col-badge col-%s">%s</span></span></div>'
            % (quote(c["slug"]), e(c["title"]),
               ('<span class="gtoday" style="left:%.1f%%"></span>' % ((today - start).days / days_in * 100)) if start <= today < month["end"] else "",
               c["board"] or "none", "" if en else " open", left, width, s.isoformat(), en.isoformat() if en else "ongoing", marks,
               s.strftime("%b %d"), en.strftime("%b %d") if en else "&middot;", c["board"] or "none", e(SHORT.get(c["board"], ""))))
    spans = "".join(bars)
    # Phones: a compact month grid with dots, then only the days that have something.
    mini, daylist = [], []
    d = start - datetime.timedelta(days=start.weekday())
    while d < month["end"] or d.weekday() != 0:
        inside = start <= d < month["end"]
        items = month["days"].get(d, []) if inside else []
        kinds = []
        for i in items:
            if i.kind not in kinds:
                kinds.append(i.kind)
        dots = "".join('<i class="ev-%s"></i>' % k for k in kinds[:4])
        mini.append('<a class="mday%s%s%s" href="#d%s">%d<span class="dots">%s</span></a>'
                    % ("" if inside else " out", " today" if d == today else "", " has" if items else "",
                       d.isoformat() if inside else "", d.day, dots))
        if items:
            seen, lines = {}, []
            for i in items:
                key = (i.kind, i.title)
                if key in seen:
                    seen[key][1] += 1
                else:
                    seen[key] = [i, 1]
            for i, n in list(seen.values())[:8]:
                if i.kind == "systems":
                    label = "%s: %s" % (i.title, ("%d changes" % n) if n > 1 else i.text[:40])
                    lines.append('<div class="ev ev-systems"><a href="/roundup?period=day&amp;date=%s">%s</a></div>' % (d.isoformat(), e(label[:60])))
                else:
                    inner = ('<a href="/p/%s">%s</a>' % (quote(i.slug), e(i.title[:60]))) if i.slug else e(i.title[:60])
                    lines.append('<div class="ev ev-%s">%s%s</div>' % (i.kind, inner, (' <span class="evn">&times;%d</span>' % n) if n > 1 else ""))
            if len(seen) > 8:
                lines.append('<div class="evmore">+%d more</div>' % (len(seen) - 8))
            daylist.append('<li id="d%s"%s><a class="daynum" href="/roundup?period=day&amp;date=%s">%s</a>%s</li>'
                           % (d.isoformat(), ' class="today"' if d == today else "", d.isoformat(), d.strftime("%a %b %d"), "".join(lines)))
        d += datetime.timedelta(days=1)
        if d >= month["end"] and d.weekday() == 0:
            break
    phone = ('<div class="minigrid">%s%s</div><ul class="daylist">%s</ul>'
             % ("".join('<b>%s</b>' % w for w in ("M", "T", "W", "T", "F", "S", "S")), "".join(mini),
                "".join(daylist) or '<li class="none"><b>Nothing This Month</b></li>'))
    body = (
        '<main class="calpage"><p class="monthnav"><a href="/calendar?month=%s">&lsaquo; %s</a>'
        '<a href="/roundup?period=month&amp;date=%s">roundup for %s</a><a href="/calendar?month=%s">%s &rsaquo;</a></p>'
        % (month["prev"].strftime("%Y-%m"), month["prev"].strftime("%b"), start.isoformat(),
           start.strftime("%B"), month["next"].strftime("%Y-%m"), month["next"].strftime("%b")) +
        '<table class="cal"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, "".join(rows)) +
        phone +
        '<p class="legend">%s</p>' % legend +
        ('<section class="spans"><h3 class="sechead">Projects this month</h3><div class="gantt">%s</div></section>' % spans if spans else "") + '</main>')
    return page(ctx, "kanban", "calendar - konbini",
                board_header(ctx, counts_of(cards), start.strftime("%B %Y"), "calendar") + body, KANBAN_TABS, "calendar")


def roundup(ctx, r, cards):
    kinds = "".join(("<b>%s</b>" % k) if k == r["kind"] else
                    '<a href="/roundup?period=%s&amp;date=%s">%s</a>' % (k, r["start"].isoformat(), k)
                    for k in ("day", "week", "month", "year"))
    navline = ('<p class="monthnav"><a href="/roundup?period=%s&amp;date=%s">&lsaquo; previous</a>%s'
               '<a href="/roundup?period=%s&amp;date=%s">next &rsaquo;</a>'
               '<a href="/roundup.md?period=%s&amp;date=%s">markdown</a></p>'
               % (r["kind"], r["prev"].isoformat(), kinds, r["kind"], r["next"].isoformat(),
                  r["kind"], r["start"].isoformat()))
    parts = []
    for key, name, rows in r["sections"]:
        items = []
        for row in rows:
            if isinstance(row, tuple):
                title, slug, group = row
                t = ('<a href="/p/%s">%s</a>' % (quote(slug), e(title))) if slug else e(title)
                if len(group) == 1:
                    items.append("<li><b>%s</b>: %s%s</li>" % (t, e(group[0].text), "" if r["kind"] == "day" else
                                 ' <span class="when">%s</span>' % group[0].date.strftime("%b %d")))
                else:
                    sub = "".join("<li>%s%s</li>" % (e(i.text), "" if r["kind"] == "day" else
                                                     ' <span class="when">%s</span>' % i.date.strftime("%b %d"))
                                  for i in group)
                    items.append("<li><b>%s</b><ul>%s</ul></li>" % (t, sub))
            elif key == "commit":
                items.append('<li>%s <span class="when">%s</span></li>' % (e(row.title), e(row.text)))
            else:
                t = ('<a href="/p/%s%s">%s</a>' % (quote(row.slug), "/kit" if key == "write" else "", e(row.title))) if row.slug else e(row.title)
                when = "" if r["kind"] == "day" else ' <span class="when">%s%s</span>' % (
                    "~" if row.approx else "", row.date.strftime("%b %d"))
                items.append("<li><b>%s</b>%s%s</li>" % (t, (": " + e(row.text)) if row.text else "", when))
        parts.append('<section class="rsec"><h3 class="sechead ev-%s">%s <span class="colcount">%d</span></h3>'
                     '<ul class="roundup">%s</ul></section>' % (key, e(name), len(rows), "".join(items)))
    if not parts:
        parts.append('<p class="none"><b>Nothing Recorded</b> No moves, Log rows or changes in this period.</p>')
    return page(ctx, "kanban", "roundup - konbini",
                board_header(ctx, counts_of(cards), "Roundup: " + r["label"], "roundup") +
                '<main class="roundup">%s%s</main>' % (navline, "\n".join(parts)), KANBAN_TABS, "roundup")


# -- writing kits and posts --------------------------------------------------------

def post_options(card, selected=None):
    cur = selected if selected is not None else (card.get("post") or "none")
    return "".join('<option value="%s"%s>%s</option>' % (p, " selected" if p == cur else "", p) for p in POST_STATES)


def post_cell(card):
    state = card.get("post") or "none"
    out = '<span class="chip post-%s">%s</span>' % (state, e(state))
    if card.get("post_url"):
        out += ' <a href="%s">%s</a>' % (e(card["post_url"]), e(card["post_url"]))
    return out


def post_form(card, cls="postform"):
    return ('<form class="%s" method="post" action="/p/%s"><label>Post <select name="post">%s</select></label>'
            '<label>URL <input type="text" name="post_url" value="%s" placeholder="https://example.com/blog/..."></label>'
            '<button type="submit" class="quiet">Save</button></form>'
            % (cls, quote(card["slug"]), post_options(card), e(card.get("post_url"))))


def size_chips(size):
    out = []
    if size.get("milestones"):
        out.append('<span class="chip">%d milestones</span>' % size["milestones"])
    if size.get("facts"):
        out.append('<span class="chip">%d facts</span>' % size["facts"])
    if size.get("images"):
        out.append('<span class="chip">%d images</span>' % size["images"])
    if size.get("days") is not None:
        out.append('<span class="chip">%d days</span>' % size["days"])
    return "".join(out)


def kit_page(ctx, card, k, html, cards):
    slug = quote(card["slug"])
    when = "%s &rarr; %s%s" % (e(k["started"] or "?"), e(k["finished"] or "not finished"), " (approx.)" if k["finished_approx"] else "")
    tools = ('<div class="kittools">'
             '<button type="button" class="kit-share" data-url="/p/%s/kit.md" data-name="%s-kit.md">Share</button>'
             '<button type="button" class="kit-copy quiet" data-url="/p/%s/kit.md">Copy Markdown</button>'
             '<a class="btn quiet" href="/p/%s/kit.md">kit.md</a><a class="btn quiet" href="/p/%s">Card</a>'
             '<a class="btn quiet" href="/posts">Posts</a></div>' % (slug, e(card["slug"]), slug, slug, slug))
    body = ('<main class="detail kit"><h1 class="ntitle">Writing kit: %s</h1>'
            '<p class="badges"><span class="chip colchip col-%s">%s</span><span class="chip">%s</span>%s</p>'
            '%s%s<div class="nbody kitbody">%s</div>'
            '<p class="foot"><a href="/posts">&larr; posts</a> &middot; <a href="/api/cards/%s/kit">json</a></p></main>'
            % (e(card["title"]), e(card["board"] or "none"), e(COLUMN_TITLES.get(card["board"], "Unsorted")), when,
               size_chips(k["size"]), tools, post_form(card), html, slug))
    return page(ctx, "kanban", "kit: " + card["title"] + " - konbini",
                board_header(ctx, counts_of(cards), "Writing kit", "posts") + body, KANBAN_TABS, "posts")


def posts(ctx, data, cards, show="ready"):
    show = show if show in ("ready", "progress", "skipped", "published") else "ready"
    def row(entry):
        c = entry["card"]
        slug = quote(c["slug"])
        fin = entry.get("finished") or ""
        when = ('<span class="when">%sfinished %s</span>' % ("~" if entry.get("approx") else "", e(ago(fin) or fin))) if fin else ""
        status = ('<span class="chip post-%s">%s</span>' % (entry["status"], e(entry["status"]))) if entry["status"] != "none" else ""
        exist = ""
        if entry.get("existing"):
            ex = entry["existing"][0]
            exist = ('<form class="markform" method="post" action="/p/%s"><span class="hint">Already written? '
                     '<a href="%s">%s</a> (%s)</span><input type="hidden" name="post" value="published">'
                     '<input type="hidden" name="post_url" value="%s"><button type="submit" class="quiet">Mark published</button></form>'
                     % (slug, e(ex["url"]), e(ex["title"]), e(ex["date"]), e(ex["url"])))
        skip = ('<form class="skipform" method="post" action="/p/%s"><input type="hidden" name="post" value="skipped">'
                '<button type="submit" class="quiet" title="not writing about this one (reversible)">Skip</button></form>' % slug)
        return ('<li class="postrow"><div class="postmain"><a class="ntl" href="/p/%s/kit">%s</a> %s%s'
                '<p class="summary">%s</p><div class="meta">%s<span class="chip area">%s</span></div>%s</div>'
                '<div class="postacts"><a class="btn" href="/p/%s/kit">Kit</a><a class="btn quiet" href="/p/%s">Card</a>%s</div></li>'
                % (slug, e(c["title"]), status, when, e(c.get("summary") or ""), size_chips(entry["size"]), e(c.get("area") or ""),
                   exist, slug, slug, skip))
    tabs = [("ready", "Ready to write"), ("progress", "In progress"), ("skipped", "Skipped"), ("published", "Published")]
    chips = "".join('<a href="/posts?show=%s"%s>%s <span class="n">%d</span></a>' % (k, ' class="here"' if k == show else "", label, len(data.get(k) or []))
                    for k, label in tabs if data.get(k) or k in ("ready", show))
    parts = ['<main class="posts">',
             '<p class="none">Finished projects without a blog post, newest first. Each kit gathers the outline and the facts; '
             'you write the post, then set the card to <b>published</b> with its URL. Skip parks one; it can be reconsidered.</p>',
             '<p class="typechips">%s</p>' % chips]
    if show == "ready":
        parts.append('<ul class="postlist">%s</ul>' % ("".join(row(x) for x in data["ready"]) or '<li class="none"><b>All Written Up</b> Every finished project has a post, or was skipped.</li>'))
    elif show == "progress":
        parts.append('<ul class="postlist">%s</ul>' % ("".join(row(x) for x in data["progress"]) or '<li class="none"><b>No Posts in Progress</b></li>'))
    elif show == "published":
        parts.append('<ul class="garden-list plain">%s</ul>' % ("".join(
            '<li><a href="/p/%s">%s</a> &middot; <a href="%s">%s</a></li>'
            % (quote(x["card"]["slug"]), e(x["card"]["title"]), e(x["url"]), e(x["url"] or "no URL")) for x in data["published"])
            or '<li class="none"><b>Nothing Published Yet</b></li>'))
    else:
        parts.append('<p class="none">Not writing about these, for now. Reconsider puts one back; the kit stays available.</p>'
                     '<ul class="garden-list plain">%s</ul>' % ("".join(
                         '<li class="skiprow"><a href="/p/%s">%s</a> <a class="nlink" href="/p/%s/kit">kit</a>'
                         '<form class="skipform" method="post" action="/p/%s"><input type="hidden" name="post" value="none">'
                         '<button type="submit" class="quiet">Reconsider</button></form></li>'
                         % (quote(x["card"]["slug"]), e(x["card"]["title"]), quote(x["card"]["slug"]), quote(x["card"]["slug"]))
                         for x in data["skipped"]) or '<li class="none"><b>Nothing Skipped</b></li>'))
    parts.append("</main>")
    return page(ctx, "kanban", "posts - konbini", board_header(ctx, counts_of(cards), "Posts", "posts") + "\n".join(parts),
                KANBAN_TABS, "posts")
