"""The outbox: card changes made while the board can't be reached wait on the device (static/outbox.js, board.js) and
are sent in order when it is back, each with what it was based on, so the board's own rule refuses a field somebody
changed meanwhile. The server half (the card form's o_board) always runs; the browser half needs Playwright for Python
with its Chromium (it says so and skips otherwise). The browser is taken offline and back the way airplane mode does it
(navigator.onLine, the online event, every request failing), with the installed app's display mode emulated, while
the board's cards are changed and deleted behind its back."""
import json, os, re, socket, subprocess, sys, tempfile, textwrap, time, urllib.error, urllib.request
from urllib.parse import urlencode

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, APP)
from vaultkit import identity  # noqa: E402

SERVER = textwrap.dedent('''
    import sys
    sys.path.insert(0, sys.argv[1])
    import threading
    import app
    app.store.rebuild()
    threading.Thread(target=app.writer.worker, daemon=True).start()   # commits, and notices a deleted note (verify)
    app.serve(int(sys.argv[2]), "tailnet")
''')
OWNER_PW = "owner pass 1"
procs = []


def note(title, status="ready", next_=""):
    return ("---\ntitle: %s\ncreated: 2026-09-01\ntags:\n  - type/project\n  - area/projects\nstatus: %s\n%s---\n# %s\n"
            % (title, status, ("next: %s\n" % next_) if next_ else "", title))


def start(signin=False):
    """A board on a free port with five cards in one lane -> (port, vault folder)."""
    d = tempfile.mkdtemp(dir=os.environ.get("TMPDIR_BIG", "/var/tmp" if os.path.isdir("/var/tmp") else None))
    os.makedirs(d + "/vault/Projects")
    for slug, text in (("alpha", note("Alpha")), ("bravo", note("Bravo", next_="old step")), ("charlie", note("Charlie")),
                       ("delta", note("Delta")), ("echo", note("Echo"))):
        open(d + "/vault/Projects/%s.md" % slug, "w").write(text)
    subprocess.run(["git", "-C", d + "/vault", "init", "-q"], check=True)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, KANBAN_REPO=d + "/vault", KANBAN_DB=d + "/db/k.db", KANBAN_TAILNET_PORT=str(port),
               KANBAN_BIND="127.0.0.1", KANBAN_AUTH="open", KANBAN_VERIFY_SECONDS="1", KANBAN_EXPORT_IDLE="1", PYTHONDONTWRITEBYTECODE="1")
    for k in ("KANBAN_AUTH_HEADER", "KANBAN_SIGNIN", "KANBAN_BOARD_URL", "KANBAN_NIWA_URL", "KANBAN_KURA_URL",
              "KANBAN_TAILNET_USERS", "MACHIYA_IDENTITY_FILE", "MACHIYA_COOKIE_DOMAIN", "MACHIYA_ROOMS"):
        env.pop(k, None)
    if signin:
        os.makedirs(d + "/identity")
        open(d + "/identity/session.key", "w").write("k" * 43)
        path = d + "/identity/identity.toml"
        identity.write_file(path, {"version": 1, "session_key_file": "session.key", "principals": {
            "owner": {"id": "ownerid000000001", "kind": "person", "owner": True,
                      "password": identity.hash_password(OWNER_PW)}}})
        env.update(MACHIYA_IDENTITY_FILE=path, KANBAN_SIGNIN="1", KANBAN_AUTH="tailscale",
                   KANBAN_BOARD_URL="http://127.0.0.1:%d" % port)
    open(d + "/server.py", "w").write(SERVER)
    proc = subprocess.Popen([sys.executable, d + "/server.py", APP, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    procs.append(proc)
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return port, d
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("board did not start: " + proc.stderr.read().decode()[-500:])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(port, method, path, headers=None, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, method=method,
                                 headers=dict({"Host": "127.0.0.1:%d" % port}, **(headers or {})))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode("utf-8", "replace")


def card(port, slug):
    st, _, body = call(port, "GET", "/api/cards/" + slug)
    return json.loads(body) if st == 200 else None


def agent_patch(port, slug, fields):
    """Somebody else's change (an agent on the API) while the browser is offline."""
    st, _, body = call(port, "PATCH", "/api/cards/" + slug, {"Content-Type": "application/json", "X-Agent": "test"},
                       json.dumps(fields).encode())
    assert st == 200, (st, body)


def until(what, check, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(0.2)
    raise AssertionError("timed out waiting for " + what)


FORM = {"Content-Type": "application/x-www-form-urlencoded"}

try:
    port, vault = start()
    same = dict(FORM, Origin="http://127.0.0.1:%d" % port)

    # -- the server half: the card form refuses a move based on a column the card has left (o_board) -----------------
    st, h, _ = call(port, "POST", "/p/alpha", same, urlencode({"board": "wip", "o_board": "ready"}).encode())
    assert st == 302 and card(port, "alpha")["board"] == "wip", st
    st, _, body = call(port, "POST", "/p/alpha", same, urlencode({"board": "done", "o_board": "ready"}).encode())
    assert st == 409 and "changed since" in body and card(port, "alpha")["board"] == "wip", (st, body[-300:])
    # without an original (an old page, the quick-move form) a move is taken as before
    st, _, _ = call(port, "POST", "/p/alpha", same, urlencode({"board": "ready"}).encode())
    assert st == 302 and card(port, "alpha")["board"] == "ready", st
    # the pages carry what a change made offline is based on
    st, _, body = call(port, "GET", "/")
    assert re.search(r'data-slug="bravo"[^>]*data-next="old step"[^>]*data-priority=""', body), body[:300]
    st, _, body = call(port, "GET", "/p/alpha")
    assert 'class="moves" method="post" action="/move" data-board="ready"' in body
    print("outbox server tests: all passed")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("outbox browser tests: skipped (no Playwright for Python)")
        raise SystemExit(0)

    BASE = "http://127.0.0.1:%d" % port
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as exc:                                     # Playwright without its Chromium
            print("outbox browser tests: skipped (%s)" % str(exc).splitlines()[0][:120])
            raise SystemExit(0)
        ctx = br.new_context(viewport={"width": 1280, "height": 900}, service_workers="allow")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # the installed app, as a home-screen app reports itself (Chromium can't emulate display-mode: standalone)
        ctx.add_init_script("Object.defineProperty(Navigator.prototype, 'standalone', {get: () => true})")
        page.goto(BASE + "/")
        page.evaluate("navigator.serviceWorker.ready")
        if not page.evaluate("!!navigator.serviceWorker.controller"):
            page.reload()
        assert page.evaluate("!!navigator.serviceWorker.controller"), "the worker should control the page"
        page.goto(BASE + "/")                                       # a navigation the worker keeps for offline use

        def go(url):
            """A navigation, again if the board's own reload (a revision it was told about) cut it short."""
            for attempt in range(3):
                try:
                    page.goto(url)
                    return
                except Exception as exc:
                    if "ERR_ABORTED" not in str(exc) or attempt == 2:
                        raise
                    page.wait_for_load_state()

        def col_of(slug):
            return page.eval_on_selector('.card[data-slug="%s"]' % slug, "e => e.closest('.col').dataset.board")

        def badge():
            el = page.query_selector(".outboxbadge")
            return el.inner_text() if el else ""

        def sheet_move(slug, to):
            page.click('.card[data-slug="%s"] .more' % slug)
            page.click('dialog.sheet [data-move="%s"]' % to)

        # -- airplane mode: changes wait on the device, applied and marked --------------------------------------------
        ctx.set_offline(True)
        assert page.evaluate("navigator.onLine") is False
        sheet_move("alpha", "wip")
        until("alpha in WIP", lambda: col_of("alpha") == "wip")
        assert page.is_visible('.card[data-slug="alpha"] .chip.waiting'), "a queued change is marked"
        until("the badge", lambda: badge() == "1 waiting")
        page.click('.card[data-slug="bravo"] .next')
        page.fill("input.inline-next", "my step")
        page.keyboard.press("Enter")
        until("bravo queued", lambda: badge() == "2 waiting")
        sheet_move("charlie", "blocked")
        sheet_move("delta", "done")
        page.fill(".newform input[name=title]", "Offline idea")
        page.click(".newform button[type=submit]")
        until("the stand-in card", lambda: page.query_selector('.col-backlog .card.queued[data-slug^="tmp-"]'))
        tmp = page.get_attribute('.card[data-slug^="tmp-"]', "data-slug")
        sheet_move(tmp, "ready")                                     # a change to a card the board doesn't have yet
        until("six waiting", lambda: badge() == "6 waiting")
        assert page.evaluate("navigator.onLine") is False and card(port, "alpha")["board"] == "ready"   # nothing sent

        # the app is closed and opened again, still offline: the board's offline copy, with the waiting changes on it
        page.reload()
        assert page.is_visible(".banner.offline"), "the offline copy says so"
        until("re-applied", lambda: col_of("alpha") == "wip" and badge() == "6 waiting")
        assert page.inner_text('.card[data-slug="bravo"] .next') == "next: my step"
        assert col_of(tmp) == "ready" and page.is_visible('.card[data-slug="%s"] .chip.waiting' % tmp)

        # -- meanwhile, on the board: bravo's next and delta's column change, charlie is deleted ------------------------
        agent_patch(port, "bravo", {"next": "their step"})
        agent_patch(port, "delta", {"board": "blocked"})
        os.remove(vault + "/vault/Projects/charlie.md")
        until("charlie gone", lambda: card(port, "charlie") is None, 45)

        # -- back online: sent in order; what changed meanwhile waits for the person ----------------------------------
        ctx.set_offline(False)
        until("alpha sent", lambda: card(port, "alpha")["board"] == "wip")
        made = until("the new card, moved", lambda: [c for c in json.loads(call(port, "GET", "/api/cards")[2])["cards"]
                                                     if c["title"] == "Offline idea" and c["board"] == "ready"])
        assert len(made) == 1, made                                   # created once, then moved under its real slug
        assert card(port, "bravo")["next"] == "their step" and card(port, "delta")["board"] == "blocked"   # not overwritten
        until("the page after the send", lambda: page.query_selector(".outboxbadge") and badge() == "3 to check")
        page.click(".outboxbadge")
        text = page.inner_text("dialog.outbox")
        assert "The board now has next “their step”." in text, text
        assert "This card is gone from the board." in text and "The board now has Blocked." in text, text
        li = lambda title: 'dialog.outbox li:has(b:text-is("%s"))' % title
        assert page.is_visible(li("Charlie") + " [data-drop]") and not page.query_selector(li("Charlie") + " [data-keep]")
        page.click(li("Bravo") + " [data-keep]")                       # Keep Mine
        until("bravo kept", lambda: card(port, "bravo")["next"] == "my step")
        page.click(li("Delta") + " [data-drop]")                       # Use the Board's
        page.click(li("Charlie") + " [data-drop]")                     # Dismiss
        until("the outbox empty", lambda: page.evaluate("KonbiniOutbox.all().then(o => o.length)") == 0)
        assert card(port, "delta")["board"] == "blocked"
        page.keyboard.press("Escape")
        until("no badge", lambda: not page.query_selector(".outboxbadge"))

        # -- the card page: a field edit and a note, offline; the form's originals follow the queued change -----------
        go(BASE + "/p/echo")
        assert page.is_visible(".topbar button.back"), "an inner page of the installed app has its back control"
        ctx.set_offline(True)
        page.fill(".editform input[name=next]", "first")
        page.click(".editform button[type=submit]")
        until("saved here", lambda: "Saved on this device" in (page.inner_text(".formmsg") or ""))
        page.fill(".editform input[name=next]", "second")
        page.fill(".editform input[name=comment]", "written on a plane")
        page.click(".editform button[type=submit]")
        until("both waiting", lambda: badge() == "2 waiting")
        assert "Not on the board yet" in page.inner_text(".waitmsg")
        page.click('form.moves button[value="wip"]')                  # the column buttons, too
        until("three waiting", lambda: badge() == "3 waiting")
        ctx.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        until("echo sent", lambda: card(port, "echo")["next"] == "second" and card(port, "echo")["board"] == "wip")
        events = json.loads(call(port, "GET", "/api/cards/echo/events")[2])
        assert any(e.get("body") == "written on a plane" for e in (events if isinstance(events, list) else events.get("events", []))), events
        until("echo's outbox empty", lambda: page.evaluate("KonbiniOutbox.all().then(o => o.length)") == 0)

        # -- online, nothing waiting: a change goes straight to the board as before ------------------------------------
        go(BASE + "/")
        sheet_move("echo", "done")
        until("echo done", lambda: card(port, "echo")["board"] == "done")
        assert page.evaluate("KonbiniOutbox.all().then(o => o.length)") == 0 and not page.query_selector(".outboxbadge")
        assert not errors, errors
        ctx.close()

        # -- signed out meanwhile: the queue holds (401) until the person signs in again --------------------------------
        sport, _ = start(signin=True)
        SB = "http://127.0.0.1:%d" % sport
        ctx = br.new_context(viewport={"width": 390, "height": 844}, service_workers="allow")
        page = ctx.new_page()
        page.goto(SB + "/signin?next=/")
        page.fill("input[name=name]", "owner")
        page.fill("input[name=password]", OWNER_PW)
        page.click("form button[type=submit]")
        page.wait_for_url(SB + "/")
        ctx.set_offline(True)
        page.evaluate("document.querySelector('.card[data-slug=\"alpha\"] .more').click()")
        page.click('dialog.sheet [data-move="wip"]')
        until("queued", lambda: badge() == "1 waiting")
        cookies = ctx.cookies()
        ctx.clear_cookies()                                          # the session ended meanwhile
        ctx.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        until("asked to sign in", lambda: "Sign in to send" in (page.inner_text("body")))
        assert page.evaluate("KonbiniOutbox.all().then(o => o.map(x => x.state))") == ["waiting"]   # held, not dropped
        ctx.add_cookies(cookies)                                     # signed in again
        page.evaluate("window.dispatchEvent(new Event('online'))")
        until("sent after sign-in", lambda: page.evaluate("KonbiniOutbox.all().then(o => o.length)") == 0)
        st, _, body = call(sport, "GET", "/api/cards/alpha", {"Cookie": "; ".join("%s=%s" % (c["name"], c["value"]) for c in cookies)})
        assert json.loads(body)["board"] == "wip", (st, body[:200])
        # the queue keeps no credentials: only the change itself
        stored = page.evaluate("indexedDB.databases().then(() => KonbiniOutbox.all())")
        assert stored == [] and not errors, (stored, errors)
        br.close()
    print("outbox browser tests: all passed")

finally:
    for p in procs:
        p.kill()
