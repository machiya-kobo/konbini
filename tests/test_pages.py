"""The board's pages as a browser gets them: a note's HTML never runs on a page (the writing kit quotes the note),
every HTML page carries vaultkit's security headers, and the shared pieces (titles, 404, offline, the 401 page,
icons, the manifest, preferences) are wired in. Each board runs in its own process (settings are read at import) on
127.0.0.1, serving a throwaway vault, and is talked to over HTTP."""
import base64, json, os, re, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from vaultkit import identity  # noqa: E402

NOTE = ("---\ntitle: Kura\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\n"
        "project: kura\nstatus: wip\n---\n# Kura\n\n## Overview\n\n"
        "Reads <script>alert(1)</script> notes <img src=x onerror=alert(2)> and "
        "[a link](javascript:alert(3)) <a href=\"javascript:alert(4)\" onclick=\"alert(5)\">raw</a>.\n")
SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import app
    app.store.rebuild()
    app.serve(int(sys.argv[2]), "tailnet")
''')
OWNER_PW = "owner pass 1"
procs = []


def write_identity(folder):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "session.key"), "w") as f:
        f.write("k" * 43)
    data = {"version": 1, "session_key_file": "session.key", "principals": {
        "owner": {"id": "ownerid000000001", "kind": "person", "owner": True,
                  "password": identity.hash_password(OWNER_PW)}}}
    path = os.path.join(folder, "identity.toml")
    identity.write_file(path, data)
    return path


def start(identity_file=False, board_url=False, notes=None, **extra):
    """A board on a free port (KANBAN_AUTH=open unless extra says otherwise) -> port. board_url: KANBAN_BOARD_URL is
    its own plain-http address (the origin vaultkit's same-origin rule trusts)."""
    d = tempfile.mkdtemp()
    os.makedirs(d + "/vault/Projects")
    open(d + "/vault/Projects/Kura.md", "w").write(NOTE)
    for name, text in (notes or {}).items():
        open(d + "/vault/Projects/%s.md" % name, "w").write(text)
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", PYTHONDONTWRITEBYTECODE="1")
    for k in ("KANBAN_AUTH_HEADER", "KANBAN_SIGNIN", "KANBAN_BOARD_URL", "KANBAN_NIWA_URL", "KANBAN_KURA_URL",
              "KANBAN_TAILNET_USERS", "MACHIYA_IDENTITY_FILE", "MACHIYA_COOKIE_DOMAIN", "MACHIYA_ROOMS"):
        env.pop(k, None)
    if identity_file:
        env["MACHIYA_IDENTITY_FILE"] = write_identity(d + "/identity")
    if board_url:
        env["KANBAN_BOARD_URL"] = "http://127.0.0.1:%d" % port
    env.update(extra)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=open(d + "/server.log", "w"))      # a file: an unread pipe fills up and stalls the board
    procs.append(proc)
    logs[port] = d + "/server.log"
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("board did not start: " + open(d + "/server.log").read()[-500:])


logs = {}      # port -> the board's log file


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(port, method, path, headers=None, body=None):
    """-> (status, headers, body text)."""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method,
                                 headers=dict({"Host": "127.0.0.1:%d" % port}, **(headers or {})))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode("utf-8", "replace")


try:
    port = start()

    # -- a note's HTML never runs: the writing kit quotes the note's overview -------------------------------------
    st, h, body = call(port, "GET", "/p/kura/kit")
    assert st == 200 and "Reads" in body, (st, body[-500:])
    kit = body[body.index('class="nbody kitbody"'):]
    for bad in ("<script>alert", "onerror", "onclick", "javascript:"):
        assert bad not in kit, (bad, kit[:2000])

    # -- every HTML page carries vaultkit's security headers, and no page has inline script or on...= handlers ------
    csp = None
    for path in ("/", "/now", "/review", "/plan", "/goals", "/timeline", "/deps", "/search?q=kura", "/archived",
                 "/share", "/posts", "/calendar", "/roundup", "/settings", "/offline", "/p/kura", "/p/kura/kit",
                 "/p/nothing", "/streams/none", "/no/such/page"):
        st, h, body = call(port, "GET", path)
        assert h["Content-Type"].startswith("text/html"), (path, h["Content-Type"])
        assert "script-src 'self'" in (h["Content-Security-Policy"] or ""), (path, dict(h))
        assert h["X-Content-Type-Options"] == "nosniff" and h["Referrer-Policy"] == "same-origin", (path, dict(h))
        assert len(h.get_all("X-Content-Type-Options")) == 1, (path, h.get_all("X-Content-Type-Options"))
        mine = body
        assert not re.search(r"<script(?![^>]*\bsrc=)", mine), (path, re.findall(r"<script[^>]*>", mine))
        assert not re.search(r"<[^>]+\son[a-z]+\s*=", mine), (path, re.findall(r"<[^>]+\son[a-z]+\s*=[^>]*>", mine)[:3])
    st, h, body = call(port, "GET", "/api/cards")
    assert st == 200 and h["Content-Security-Policy"] is None       # JSON isn't a page
    st, h, body = call(port, "GET", "/")
    assert "data-submit" in body and "this.form.submit" not in body  # board.js posts the column select

    # -- titles: "What - Konbini" with the page names as the nav shows them; the board is "Konbini" ---------------
    for path, title in (("/", "Konbini"), ("/now", "Now - Konbini"), ("/review", "Review - Konbini"),
                        ("/plan", "Plan - Konbini"), ("/streams", "Streams - Konbini"), ("/goals", "Goals - Konbini"),
                        ("/posts", "Posts - Konbini"), ("/calendar", "Calendar - Konbini"),
                        ("/roundup", "Roundup - Konbini"), ("/settings", "Settings - Konbini"),
                        ("/p/kura", "Kura - Konbini"), ("/p/kura/kit", "Writing Kit: Kura - Konbini"),
                        ("/search?q=kura", "kura - Search - Konbini"), ("/offline", "Offline - Konbini"),
                        ("/nope", "Not Found - Konbini")):
        assert "<title>%s</title>" % title in call(port, "GET", path)[2], path

    # -- 404s are shell.not_found inside the room's header, nav and tab bar (never a dead end) ----------------------
    for path in ("/nope", "/p/nothing", "/p/nothing/kit", "/streams/nothing"):
        st, h, body = call(port, "GET", path)
        assert st == 404 and "Not Found" in body and 'class="nav"' in body and 'class="tabbar"' in body, (path, st)
        assert 'href="/">Go to Konbini</a>' in body, path
    # a refused write keeps the header too
    st, h, body = call(port, "POST", "/move", {"Origin": "http://evil.example"}, b"slug=kura&board=done")
    assert st == 403 and "Not Saved" in body and 'class="tabbar"' in body, (st, body[-300:])

    # -- the precached /offline: shell.offline, no status line, no search box --------------------------------------
    st, h, body = call(port, "GET", "/offline")
    assert st == 200 and "be reached. Pages you&#x27;ve opened before still work" in body and 'class="tabbar"' in body
    assert 'class="status' not in body and 'type="search"' not in body and "Tailscale" not in body, body[-800:]

    # -- Card Style: cards are tinted by their column; the setting is a row in Settings and a <body> attribute ------------
    st, h, board = call(port, "GET", "/")
    assert 'class="card tinted is-card col-' in board and "data-card-style" not in board
    st, h, sett = call(port, "GET", "/settings")
    assert '<span>Card Style</span>' in sett and 'data-set="cardStyle"' in sett, sett[:200]
    assert [m for m in re.findall(r'<option value="(tint|solid|bar|none)"', sett)] == ["tint", "solid", "bar", "none"]
    assert "Left Bar" in sett and '<option value="tint" selected>Tint</option>' in sett
    for style in ("solid", "bar", "none"):
        st, h, styled = call(port, "GET", "/", headers={"Cookie": "cardStyle=" + style})
        assert '<body data-card-style="%s" class="' % style in styled, (style, styled[styled.index("<body"):][:120])
        assert 'selected>' in call(port, "GET", "/settings", headers={"Cookie": "cardStyle=" + style})[2]
    assert "data-card-style" not in call(port, "GET", "/", headers={"Cookie": "cardStyle=tint"})[2]
    assert "data-card-style" not in call(port, "GET", "/", headers={"Cookie": "cardStyle=nonsense"})[2]

    # -- gzip: text answers over 1 KB are compressed for a client that asks, the same bytes once unpacked ---------------
    import gzip, http.client
    def raw_get(path, enc):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", path, headers={"Host": "127.0.0.1:%d" % port, **({"Accept-Encoding": enc} if enc else {})})
        r = c.getresponse(); data = r.read(); h = dict(r.getheaders()); c.close()
        return r.status, h, data
    st, h, plain = raw_get("/", "")
    assert st == 200 and "Content-Encoding" not in h and len(plain) > 1024
    st, h, packed = raw_get("/", "gzip, deflate")
    assert h.get("Content-Encoding") == "gzip" and "Accept-Encoding" in h.get("Vary", "") and len(packed) < len(plain) // 2, h
    assert gzip.decompress(packed) == plain, "the gzipped page differs from the plain one"
    css = re.search(r'href="(/static/board\.css[^"]*)"', plain.decode()).group(1)
    st, h, packed = raw_get(css, "gzip")
    assert h.get("Content-Encoding") == "gzip" and "immutable" in h.get("Cache-Control", "") and raw_get(css, "gzip")[2] == packed
    assert gzip.decompress(packed) == raw_get(css, "")[2]
    st, h, tiny = raw_get("/healthz", "gzip")
    assert "Content-Encoding" not in h and tiny == b"ok\n"

    # -- the log has the request without its query: a search term is the user's, not the log's ----------------------------
    call(port, "GET", "/search?q=secretlantern")
    call(port, "GET", "/?topic=secretfilter")
    time.sleep(0.2)
    log = open(logs[port]).read()
    assert '"GET /search' in log and "secretlantern" not in log and "secretfilter" not in log, log[-400:]

    # -- icons are named after the room key; the old kanban-* names answer 301 --------------------------------------
    st, h, body = call(port, "GET", "/")
    assert 'href="/static/icons/konbini-small.svg"' in body and 'href="/static/icons/konbini.ico"' in body
    assert 'href="/static/icons/konbini-apple-180.png"' in body
    # the favicon is the small variant of the icon (it reads at 16 px); favicon.ico holds 16, 32 and 48 px of it, and the
    # root /favicon.ico answers with the same file; the header mark (machiya.css) is the full drawing, the same as konbini.svg
    icons_dir = os.path.join(APP, "static", "icons")
    with open(os.path.join(icons_dir, "konbini.ico"), "rb") as f:
        ico = f.read()
    assert ico[:4] == b"\0\0\1\0" and ico[4] == 3 and sorted((ico[6 + 16 * i], ico[7 + 16 * i]) for i in range(3)) == [(16, 16), (32, 32), (48, 48)], ico[:48]
    st, h, _ = call(port, "GET", "/favicon.ico")
    assert st == 200 and h["Content-Type"] == "image/x-icon" and "attachment" not in (h.get("Content-Disposition") or ""), (st, dict(h))
    with open(os.path.join(icons_dir, "konbini.svg"), "rb") as f:
        full = f.read()
    css = call(port, "GET", re.search(r'href="(/static/machiya\.css[^"]*)"', body).group(1))[2]
    mark = re.search(r'\.seal\.icon\[data-room="konbini"\] \{ background-image: url\("data:image/svg\+xml;base64,([^"]+)"\)', css)
    assert mark and base64.b64decode(mark.group(1)).strip() == full.strip(), "the header mark is not Konbini's icon"
    with open(os.path.join(icons_dir, "konbini-small.svg"), "rb") as f:
        assert b"viewBox=\"0 0 512 512\"" in f.read()
    for name, px in (("konbini-apple-180.png", 180), ("konbini-192.png", 192), ("konbini-512.png", 512), ("konbini-maskable-512.png", 512)):
        with open(os.path.join(icons_dir, name), "rb") as f:
            head = f.read(24)
        assert head[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(head[16:20], "big") == px == int.from_bytes(head[20:24], "big"), name
    for name in ("konbini.svg", "konbini-small.svg", "konbini.ico", "konbini-apple-180.png", "konbini-192.png", "konbini-512.png", "konbini-maskable-512.png"):
        st, h, _ = call(port, "GET", "/static/icons/" + name)
        assert st == 200 and h["Content-Type"].startswith("image/"), (name, st)
    # -- the shared pills (machiya.css): Group By, Area, the phone's column tabs, the Plan nav; state and link chips -----
    assert 'class="segmented" aria-label="Group By"' in body and '<a href="/?group=area" aria-current="true">Area</a>' in body, body[:300]
    assert 'class="pills coltabs"' in body and 'class="pill col-ready"' in body and 'class="count">' in body
    assert 'class="topic"' not in body and "fchip" not in body and "filterbar" in body
    st, h, grouped = call(port, "GET", "/?group=stream&area=crafts")
    assert 'href="/?area=crafts&amp;group=stream" aria-current="true">Stream (Project)' in grouped.replace('group=stream&amp;area=crafts', 'area=crafts&amp;group=stream'), grouped[:200]
    st, h, plan = call(port, "GET", "/goals")
    assert '<a href="/goals" aria-current="page">Goals' in plan and 'class="subnav"' not in plan.replace("pills subnav", ""), plan[:200]
    for old in ("kanban.svg", "kanban-192.png", "kanban-apple-180.png", "kanban-maskable-512.png"):
        st, h, _ = call(port, "GET", "/static/icons/" + old)
        assert (st, h["Location"]) == (301, "/static/icons/konbini" + old[len("kanban"):]), (old, st, h["Location"])
    assert call(port, "GET", "/static/icons/kanban-nothing.png")[0] == 404
    manifest = json.loads(call(port, "GET", "/manifest.webmanifest")[2])
    assert {i["src"] for i in manifest["icons"]} == {"/static/icons/konbini-192.png", "/static/icons/konbini-512.png",
                                                    "/static/icons/konbini-maskable-512.png"}, manifest["icons"]

    # the manifest: shortcuts to the main pages (each with an icon), a category, the language
    assert manifest["lang"] == "en" and manifest["categories"] == ["productivity"], manifest
    assert [s["url"] for s in manifest["shortcuts"]] == ["/", "/now", "/review", "/share"], manifest["shortcuts"]
    for s in manifest["shortcuts"]:
        assert s["name"] and s["icons"] and all(call(port, "GET", i["src"])[0] == 200 for i in s["icons"]), s
        assert call(port, "GET", s["url"])[0] == 200, s
    assert manifest["background_color"] == "#1a1b26"              # System, the device unknown: Night
    # a light device gets a light splash screen (vaultkit 0.14); a theme chosen in Settings still wins
    st, h, body = call(port, "GET", "/manifest.webmanifest", {"Sec-CH-Prefers-Color-Scheme": "light"})
    light = json.loads(body)
    assert (light["background_color"], light["theme_color"]) == ("#e1e2e7", "#d0d5e3"), light
    assert light["user_preferences"]["color_scheme_dark"]["background_color"] == "#1a1b26", light
    assert "Sec-CH-Prefers-Color-Scheme" in h["Vary"], h["Vary"]
    night = json.loads(call(port, "GET", "/manifest.webmanifest", {"Sec-CH-Prefers-Color-Scheme": "light",
                                                                  "Cookie": "theme=night"})[2])
    assert night["background_color"] == "#1a1b26", night
    assert call(port, "GET", "/")[1]["Accept-CH"] == "Sec-CH-Prefers-Color-Scheme"
    # a chosen theme (vaultkit 0.15): the page wears it, the manifest uses its colours, Settings offers it
    cookie = {"Cookie": "palette=catppuccin; theme=day"}
    assert json.loads(call(port, "GET", "/manifest.webmanifest", cookie)[2])["background_color"] == "#eff1f5"
    assert 'class="theme-day palette-catppuccin' in call(port, "GET", "/", cookie)[2]
    assert '<option value="catppuccin" selected>Catppuccin</option>' in call(port, "GET", "/settings", cookie)[2]

    # the share target is a GET: the Capture form, prefilled, and nothing written until that form posts
    assert manifest["share_target"] == {"action": "/share", "method": "GET",
                                        "params": {"title": "title", "text": "text", "url": "url"}}, manifest
    st, _, body = call(port, "GET", "/share?title=A+lantern&url=https%3A%2F%2Fexample.com%2Fl&text=look")
    assert st == 200 and 'name="title" value="A lantern"' in body and 'value="https://example.com/l"' in body \
        and 'name="text" value="look"' in body and 'method="post" action="/share"' in body, body[-1500:]
    assert len(json.loads(call(port, "GET", "/api/cards")[2])["cards"]) == 1          # a GET makes no card
    form = {"Origin": "http://127.0.0.1:%d" % port, "Content-Type": "application/x-www-form-urlencoded"}
    st, h, _ = call(port, "POST", "/share", form, b"title=A+lantern&url=https%3A%2F%2Fexample.com%2Fl&area=projects")
    assert st == 302 and h["Location"].startswith("/p/"), (st, h["Location"])
    for bad in ({}, {"Origin": "null"}):                             # the form's post stays same-origin only
        h0 = {"Content-Type": "application/x-www-form-urlencoded"}; h0.update(bad)
        assert call(port, "POST", "/share", h0, b"title=x")[0] == 403, bad

    # board.js: no alert() for a write that failed (an inline line or a toast says so), and it posts the forms itself
    js = call(port, "GET", "/static/board.js")[2]
    assert "gardenBase" not in js and "dataset.app" not in js
    assert "Tailscale" not in js and 'const roots = ["/", "/now", "/review", "/plan", "/posts", "/calendar", "/roundup"]' in js
    assert '"kanban.col", "konbini.col"' in js and 'stored("kanban' not in js and 'store("kanban' not in js
    assert 'document.querySelector("main#board")' in js and 'getElementById("board")' not in js   # Settings has h2#board
    assert '<h2 id="board">' in call(port, "GET", "/settings")[2]
    assert "alert(" not in js and 'document.addEventListener("submit"' in js and "You're offline" in js

    # -- the card sheet's links: Niwa only when it's configured and the note is published, Kura when configured -----
    st, _, body = call(port, "GET", "/")
    assert "data-garden=" not in body and "data-kura=" not in body and "data-publish" not in body
    assert "Garden preview" not in js and "Read in the Garden" in js and "View in Kura" in js
    lantern = NOTE.replace("title: Kura", "title: Lantern").replace("project: kura", "project: lantern") \
        .replace("status: wip", "status: ready\npublish: true")
    port6 = start(notes={"Lantern": lantern}, KANBAN_NIWA_URL="https://niwa.example", KANBAN_KURA_URL="https://kura.example",
                  KANBAN_OBSIDIAN_VAULT="notes")
    body = call(port6, "GET", "/")[2]
    kura_card = re.search(r'<article [^>]*id="c-kura"[^>]*>', body).group(0)
    lantern_card = re.search(r'<article [^>]*id="c-lantern"[^>]*>', body).group(0)
    assert 'data-kura="https://kura.example/n/Projects/Kura"' in kura_card and "data-garden" not in kura_card, kura_card
    assert 'data-garden="https://niwa.example/n/Projects/Lantern"' in lantern_card, lantern_card
    body = call(port6, "GET", "/p/kura")[2]
    assert ">Kura</a>" in body and ">Obsidian</a>" in body and "Edit in Obsidian" not in body

    # -- an empty column says so ---------------------------------------------------------------------------------
    body = call(port, "GET", "/")[2]
    assert body.count('<p class="colempty">No cards</p>') == 3, body.count("colempty")   # Kura in WIP, the capture in Backlog
    assert 'p.textContent = "No cards"' in js                       # and one emptied by a move, too

    # -- the calendar's projects: no arrow to nothing for a project that hasn't finished --------------------------
    import datetime, common, modern
    d = datetime.date
    month = {"start": d(2026, 9, 1), "end": d(2026, 10, 1), "days": {}, "prev": d(2026, 8, 1), "next": d(2026, 10, 1),
             "spans": [(d(2026, 9, 2), None, {"slug": "a", "title": "A", "board": "wip"}),
                       (d(2026, 9, 3), d(2026, 9, 9), {"slug": "b", "title": "B", "board": "done"})]}
    dates = re.findall(r'<span class="gdates">(.*?) <span', modern.calendar(common.Ctx("night"), month, []))
    assert dates == ["Sep 02", "Sep 03 &rarr; Sep 09"], dates

    # -- the service worker never stores the sign-in page (nor search, settings, capture) ---------------------------
    st, h, sw_js = call(port, "GET", "/sw.js")
    sw = json.loads(re.search(r"machiyaSW\((.*?)\);\n", sw_js, re.S).group(1))
    # the outbox (outbox.js) is precached, and the worker sends it on Background Sync; the APIs stay untouched
    outbox = [u for u in sw["precache"] if u.startswith("/static/outbox.js?v=")]
    assert outbox and "importScripts(%s)" % json.dumps(outbox[0]) in sw_js and "KonbiniOutbox.SYNC" in sw_js, sw_js[-400:]
    assert sw["bypass"] == ["^/api/"], sw["bypass"]
    network = sw["network"]
    assert {"^/signin$", "^/search$", "^/settings$", "^/share$"} <= set(network), network
    # it precaches the icons pages and the installed app really ask for, and every one of them answers
    icons = [u for u in sw["precache"] if u.startswith("/static/icons/")]
    assert sorted(icons) == ["/static/icons/konbini-192.png", "/static/icons/konbini-apple-180.png",
                             "/static/icons/konbini-small.svg", "/static/icons/konbini.ico"], icons
    for u in sw["precache"]:
        assert call(port, "GET", u)[0] == 200, u
    # board.js loads Sortable from the versioned URL the worker precached
    sortable = re.search(r'data-sortable="([^"]+)"', call(port, "GET", "/")[2]).group(1)
    assert sortable in sw["precache"] and "?v=" in sortable, (sortable, sw["precache"])

    # -- preferences without an identity file (vaultkit 0.12): open mode's owner -------------------------------------
    PREFS_META = '<meta name="machiya-prefs" content="/api/prefs">'
    st, h, body = call(port, "GET", "/api/prefs")
    assert st == 200 and json.loads(body) == {"v": 1, "rev": 0, "prefs": {}, "updated": {}} and h["Cache-Control"] == "no-store", (st, body)
    st, _, body = call(port, "GET", "/settings")
    assert PREFS_META in body and "Kept in this browser" in body and 'id="account"' not in body, body[:600]
    assert 'class="iconbtn who"' not in body                        # nobody signed in: no person button
    # open mode over plain http without KANBAN_BOARD_URL: the request's own (allowed) Host is the origin to trust
    same = {"Origin": "http://127.0.0.1:%d" % port, "Content-Type": "application/json"}
    st, _, body = call(port, "PUT", "/api/prefs", same, b'{"prefs": {"theme": "day"}}')
    assert st == 200 and json.loads(body)["prefs"] == {"theme": "day"}, (st, body)
    for bad in ({"Origin": "http://evil.example"}, {"Origin": "http://127.0.0.1:1"}, {"Origin": "null"}, {}):
        h0 = dict(same); h0.pop("Origin"); h0.update(bad)
        assert call(port, "PUT", "/api/prefs", h0, b'{"prefs": {"theme": "night"}}')[0] == 403, bad
    # a rebinding name never gets that far (the Host rule refuses it first)
    assert call(port, "PUT", "/api/prefs", dict(same, Host="evil.example", Origin="http://evil.example"),
                b'{"prefs": {}}')[0] == 403
    assert json.loads(call(port, "GET", "/api/prefs")[2])["prefs"] == {"theme": "day"}
    port2 = start(board_url=True)
    origin2 = {"Origin": "http://127.0.0.1:%d" % port2, "Content-Type": "application/json"}
    st, _, body = call(port2, "PUT", "/api/prefs", origin2, b'{"prefs": {"theme": "night"}}')
    assert st == 200 and json.loads(body)["prefs"] == {"theme": "night"}, (st, body)
    assert json.loads(call(port2, "GET", "/api/prefs")[2])["prefs"] == {"theme": "night"}
    assert call(port2, "PUT", "/api/prefs", dict(origin2, Origin="http://evil.example"), b'{"prefs": {}}')[0] == 403

    # Tailscale without a file: the login the gate let in; nobody else gets past the gate
    port3 = start(KANBAN_AUTH="tailscale", KANBAN_TAILNET_USERS="owner@example")
    me = {"Tailscale-User-Login": "owner@example"}
    assert call(port3, "GET", "/api/prefs")[0] == 403
    assert call(port3, "GET", "/api/prefs", {"Tailscale-User-Login": "other@example"})[0] == 403
    assert call(port3, "GET", "/api/prefs", me)[0] == 200
    assert PREFS_META in call(port3, "GET", "/now", me)[2]

    # -- with an identity file: the signed-in person in the header, Settings, Account (#account) -----------------
    port4 = start(identity_file=True, KANBAN_SIGNIN="1", board_url=True, KANBAN_AUTH="tailscale")
    form = "name=owner&password=%s&next=/" % OWNER_PW.replace(" ", "+")
    st, h, _ = call(port4, "POST", "/signin", {"Origin": "http://127.0.0.1:%d" % port4,
                                                "Content-Type": "application/x-www-form-urlencoded"}, form.encode())
    assert st == 303, st
    owner = {"Cookie": h["Set-Cookie"].split(";")[0]}
    st, _, body = call(port4, "GET", "/settings", owner)
    assert st == 200 and PREFS_META in body and 'href="/settings#account"' in body, body[:800]
    assert '<h2 id="account">Account</h2>' in body and 'action="/signout"' in body and "Saved for you in Konbini" in body
    st, h, body = call(port4, "GET", "/signin")
    assert PREFS_META not in body                                   # nobody known: the page never asks
    csps = h.get_all("Content-Security-Policy")
    assert any("script-src 'self'" in c for c in csps) and any("frame-ancestors 'none'" in c for c in csps), csps   # the sign-in page

    # -- the 401 page: vaultkit's (plain header, the way in, no Rooms switcher, no prefs), with the security headers
    st, h, body = call(port4, "GET", "/p/kura?x=1", {"Accept": "text/html"})
    assert st == 401 and "<title>Sign In - Konbini</title>" in body and "Konbini is private." in body, (st, body[-800:])
    assert 'href="/signin?next=%2Fp%2Fkura%3Fx%3D1"' in body and 'class="rooms' not in body and PREFS_META not in body
    assert '<p class="item">' not in body                           # the old page's sentence broke into a grid
    assert any("script-src 'self'" in c for c in h.get_all("Content-Security-Policy")) and h["Cache-Control"] == "no-store"
    # the file without sign-in: a browser learns how Konbini knows people; anything else keeps the plain text
    port5 = start(identity_file=True, KANBAN_AUTH="tailscale")
    st, h, body = call(port5, "GET", "/", {"Accept": "text/html,*/*"})
    assert st == 401 and "Who Are You?" in body and "/signin" not in body, (st, body[-600:])
    st, h, body = call(port5, "GET", "/")
    assert st == 401 and h["Content-Type"].startswith("text/plain"), (st, h["Content-Type"])

    print("pages tests: all passed")

finally:
    for p in procs:
        p.kill()
